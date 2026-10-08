/**
 * Centralized API client for Dayform.
 *
 * Handles base URL, auth token attachment, automated demo authentication
 * for local development, JSON parsing, and friendly error reporting.
 */

import {
  clearPersistedAuthSession,
  clearPersistedWorkspaceState,
  extractJwtSubject,
  isValidJwtAccessToken,
  loadPersistedAuthSession,
  loadPersistedWorkspaceState,
  savePersistedAuthSession,
} from '../utils/persistedState.ts';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api/v1';

export const DEFAULT_REQUEST_TIMEOUT_MS = 45_000;
export const COLD_START_TIMEOUT_MS = 90_000;

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
}

export interface ApiError extends Error {
  status?: number;
  rawDetail?: string;
}

let authToken: string | null = null;
let refreshToken: string | null = null;
let lastKnownUserId: string | null = null;
let sharedSessionPromise: Promise<string> | null = null;

/**
 * Translates raw technical API, auth, or network errors into calm,
 * user-friendly messages so raw JWT/HTTP strings never surface in the UI.
 */
export function toUserFriendlyErrorMessage(rawMessage: string, status?: number): string {
  const normalized = (rawMessage || '').trim();

  if (
    status === 401 ||
    /access token|invalid or expired|existing user|validate credentials|401|unauthorized|authentication failed|malformed access token/i.test(
      normalized
    )
  ) {
    return "Your session needed refreshing. We've taken care of it — please try again.";
  }

  if (
    status === 408 ||
    status === 502 ||
    status === 503 ||
    status === 504 ||
    /took too long|taking a little longer|timeout|timed out|aborted|aborterror|unable to connect|failed to fetch|networkerror|load failed/i.test(
      normalized
    )
  ) {
    return 'Dayform is taking a little longer than usual. Please try again.';
  }

  if ((status && status >= 500) || /^request failed \(\d+\)$/i.test(normalized) || !normalized) {
    return "We couldn't finish building this plan. Your request is still safe — try again.";
  }

  return normalized;
}

function createApiError(rawDetail: string, status?: number): ApiError {
  const friendly = toUserFriendlyErrorMessage(rawDetail, status);
  const error = new Error(friendly) as ApiError;
  error.rawDetail = rawDetail;
  if (status !== undefined) {
    error.status = status;
  }
  return error;
}

function hasStorageAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage);
  } catch {
    return false;
  }
}

const TRANSIENT_GATEWAY_STATUSES = new Set([502, 503, 504]);

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<Response> {
  const maxAttempts = 3;
  const retryDelaysMs = timeoutMs >= 5_000 ? [1_200, 2_500] : [10, 20];
  const startedAt = Date.now();

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const elapsed = Date.now() - startedAt;
    const remainingTimeoutMs = Math.max(timeoutMs - elapsed, 15);
    const controller = new AbortController();
    const externalSignal = init.signal;
    if (externalSignal) {
      if (externalSignal.aborted) {
        controller.abort();
      } else {
        externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
      }
    }

    const timer = setTimeout(() => controller.abort(), remainingTimeoutMs);
    try {
      const response = await fetch(url, {
        ...init,
        signal: controller.signal,
      });

      if (
        TRANSIENT_GATEWAY_STATUSES.has(response.status) &&
        attempt < maxAttempts - 1 &&
        !externalSignal?.aborted
      ) {
        const delay = retryDelaysMs[attempt] ?? 1_500;
        if (Date.now() - startedAt + delay < timeoutMs) {
          await sleepMs(delay);
          continue;
        }
      }

      return response;
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        throw createApiError('The planning service took too long to respond.', 408);
      }
      if (attempt < maxAttempts - 1 && !externalSignal?.aborted) {
        const delay = retryDelaysMs[attempt] ?? 1_500;
        if (Date.now() - startedAt + delay < timeoutMs) {
          await sleepMs(delay);
          continue;
        }
      }
      if (err instanceof Error) {
        throw createApiError(err.message);
      }
      throw createApiError('Unable to connect to API backend.');
    } finally {
      clearTimeout(timer);
    }
  }

  throw createApiError('Unable to connect to API backend.');
}

function syncSessionFromStorage(): void {
  if (!hasStorageAvailable()) {
    return;
  }
  const session = loadPersistedAuthSession();
  if (session) {
    authToken = session.accessToken || null;
    refreshToken = session.refreshToken;
    const sub = authToken ? extractJwtSubject(authToken) : null;
    if (sub) {
      lastKnownUserId = sub;
    }
  } else {
    authToken = null;
    refreshToken = null;
  }
}

// Hydrate validated session on module load (automatically removes expired/corrupt legacy tokens)
syncSessionFromStorage();

