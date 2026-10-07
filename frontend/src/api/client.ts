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
  savePersistedAuthSession,
} from '../utils/persistedState.ts';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '/api/v1';

export const DEFAULT_REQUEST_TIMEOUT_MS = 45_000;

const DEMO_CREDENTIALS = {
  email: 'demo@dayform.local',
  password: 'DemoPassword123',
} as const;

let authToken: string | null = null;
let refreshToken: string | null = null;
let lastKnownUserId: string | null = null;
let pendingAuthPromise: Promise<string> | null = null;

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
      throw new Error('The planning service took too long to respond. Please try again.');
    }
    throw err;
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
    throw new Error('Authentication response did not include a valid access token.');
  }

  const cleanAccess = newAccessToken.trim();
  const newUserId = extractJwtSubject(cleanAccess);
  if (!newUserId) {
    clearPersistedAuthSession();
    authToken = null;
    refreshToken = null;
    throw new Error('Authentication response returned a malformed access token.');
  }

  // If the backend database was reset/reseeded and issued a different user UUID,
  // any persisted workspace plan ID from the old user is no longer valid on the server.
  if (lastKnownUserId && lastKnownUserId !== newUserId) {
    clearPersistedWorkspaceState();
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

async function tryRefreshSession(tokenToRefresh: string): Promise<string | null> {
  try {
    const response = await fetchWithTimeout(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokenToRefresh }),
    });
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

async function authenticateDemoUser(): Promise<string> {
  let response: Response;
  try {
    response = await fetchWithTimeout(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(DEMO_CREDENTIALS),
    });
  } catch (netErr) {
    console.error('Network failure during authentication:', netErr);
    if (netErr instanceof Error && netErr.message.includes('took too long')) {
      throw netErr;
    }
    throw new Error('Unable to connect to API backend.');
  }

  if (!response.ok) {
    // Try registering demo user first if login failed
    let regRes: Response;
    try {
      regRes = await fetchWithTimeout(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(DEMO_CREDENTIALS),
      });
    } catch (netErr) {
      console.error('Network failure during demo registration:', netErr);
      if (netErr instanceof Error && netErr.message.includes('took too long')) {
        throw netErr;
      }
      throw new Error('Unable to connect to API backend.');
    }

    if (regRes.ok || regRes.status === 409 || regRes.status === 422) {
      let retryLogin: Response;
      try {
        retryLogin = await fetchWithTimeout(`${API_BASE}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(DEMO_CREDENTIALS),
        });
      } catch (netErr) {
        console.error('Network failure during login retry:', netErr);
        if (netErr instanceof Error && netErr.message.includes('took too long')) {
          throw netErr;
        }
        throw new Error('Unable to connect to API backend.');
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
      throw new Error(`Authentication failed (${retryLogin.status})${errorDetail}`);
    }

    let regErrorDetail = '';
    try {
      const errJson = await regRes.json();
      regErrorDetail = typeof errJson.detail === 'string' ? `: ${errJson.detail}` : '';
    } catch {
      // body not json
    }
    throw new Error(`Authentication failed during registration (${regRes.status})${regErrorDetail}`);
  }

  const data = await response.json();
  return persistTokens(data?.access_token, data?.refresh_token);
}

export async function ensureAuthToken(
  forceRefresh = false,
  rejectedToken?: string | null
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
        const refreshed = await tryRefreshSession(refreshToken);
        if (refreshed) {
          return refreshed;
        }
      }
      clearPersistedAuthSession();
      authToken = null;
      refreshToken = null;
      return await authenticateDemoUser();
    } finally {
      pendingAuthPromise = null;
    }
  })();

  return pendingAuthPromise;
}

export async function apiClient<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  let token = await ensureAuthToken(false);

  const executeRequest = async (bearerToken: string): Promise<Response> => {
    const incomingHeaders = new Headers(options.headers);
    const headersRecord: Record<string, string> = {};
    incomingHeaders.forEach((value, key) => {
      if (key.toLowerCase() !== 'authorization' && key.toLowerCase() !== 'content-type') {
        headersRecord[key] = value;
      }
    });
    headersRecord['Content-Type'] = incomingHeaders.get('Content-Type') || 'application/json';
    // Always overwrite Authorization with the authoritative bearer token
    headersRecord.Authorization = `Bearer ${bearerToken}`;

    return fetchWithTimeout(`${API_BASE}${endpoint}`, {
      ...options,
      headers: headersRecord,
    });
  };

  let response = await executeRequest(token);

  // If the persisted token was rejected by the backend (e.g., expired, secret rotated,
  // or demo user recreated after an ephemeral DB reset), clear it and re-authenticate once.
  if (response.status === 401) {
    const freshToken = await ensureAuthToken(true, token);
    response = await executeRequest(freshToken);
    if (response.status === 401) {
      clearPersistedAuthSession();
      authToken = null;
      refreshToken = null;
    }
  }

  if (!response.ok) {
    let errorMessage = `Request failed (${response.status})`;
    try {
      const errBody = await response.json();
      if (errBody?.detail) {
        if (typeof errBody.detail === 'string') {
          errorMessage = errBody.detail;
        } else if (Array.isArray(errBody.detail) && errBody.detail[0]?.msg) {
          errorMessage = errBody.detail[0].msg;
        }
      }
    } catch {
      // response was not json
    }
    const error = new Error(errorMessage);
    (error as unknown as { status: number }).status = response.status;
    throw error;
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}
