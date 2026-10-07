/**
 * Centralized API client for Dayform.
 *
 * Handles base URL, auth token attachment, automated demo authentication
 * for local development, JSON parsing, and friendly error reporting.
 */

import {
  clearPersistedAuthSession,
  isValidJwtAccessToken,
  loadPersistedAuthSession,
  savePersistedAuthSession,
} from '../utils/persistedState.ts';

const API_BASE =
  (import.meta as unknown as { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL ||
  '/api/v1';

const DEMO_CREDENTIALS = {
  email: 'demo@dayform.local',
  password: 'DemoPassword123',
} as const;

let authToken: string | null = null;
let refreshToken: string | null = null;
let pendingAuthPromise: Promise<string> | null = null;

function hasStorageAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && Boolean(window.localStorage);
  } catch {
    return false;
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
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokenToRefresh }),
    });
    if (!response.ok) {
      return null;
    }
    const data = await response.json();
    if (typeof data?.access_token === 'string' && data.access_token.trim()) {
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
    response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(DEMO_CREDENTIALS),
    });
  } catch (netErr) {
    console.error('Network failure during authentication:', netErr);
    throw new Error('Unable to connect to API backend.');
  }

  if (!response.ok) {
    // Try registering demo user first if login failed
    let regRes: Response;
    try {
      regRes = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(DEMO_CREDENTIALS),
      });
    } catch (netErr) {
      console.error('Network failure during demo registration:', netErr);
      throw new Error('Unable to connect to API backend.');
    }

    if (regRes.ok || regRes.status === 409 || regRes.status === 422) {
      let retryLogin: Response;
      try {
        retryLogin = await fetch(`${API_BASE}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(DEMO_CREDENTIALS),
        });
      } catch (netErr) {
        console.error('Network failure during login retry:', netErr);
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

export async function ensureAuthToken(forceRefresh = false): Promise<string> {
  if (forceRefresh) {
    authToken = null;
    refreshToken = null;
    clearPersistedAuthSession();
  } else {
    syncSessionFromStorage();
    if (authToken && isValidJwtAccessToken(authToken)) {
      return authToken;
    }
  }

  if (pendingAuthPromise) {
    return pendingAuthPromise;
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
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
      Authorization: `Bearer ${bearerToken}`,
    };

    return fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });
  };

  let response = await executeRequest(token);

  // If the persisted token was rejected by the backend (e.g., expired, secret rotated,
  // or demo user recreated after an ephemeral DB reset), clear it and re-authenticate once.
  if (response.status === 401) {
    token = await ensureAuthToken(true);
    response = await executeRequest(token);
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