function persistTokens(newAccessToken: unknown, newRefreshToken?: unknown): string {
  if (typeof newAccessToken !== 'string' || !newAccessToken.trim()) {
    clearPersistedAuthSession();
    authToken = null;
    refreshToken = null;
    throw createApiError('Authentication response did not include a valid access token.', 401);
  }

  const cleanAccess = newAccessToken.trim();
  const newUserId = extractJwtSubject(cleanAccess);
  if (!newUserId) {
    clearPersistedAuthSession();
    authToken = null;
    refreshToken = null;
    throw createApiError('Authentication response returned a malformed access token.', 401);
  }

  // If the backend database was reset/reseeded and issued a different user UUID,
  // any persisted workspace plan ID from the old user is no longer valid on the server.
  if (lastKnownUserId && lastKnownUserId !== newUserId) {
    clearPersistedWorkspaceState();
  }
  // Also validate any workspace state currently in storage against the new userId
  if (hasStorageAvailable()) {
    loadPersistedWorkspaceState(undefined, Date.now(), newUserId);
  }
  lastKnownUserId = newUserId;

  const cleanRefresh =
    typeof newRefreshToken === 'string' && newRefreshToken.trim().length > 0
      ? newRefreshToken.trim()
      : null;

  authToken = cleanAccess;
  refreshToken = cleanRefresh;
  savePersistedAuthSession(cleanAccess, cleanRefresh);
  return cleanAccess;
}

export type RefreshResult =
  | { success: true; token: string }
  | { success: false; reason: 'invalid_token' | 'transient_error'; error?: unknown };

export async function tryRefreshSession(
  tokenToRefresh: string,
  timeoutMs: number = COLD_START_TIMEOUT_MS
): Promise<RefreshResult> {
  try {
    const response = await fetchWithTimeout(
      `${API_BASE}/auth/refresh`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokenToRefresh }),
      },
      timeoutMs
    );
    if (response.ok) {
      const data = await response.json();
      if (typeof data?.access_token === 'string' && isValidJwtAccessToken(data.access_token.trim())) {
        const token = persistTokens(data.access_token, data.refresh_token ?? tokenToRefresh);
        return { success: true, token };
      }
      return { success: false, reason: 'invalid_token' };
    }
    if (
      response.status === 400 ||
      response.status === 401 ||
      response.status === 403 ||
      response.status === 422
    ) {
      return { success: false, reason: 'invalid_token' };
    }
    return { success: false, reason: 'transient_error' };
  } catch (err: unknown) {
    return { success: false, reason: 'transient_error', error: err };
  }
}

