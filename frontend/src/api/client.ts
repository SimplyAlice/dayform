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

export const DEFAULT_REQUEST_TIMEOUT_MS = 60_000;

export interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
}

export interface ApiError extends Error {
  status?: number;
  rawDetail?: string;
}

const DEMO_CREDENTIALS = {
  email: 'demo@dayform.local',
  password: 'DemoPassword123',
} as const;

let authToken: string | null = null;
let refreshToken: string | null = null;
let lastKnownUserId: string | null = null;
let pendingAuthPromise: Promise<string> | null = null;

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

async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }

  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw createApiError('The planning service took too long to respond.', 408);
    }
    if (err instanceof Error) {
      throw createApiError(err.message);
    }
    throw createApiError('Unable to connect to API backend.');
  } finally {
    clearTimeout(timer);
  }
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

async function tryRefreshSession(
  tokenToRefresh: string,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<string | null> {
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
    if (!response.ok) {
      return null;
    }
    const data = await response.json();
    if (typeof data?.access_token === 'string' && isValidJwtAccessToken(data.access_token.trim())) {
      return persistTokens(data.access_token, data.refresh_token ?? tokenToRefresh);
    }
    return null;
  } catch {
    return null;
  }
}

async function authenticateDemoUser(
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<string> {
  let response: Response;
  try {
    response = await fetchWithTimeout(
      `${API_BASE}/auth/login`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(DEMO_CREDENTIALS),
      },
      timeoutMs
    );
  } catch (netErr) {
    console.error('Network failure during authentication:', netErr);
    if (netErr instanceof Error) {
      throw createApiError(netErr.message);
    }
    throw createApiError('Unable to connect to API backend.');
  }

  if (!response.ok) {
    // Try registering demo user first if login failed
    let regRes: Response;
    try {
      regRes = await fetchWithTimeout(
        `${API_BASE}/auth/register`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(DEMO_CREDENTIALS),
        },
        timeoutMs
      );
    } catch (netErr) {
      console.error('Network failure during demo registration:', netErr);
      if (netErr instanceof Error) {
        throw createApiError(netErr.message);
      }
      throw createApiError('Unable to connect to API backend.');
    }

    if (regRes.ok || regRes.status === 409 || regRes.status === 422) {
      let retryLogin: Response;
      try {
        retryLogin = await fetchWithTimeout(
          `${API_BASE}/auth/login`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(DEMO_CREDENTIALS),
          },
          timeoutMs
        );
      } catch (netErr) {
        console.error('Network failure during login retry:', netErr);
        if (netErr instanceof Error) {
          throw createApiError(netErr.message);
        }
        throw createApiError('Unable to connect to API backend.');
      }

      if (retryLogin.ok) {
        const data = await retryLogin.json();
        return persistTokens(data?.access_token, data?.refresh_token);
      }

      let errorDetail = '';
      try {
        const errJson = await retryLogin.json();
        errorDetail = typeof errJson.detail === 'string' ? `: ${errJson.detail}` : '';
      } catch {
        // body not json
      }
      throw createApiError(
        `Authentication failed (${retryLogin.status})${errorDetail}`,
        retryLogin.status
      );
    }

    let regErrorDetail = '';
    try {
      const errJson = await regRes.json();
      regErrorDetail = typeof errJson.detail === 'string' ? `: ${errJson.detail}` : '';
    } catch {
      // body not json
    }
    throw createApiError(
      `Authentication failed during registration (${regRes.status})${regErrorDetail}`,
      regRes.status
    );
  }

  const data = await response.json();
  return persistTokens(data?.access_token, data?.refresh_token);
}

export async function ensureAuthToken(
  forceRefresh = false,
  rejectedToken?: string | null,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<string> {
  if (!forceRefresh) {
    syncSessionFromStorage();
    if (authToken && isValidJwtAccessToken(authToken)) {
      return authToken;
    }
    if (pendingAuthPromise) {
      return pendingAuthPromise;
    }
  } else {
    // If an auth recovery is already in flight from a parallel request, wait for it first
    if (pendingAuthPromise) {
      try {
        const recovered = await pendingAuthPromise;
        if (recovered && recovered !== rejectedToken && isValidJwtAccessToken(recovered)) {
          return recovered;
        }
      } catch {
        // Fall through to fresh recovery attempt
      }
    }

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
    refreshToken = null;
    clearPersistedAuthSession();
  }

  pendingAuthPromise = (async () => {
    try {
      if (!forceRefresh && refreshToken) {
        const refreshed = await tryRefreshSession(refreshToken, timeoutMs);
        if (refreshed) {
          return refreshed;
        }
      }
      clearPersistedAuthSession();
      authToken = null;
      refreshToken = null;
      return await authenticateDemoUser(timeoutMs);
    } finally {
      pendingAuthPromise = null;
    }
  })();

  return pendingAuthPromise;
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