async function createAnonymousSession(
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<string> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${API_BASE}/auth/anonymous-session`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      },
      timeoutMs
    );
  } catch (netErr) {
    console.error('Network failure during anonymous session creation:', netErr);
    if (netErr instanceof Error) {
      throw createApiError(netErr.message, (netErr as ApiError).status);
    }
    throw createApiError('Unable to connect to API backend.');
  }

  if (!response.ok) {
    let errorDetail = '';
    try {
      const errJson = await response.json();
      errorDetail = typeof errJson.detail === 'string' ? `: ${errJson.detail}` : '';
    } catch {
      // body not json
    }
    throw createApiError(
      `Anonymous session creation failed (${response.status})${errorDetail}`,
      response.status
    );
  }

  const data = await response.json();
  return persistTokens(data?.access_token, data?.refresh_token);
}

async function runSessionInitialization(
  forceRefresh = false,
  rejectedToken?: string | null,
  timeoutMs: number = COLD_START_TIMEOUT_MS
): Promise<string> {
  if (!forceRefresh) {
    syncSessionFromStorage();
    if (authToken && isValidJwtAccessToken(authToken)) {
      // Proactively wake up backend if needed (cold-start resilience)
      try {
        await fetchWithTimeout(`${API_BASE}/health`, { method: 'GET' }, timeoutMs);
      } catch {
        // Silent health ping failure; keep existing valid token
      }
      return authToken;
    }
  } else {
    // Check if another concurrent request already updated storage with a fresh token
    syncSessionFromStorage();
    if (
      rejectedToken &&
      authToken &&
      authToken !== rejectedToken &&
      isValidJwtAccessToken(authToken)
    ) {
      return authToken;
    }
  }

  // Session needs authentication or refresh.
  // Prefer /auth/refresh (0.485s, SHA-256) over bcrypt login (2.3s+ 100% CPU on Render).
  if (refreshToken) {
    const refreshResult = await tryRefreshSession(refreshToken, timeoutMs);
    if (refreshResult.success) {
      return refreshResult.token;
    }
    if (refreshResult.reason === 'invalid_token') {
      // Explicit server rejection (400/401/403/422): clear session and fall back to anonymous session
      clearPersistedAuthSession();
      authToken = null;
      refreshToken = null;
    } else {
      // Transient error (502, 503, 504, timeout, network failure):
      // PRESERVE refresh token in storage!
      throw createApiError(
        'Dayform is taking a little longer than usual. Please try again.',
        503
      );
    }
  } else {
    clearPersistedAuthSession();
    authToken = null;
    refreshToken = null;
  }

  return await createAnonymousSession(timeoutMs);
}

export async function ensureAuthToken(
  forceRefresh = false,
  rejectedToken?: string | null,
  timeoutMs: number = COLD_START_TIMEOUT_MS
): Promise<string> {
  if (!forceRefresh) {
    syncSessionFromStorage();
    if (authToken && isValidJwtAccessToken(authToken)) {
      if (sharedSessionPromise) {
        return sharedSessionPromise;
      }
      return authToken;
    }
  }

  // If a session initialization is already in flight, await it first
  if (sharedSessionPromise) {
    try {
      const recovered = await sharedSessionPromise;
      if (
        !forceRefresh ||
        (recovered && recovered !== rejectedToken && isValidJwtAccessToken(recovered))
      ) {
        return recovered;
      }
    } catch {
      // In-flight initialization errored; fall through to fresh attempt
    }
  }

  if (forceRefresh) {
    // Check if another concurrent request already updated storage with a fresh token
    syncSessionFromStorage();
    if (
      rejectedToken &&
      authToken &&
      authToken !== rejectedToken &&
      isValidJwtAccessToken(authToken)
    ) {
      return authToken;
    }
    authToken = null;
  }

  sharedSessionPromise = (async () => {
    try {
      return await runSessionInitialization(forceRefresh, rejectedToken, timeoutMs);
    } finally {
      sharedSessionPromise = null;
    }
  })();

  return sharedSessionPromise;
}

/**
 * Proactively wakes up the backend service and ensures a valid auth token
 * in the background while the user is on the landing page or typing their
 * intention, eliminating cold-start and bcrypt login latency on submit.
 *
 * Utilizes the shared session initialization promise so concurrent
 * user planning requests await the same in-flight operation without
 * spawning duplicate requests against cold Render instances.
 */
export function warmupBackendSession(): Promise<string | void> {
  if (typeof window === 'undefined') {
    return Promise.resolve();
  }
  syncSessionFromStorage();
  if (authToken && isValidJwtAccessToken(authToken)) {
    if (sharedSessionPromise) {
      return sharedSessionPromise;
    }
    sharedSessionPromise = (async () => {
      try {
        await fetchWithTimeout(`${API_BASE}/health`, { method: 'GET' }, COLD_START_TIMEOUT_MS);
      } catch {
        // Silent health ping failure
      } finally {
        sharedSessionPromise = null;
      }
      return authToken || '';
    })();
    return sharedSessionPromise;
  }
  return ensureAuthToken(false, null, COLD_START_TIMEOUT_MS).catch(() => {
    // Silent background warmup — foreground user actions will retry cleanly if needed
  });
}

export function _resetClientAuthForTesting(): void {
  authToken = null;
  refreshToken = null;
  lastKnownUserId = null;
  sharedSessionPromise = null;
}

export async function apiClient<T>(
  endpoint: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...requestInit } = options;
  const token = await ensureAuthToken(false, null, timeoutMs);

  const executeRequest = async (bearerToken: string): Promise<Response> => {
    const incomingHeaders = new Headers(requestInit.headers);
    const headersRecord: Record<string, string> = {};
    incomingHeaders.forEach((value, key) => {
      if (key.toLowerCase() !== 'authorization' && key.toLowerCase() !== 'content-type') {
        headersRecord[key] = value;
      }
    });
    headersRecord['Content-Type'] = incomingHeaders.get('Content-Type') || 'application/json';
    // Always overwrite Authorization with the authoritative bearer token
    headersRecord.Authorization = `Bearer ${bearerToken}`;

    return fetchWithTimeout(
      `${API_BASE}${endpoint}`,
      {
        ...requestInit,
        headers: headersRecord,
      },
      timeoutMs
    );
  };

  let response = await executeRequest(token);

  // If the persisted token was rejected by the backend (e.g., expired, secret rotated,
  // or demo user recreated after an ephemeral DB reset), clear it and re-authenticate once.
  if (response.status === 401) {
    const freshToken = await ensureAuthToken(true, token, timeoutMs);
    response = await executeRequest(freshToken);
    if (response.status === 401) {
      clearPersistedAuthSession();
      authToken = null;
      refreshToken = null;
    }
  }

  if (!response.ok) {
    let rawErrorMessage = `Request failed (${response.status})`;
    try {
      const errBody = await response.json();
      if (errBody?.detail) {
        if (typeof errBody.detail === 'string') {
          rawErrorMessage = errBody.detail;
        } else if (Array.isArray(errBody.detail) && errBody.detail[0]?.msg) {
          rawErrorMessage = errBody.detail[0].msg;
        }
      }
    } catch {
      // response was not json
    }
    throw createApiError(rawErrorMessage, response.status);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}
