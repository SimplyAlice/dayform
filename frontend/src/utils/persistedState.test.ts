import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  AUTH_SCHEMA_VERSION,
  AUTH_STORAGE_KEY,
  MAX_WORKSPACE_AGE_MS,
  WORKSPACE_SCHEMA_VERSION,
  WORKSPACE_STORAGE_KEY,
  clearPersistedAuthSession,
  clearPersistedWorkspaceState,
  isValidJwtAccessToken,
  loadPersistedAuthSession,
  loadPersistedWorkspaceState,
  parseJwtPayload,
  savePersistedAuthSession,
  savePersistedWorkspaceState,
  type StorageLike,
} from './persistedState.ts';
import type { DecisionCandidateRead, PlanRead } from '../types/planning.ts';
import type { ProposedItinerary } from './itineraryBuilder.ts';
import {
  apiClient,
  ensureAuthToken,
  toUserFriendlyErrorMessage,
  type ApiError,
} from '../api/client.ts';
import { createPlanFromIntent, getPlanRecommendations } from '../api/planning.ts';

class MemoryStorage implements StorageLike {
  private store = new Map<string, string>();
  public clearCalled = false;

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) ?? null) : null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  clear(): void {
    this.clearCalled = true;
    this.store.clear();
  }

  has(key: string): boolean {
    return this.store.has(key);
  }
}

function createMockJwt(claims: Record<string, unknown>): string {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
  const signature = Buffer.from('mock-signature').toString('base64url');
  return `${header}.${payload}.${signature}`;
}

function createSamplePlan(): PlanRead {
  return {
    id: 'plan-123',
    title: 'Sea Point Morning',
    intention: 'Coffee and a coastal walk in Sea Point under R300',
    status: 'draft',
    created_at: '2026-10-08T08:00:00Z',
    updated_at: '2026-10-08T08:00:00Z',
    context: {
      location: 'Sea Point',
      start_time: '2026-10-08T09:00:00Z',
      end_time: '2026-10-08T12:00:00Z',
      group_size: 2,
      transport_mode: 'walking',
    },
    items: [
      {
        id: 'item-1',
        item_type: 'food',
        name: 'Bootlegger Coffee Company',
        description: 'Artisanal coffee roastery',
        location: 'Sea Point',
        start_time: '2026-10-08T09:00:00Z',
        end_time: '2026-10-08T10:00:00Z',
        estimated_cost: '120',
        duration_minutes: 60,
        position: 0,
      },
    ],
    constraints: [
      {
        id: 'c-1',
        type: 'budget_max',
        value: 'R300',
        numeric_value: 300,
      },
    ],
    budget: {
      budget_maximum: 300,
      total_planned_cost: 120,
      remaining_budget: 180,
      is_over_budget: false,
    },
  };
}

function createSampleCandidate(): DecisionCandidateRead {
  return {
    option_id: 'opt-1',
    option_type: 'place',
    name: 'Bootlegger Coffee Company',
    category: 'food',
    is_eligible: true,
    score: 92,
    reasons: [
      {
        type: 'category',
        outcome: 'supported',
        message: 'Matches morning coffee request',
      },
    ],
    cost: '120',
    duration_minutes: 60,
    location: 'Sea Point',
    source: 'fixture',
  };
}

function createSampleProposedItinerary(): ProposedItinerary {
  const candidate = createSampleCandidate();
  return {
    items: [
      {
        candidate,
        icon: 'food',
        subtitle: 'Sea Point',
        costNumber: 120,
        rationale: ['Great morning stop'],
      },
    ],
    alternatives: [],
    estimatedTotal: 120,
    remainingBudget: 180,
    isOverBudget: false,
    narrativeSubheading: 'A relaxed morning in Sea Point.',
  };
}

describe('Persisted Auth Session Lifecycle & Validation', () => {
  const fixedNowMs = 1_760_000_000_000;
  const fixedNowSec = Math.floor(fixedNowMs / 1000);

  it('returns null when Local Storage is empty', () => {
    const storage = new MemoryStorage();
    const session = loadPersistedAuthSession(storage, fixedNowMs);
    assert.equal(session, null);
    assert.equal(storage.clearCalled, false);
  });

  it('validates and decodes well-formed, non-expired JWT access tokens', () => {
    const validToken = createMockJwt({ sub: 'user-123', exp: fixedNowSec + 900 });
    assert.equal(isValidJwtAccessToken(validToken, fixedNowMs), true);

    const payload = parseJwtPayload(validToken);
    assert.equal(payload?.sub, 'user-123');
  });

  it('rejects expired JWT access tokens or tokens expiring within the safety buffer', () => {
    const expiredToken = createMockJwt({ sub: 'user-123', exp: fixedNowSec - 10 });
    const nearlyExpiredToken = createMockJwt({ sub: 'user-123', exp: fixedNowSec + 30 });

    assert.equal(isValidJwtAccessToken(expiredToken, fixedNowMs), false);
    assert.equal(isValidJwtAccessToken(nearlyExpiredToken, fixedNowMs), false);
  });

  it('rejects malformed JWT strings, missing claims, and literal "undefined"/"null"', () => {
    assert.equal(isValidJwtAccessToken('', fixedNowMs), false);
    assert.equal(isValidJwtAccessToken('undefined', fixedNowMs), false);
    assert.equal(isValidJwtAccessToken('null', fixedNowMs), false);
    assert.equal(isValidJwtAccessToken('not-a-jwt', fixedNowMs), false);
    assert.equal(isValidJwtAccessToken('a.b', fixedNowMs), false);

    const missingSub = createMockJwt({ exp: fixedNowSec + 900 });
    const missingExp = createMockJwt({ sub: 'user-123' });
    assert.equal(isValidJwtAccessToken(missingSub, fixedNowMs), false);
    assert.equal(isValidJwtAccessToken(missingExp, fixedNowMs), false);
  });

  it('saves and restores a valid versioned auth session across page refreshes', () => {
    const storage = new MemoryStorage();
    storage.setItem('unrelated_app_key', 'keep-me');

    const validToken = createMockJwt({ sub: 'user-123', exp: fixedNowSec + 900 });
    const saved = savePersistedAuthSession(validToken, 'refresh-token-xyz', storage, fixedNowMs);
    assert.equal(saved, true);

    const restored = loadPersistedAuthSession(storage, fixedNowMs + 60_000);
    assert.notEqual(restored, null);
    assert.equal(restored?.version, AUTH_SCHEMA_VERSION);
    assert.equal(restored?.accessToken, validToken);
    assert.equal(restored?.refreshToken, 'refresh-token-xyz');
    assert.equal(storage.getItem('unrelated_app_key'), 'keep-me');
    assert.equal(storage.clearCalled, false);
  });

  it('migrates a valid legacy dayform_access_token to versioned storage and removes legacy keys', () => {
    const storage = new MemoryStorage();
    const validToken = createMockJwt({ sub: 'user-legacy', exp: fixedNowSec + 900 });
    storage.setItem('dayform_access_token', validToken);
    storage.setItem('opsos_access_token', 'old-opsos-token');

    const migrated = loadPersistedAuthSession(storage, fixedNowMs);
    assert.notEqual(migrated, null);
    assert.equal(migrated?.accessToken, validToken);
    assert.equal(storage.has('dayform_access_token'), false);
    assert.equal(storage.has('opsos_access_token'), false);
    assert.equal(storage.has(AUTH_STORAGE_KEY), true);
  });

  it('discards and deletes an expired or corrupted legacy dayform_access_token on startup', () => {
    const storage = new MemoryStorage();
    const expiredToken = createMockJwt({ sub: 'user-legacy', exp: fixedNowSec - 3600 });
    storage.setItem('dayform_access_token', expiredToken);

    const result = loadPersistedAuthSession(storage, fixedNowMs);
    assert.equal(result, null);
    assert.equal(storage.has('dayform_access_token'), false);
    assert.equal(storage.has(AUTH_STORAGE_KEY), false);
  });

  it('preserves refreshToken when accessToken is expired so client can attempt refresh', () => {
    const storage = new MemoryStorage();
    const expiredToken = createMockJwt({ sub: 'user-123', exp: fixedNowSec - 120 });
    savePersistedAuthSession(expiredToken, 'valid-refresh-token', storage, fixedNowMs - 900_000);

    const loaded = loadPersistedAuthSession(storage, fixedNowMs);
    assert.notEqual(loaded, null);
    assert.equal(loaded?.accessToken, '');
    assert.equal(loaded?.refreshToken, 'valid-refresh-token');
  });

  it('handles corrupted JSON and incompatible schema versions in auth storage without throwing', () => {
    const storage = new MemoryStorage();
    storage.setItem(AUTH_STORAGE_KEY, '{corrupted-json');
    assert.equal(loadPersistedAuthSession(storage, fixedNowMs), null);
    assert.equal(storage.has(AUTH_STORAGE_KEY), false);

    storage.setItem(
      AUTH_STORAGE_KEY,
      JSON.stringify({ version: 999, accessToken: 'abc', refreshToken: null })
    );
    assert.equal(loadPersistedAuthSession(storage, fixedNowMs), null);
    assert.equal(storage.has(AUTH_STORAGE_KEY), false);
  });
});

describe('Persisted Workspace State Lifecycle & Validation', () => {
  const fixedNowMs = 1_760_000_000_000;

  it('returns null when no workspace state is stored', () => {
    const storage = new MemoryStorage();
    assert.equal(loadPersistedWorkspaceState(storage, fixedNowMs), null);
  });

  it('saves and restores a valid unconfirmed workspace state across refresh', () => {
    const storage = new MemoryStorage();
    const plan = createSamplePlan();
    const candidate = createSampleCandidate();
    const itinerary = createSampleProposedItinerary();

    const saved = savePersistedWorkspaceState(
      {
        submittedIntent: plan.intention,
        isConfirmed: false,
        currentPlan: plan,
        candidates: [candidate],
        proposedItinerary: itinerary,
      },
      storage,
      fixedNowMs
    );
    assert.equal(saved, true);

    const loaded = loadPersistedWorkspaceState(storage, fixedNowMs + 5000);
    assert.notEqual(loaded, null);
    assert.equal(loaded?.version, WORKSPACE_SCHEMA_VERSION);
    assert.equal(loaded?.submittedIntent, plan.intention);
    assert.equal(loaded?.isConfirmed, false);
    assert.equal(loaded?.currentPlan.id, 'plan-123');
    assert.equal(loaded?.candidates.length, 1);
    assert.equal(loaded?.proposedItinerary?.items.length, 1);
  });

  it('rejects malformed JSON in workspace storage and removes only the broken key', () => {
    const storage = new MemoryStorage();
    storage.setItem('user_theme', 'editorial-light');
    storage.setItem(WORKSPACE_STORAGE_KEY, '{"version":1,"currentPlan":');

    const loaded = loadPersistedWorkspaceState(storage, fixedNowMs);
    assert.equal(loaded, null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
    assert.equal(storage.getItem('user_theme'), 'editorial-light');
    assert.equal(storage.clearCalled, false);
  });

  it('rejects workspace state with missing required fields or wrong data types', () => {
    const storage = new MemoryStorage();

    // Missing currentPlan.id and wrong items type
    storage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        version: WORKSPACE_SCHEMA_VERSION,
        savedAt: fixedNowMs,
        submittedIntent: 'Test day',
        isConfirmed: true,
        currentPlan: { intention: 'Test day', status: 'ready', items: 'not-an-array' },
        candidates: [],
        proposedItinerary: null,
      })
    );
    assert.equal(loadPersistedWorkspaceState(storage, fixedNowMs), null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);

    // Unconfirmed workspace missing proposedItinerary (would render a blank /workspace screen)
    storage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        version: WORKSPACE_SCHEMA_VERSION,
        savedAt: fixedNowMs,
        submittedIntent: 'Test day',
        isConfirmed: false,
        currentPlan: createSamplePlan(),
        candidates: [],
        proposedItinerary: null,
      })
    );
    assert.equal(loadPersistedWorkspaceState(storage, fixedNowMs), null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
  });

  it('rejects old/incompatible schema versions and expired workspace state', () => {
    const storage = new MemoryStorage();
    const plan = createSamplePlan();

    // Incompatible version
    storage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        version: 0,
        savedAt: fixedNowMs,
        submittedIntent: plan.intention,
        isConfirmed: true,
        currentPlan: plan,
        candidates: [],
        proposedItinerary: null,
      })
    );
    assert.equal(loadPersistedWorkspaceState(storage, fixedNowMs), null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);

    // Stale workspace state beyond MAX_WORKSPACE_AGE_MS
    savePersistedWorkspaceState(
      {
        submittedIntent: plan.intention,
        isConfirmed: true,
        currentPlan: plan,
        candidates: [],
        proposedItinerary: null,
      },
      storage,
      fixedNowMs
    );
    const expiredLoad = loadPersistedWorkspaceState(
      storage,
      fixedNowMs + MAX_WORKSPACE_AGE_MS + 1000
    );
    assert.equal(expiredLoad, null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
  });

  it('clears only Dayform keys without calling localStorage.clear()', () => {
    const storage = new MemoryStorage();
    storage.setItem('external_key', 'preserve-me');
    storage.setItem(AUTH_STORAGE_KEY, 'val');
    storage.setItem(WORKSPACE_STORAGE_KEY, 'val');

    clearPersistedAuthSession(storage);
    clearPersistedWorkspaceState(storage);

    assert.equal(storage.has(AUTH_STORAGE_KEY), false);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
    assert.equal(storage.getItem('external_key'), 'preserve-me');
    assert.equal(storage.clearCalled, false);
  });
});

describe('API Client Auth Recovery (ensureAuthToken & apiClient)', () => {
  it('automatically discards an expired legacy token in localStorage and re-authenticates', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const expiredJwt = createMockJwt({ sub: 'stale-user', exp: nowSec - 600 });
    const freshJwt = createMockJwt({ sub: 'fresh-user', exp: nowSec + 900 });

    storage.setItem('dayform_access_token', expiredJwt);
    storage.setItem('keep_other_key', 'untouched');

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      const calls: string[] = [];
      globalThis.fetch = (async (input: string | URL | Request) => {
        const url = String(input);
        calls.push(url);
        if (url.endsWith('/auth/login')) {
          return new Response(
            JSON.stringify({ access_token: freshJwt, refresh_token: 'fresh-refresh' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(JSON.stringify({ detail: 'Unexpected URL' }), { status: 500 });
      }) as typeof fetch;

      const token = await ensureAuthToken(false);
      assert.equal(token, freshJwt);
      assert.equal(calls.length, 1);
      assert.equal(storage.has('dayform_access_token'), false);
      assert.equal(storage.has(AUTH_STORAGE_KEY), true);
      assert.equal(storage.getItem('keep_other_key'), 'untouched');
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('intercepts 401 Unauthorized on apiClient, clears the rejected token, re-authenticates, and retries once', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const rejectedJwt = createMockJwt({ sub: 'deleted-db-user', exp: nowSec + 600 });
    const recoveredJwt = createMockJwt({ sub: 'recreated-user', exp: nowSec + 900 });

    savePersistedAuthSession(rejectedJwt, null, storage, Date.now());

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      const seenAuthHeaders: Array<string | null> = [];
      let plansAttempt = 0;

      globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/planning/plans')) {
          plansAttempt += 1;
          const headers = (init?.headers ?? {}) as Record<string, string>;
          seenAuthHeaders.push(headers.Authorization ?? null);
          if (plansAttempt === 1) {
            return new Response(JSON.stringify({ detail: 'Could not validate credentials' }), {
              status: 401,
              headers: { 'Content-Type': 'application/json' },
            });
          }
          return new Response(JSON.stringify([{ id: 'plan-1', intention: 'Day out', status: 'ready' }]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.endsWith('/auth/login')) {
          return new Response(
            JSON.stringify({ access_token: recoveredJwt, refresh_token: 'new-refresh' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 });
      }) as typeof fetch;

      const result = await apiClient<Array<{ id: string }>>('/planning/plans');
      assert.equal(Array.isArray(result), true);
      assert.equal(result[0]?.id, 'plan-1');
      assert.equal(plansAttempt, 2);
      assert.deepEqual(seenAuthHeaders, [
        `Bearer ${rejectedJwt}`,
        `Bearer ${recoveredJwt}`,
      ]);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('registers a fresh demo user when initial login returns 401 and persists the session', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const freshJwt = createMockJwt({ sub: 'brand-new-user', exp: nowSec + 900 });

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      const sequence: string[] = [];
      let loginCalls = 0;

      globalThis.fetch = (async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith('/auth/login')) {
          loginCalls += 1;
          sequence.push(`login-${loginCalls}`);
          if (loginCalls === 1) {
            return new Response(JSON.stringify({ detail: 'Invalid email or password.' }), {
              status: 401,
              headers: { 'Content-Type': 'application/json' },
            });
          }
          return new Response(
            JSON.stringify({ access_token: freshJwt, refresh_token: 'fresh-refresh-1' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        if (url.endsWith('/auth/register')) {
          sequence.push('register');
          return new Response(
            JSON.stringify({ id: 'brand-new-user', email: 'demo@dayform.local' }),
            { status: 201, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(null, { status: 404 });
      }) as typeof fetch;

      const token = await ensureAuthToken(false);
      assert.equal(token, freshJwt);
      assert.deepEqual(sequence, ['login-1', 'register', 'login-2']);
      assert.equal(storage.has(AUTH_STORAGE_KEY), true);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('uses refresh token when access token is expired (refresh success) and falls back to login on refresh failure', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const expiredJwt = createMockJwt({ sub: 'user-refresh', exp: nowSec - 300 });
    const refreshedJwt = createMockJwt({ sub: 'user-refresh', exp: nowSec + 900 });
    const fallbackLoginJwt = createMockJwt({ sub: 'user-fallback', exp: nowSec + 900 });

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      // Part 1: Refresh succeeds
      savePersistedAuthSession(expiredJwt, 'valid-refresh-tok', storage, Date.now() - 600_000);
      globalThis.fetch = (async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith('/auth/refresh')) {
          return new Response(
            JSON.stringify({ access_token: refreshedJwt, refresh_token: 'rotated-refresh-tok' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(null, { status: 500 });
      }) as typeof fetch;

      const tokenFromRefresh = await ensureAuthToken(false);
      assert.equal(tokenFromRefresh, refreshedJwt);

      // Part 2: Refresh fails (401) -> falls back to /auth/login
      savePersistedAuthSession(expiredJwt, 'revoked-refresh-tok', storage, Date.now() - 600_000);
      const calls: string[] = [];
      globalThis.fetch = (async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith('/auth/refresh')) {
          calls.push('refresh');
          return new Response(
            JSON.stringify({ detail: 'Refresh token is invalid, expired, or has already been used.' }),
            { status: 401, headers: { 'Content-Type': 'application/json' } }
          );
        }
        if (url.endsWith('/auth/login')) {
          calls.push('login');
          return new Response(
            JSON.stringify({ access_token: fallbackLoginJwt, refresh_token: 'new-refresh-tok' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(null, { status: 500 });
      }) as typeof fetch;

      const tokenFromFallback = await ensureAuthToken(false);
      assert.equal(tokenFromFallback, fallbackLoginJwt);
      assert.deepEqual(calls, ['refresh', 'login']);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('clears persisted auth session and throws user-friendly error without infinite loop when 401 persists after retry', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const initialJwt = createMockJwt({ sub: 'user-1', exp: nowSec + 600 });
    const retryJwt = createMockJwt({ sub: 'user-1', exp: nowSec + 900 });

    savePersistedAuthSession(initialJwt, null, storage, Date.now());

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      let planningCalls = 0;
      let loginCalls = 0;
      globalThis.fetch = (async (input: string | URL | Request) => {
        const url = String(input);
        if (url.endsWith('/auth/login')) {
          loginCalls += 1;
          return new Response(
            JSON.stringify({ access_token: retryJwt, refresh_token: 'ref' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }
        planningCalls += 1;
        return new Response(
          JSON.stringify({ detail: 'Access token is invalid or expired.' }),
          { status: 401, headers: { 'Content-Type': 'application/json' } }
        );
      }) as typeof fetch;

      let caughtError: ApiError | null = null;
      try {
        await apiClient('/planning/plans');
      } catch (err) {
        caughtError = err as ApiError;
      }

      assert.notEqual(caughtError, null);
      assert.equal(
        caughtError?.message,
        "Your session needed refreshing. We've taken care of it — please try again."
      );
      assert.equal(caughtError?.rawDetail, 'Access token is invalid or expired.');
      assert.equal(caughtError?.status, 401);
      assert.equal(planningCalls, 2);
      assert.equal(loginCalls, 1);
      assert.equal(storage.has(AUTH_STORAGE_KEY), false);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('deduplicates multiple simultaneous API requests during auth recovery and clears stale user workspace', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const oldUserJwt = createMockJwt({ sub: 'old-deleted-user', exp: nowSec + 600 });
    const newUserJwt = createMockJwt({ sub: 'new-recreated-user', exp: nowSec + 900 });

    savePersistedAuthSession(oldUserJwt, null, storage, Date.now());
    savePersistedWorkspaceState(
      {
        submittedIntent: 'Old plan from deleted user',
        isConfirmed: true,
        currentPlan: createSamplePlan(),
        candidates: [],
        proposedItinerary: null,
      },
      storage,
      Date.now()
    );

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      let loginCount = 0;
      globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/auth/login')) {
          loginCount += 1;
          await new Promise((r) => setTimeout(r, 15));
          return new Response(
            JSON.stringify({ access_token: newUserJwt, refresh_token: 'new-ref' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        const headers = (init?.headers ?? {}) as Record<string, string>;
        if (headers.Authorization === `Bearer ${oldUserJwt}`) {
          return new Response(
            JSON.stringify({ detail: 'Token does not correspond to an existing user.' }),
            { status: 401, headers: { 'Content-Type': 'application/json' } }
          );
        }

        return new Response(JSON.stringify({ ok: true, url }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }) as typeof fetch;

      const [res1, res2, res3] = await Promise.all([
        apiClient<{ ok: boolean }>('/planning/plans/1'),
        apiClient<{ ok: boolean }>('/planning/plans/2'),
        apiClient<{ ok: boolean }>('/planning/plans/3'),
      ]);

      assert.equal(res1.ok, true);
      assert.equal(res2.ok, true);
      assert.equal(res3.ok, true);
      assert.equal(loginCount, 1);
      // Workspace state belonging to the old deleted user ID was automatically cleaned up
      assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('completes full plan creation (createPlanFromIntent + getPlanRecommendations) after recovering from stale dayform_access_token and cannot be bypassed by custom Authorization headers', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const staleLegacyToken = createMockJwt({ sub: 'stale-user', exp: nowSec - 3600 });
    const validToken = createMockJwt({ sub: 'active-user', exp: nowSec + 900 });

    storage.setItem('dayform_access_token', staleLegacyToken);

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      const samplePlan = createSamplePlan();
      const sampleCand = createSampleCandidate();
      const seenAuthOnPlanning: string[] = [];

      globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        const headers = (init?.headers ?? {}) as Record<string, string>;

        if (url.endsWith('/auth/login')) {
          return new Response(
            JSON.stringify({ access_token: validToken, refresh_token: 'active-refresh' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        if (url.endsWith('/planning/requests')) {
          seenAuthOnPlanning.push(headers.Authorization);
          return new Response(JSON.stringify(samplePlan), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.endsWith(`/planning/plans/${samplePlan.id}/recommendations`)) {
          seenAuthOnPlanning.push(headers.Authorization);
          return new Response(
            JSON.stringify({
              data_source: 'live',
              is_live: true,
              candidates: [sampleCand],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        if (url.endsWith('/planning/custom-header-test')) {
          seenAuthOnPlanning.push(headers.Authorization);
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        return new Response(null, { status: 404 });
      }) as typeof fetch;

      const createdPlan = await createPlanFromIntent('Coffee in Sea Point');
      const recs = await getPlanRecommendations(createdPlan.id);

      // Verify custom stale Authorization header cannot bypass apiClient's authoritative token
      await apiClient('/planning/custom-header-test', {
        headers: { Authorization: `Bearer ${staleLegacyToken}` },
      });

      assert.equal(createdPlan.id, samplePlan.id);
      assert.equal(recs.candidates.length, 1);
      assert.deepEqual(seenAuthOnPlanning, [
        `Bearer ${validToken}`,
        `Bearer ${validToken}`,
        `Bearer ${validToken}`,
      ]);
      assert.equal(storage.has('dayform_access_token'), false);
      assert.equal(storage.has(AUTH_STORAGE_KEY), true);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('recovers when createPlanFromIntent succeeds and getPlanRecommendations returns 401 on first attempt', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const initialToken = createMockJwt({ sub: 'user-step1', exp: nowSec + 600 });
    const refreshedToken = createMockJwt({ sub: 'user-step1', exp: nowSec + 1200 });

    savePersistedAuthSession(initialToken, null, storage, Date.now());

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      const samplePlan = createSamplePlan();
      const sampleCand = createSampleCandidate();
      let recsAttempts = 0;

      globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        const headers = (init?.headers ?? {}) as Record<string, string>;

        if (url.endsWith('/planning/requests')) {
          return new Response(JSON.stringify(samplePlan), {
            status: 201,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.endsWith(`/planning/plans/${samplePlan.id}/recommendations`)) {
          recsAttempts += 1;
          if (recsAttempts === 1) {
            return new Response(
              JSON.stringify({ detail: 'Access token is invalid or expired.' }),
              { status: 401, headers: { 'Content-Type': 'application/json' } }
            );
          }
          assert.equal(headers.Authorization, `Bearer ${refreshedToken}`);
          return new Response(
            JSON.stringify({
              data_source: 'live',
              is_live: true,
              candidates: [sampleCand],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        if (url.endsWith('/auth/login')) {
          return new Response(
            JSON.stringify({ access_token: refreshedToken, refresh_token: 'ref-step2' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } }
          );
        }

        return new Response(null, { status: 404 });
      }) as typeof fetch;

      const plan = await createPlanFromIntent('Morning in Sea Point');
      const recs = await getPlanRecommendations(plan.id);
      assert.equal(plan.id, samplePlan.id);
      assert.equal(recsAttempts, 2);
      assert.equal(recs.candidates.length, 1);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('aborts hung API requests when timeoutMs expires and throws a friendly timeout message', async () => {
    const storage = new MemoryStorage();
    const nowSec = Math.floor(Date.now() / 1000);
    const validToken = createMockJwt({ sub: 'user-timeout', exp: nowSec + 900 });
    savePersistedAuthSession(validToken, null, storage, Date.now());

    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;

    try {
      Object.defineProperty(globalThis, 'window', {
        value: { localStorage: storage },
        configurable: true,
        writable: true,
      });

      globalThis.fetch = ((_input: string | URL | Request, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          const sig = init?.signal;
          if (sig) {
            if (sig.aborted) {
              const err = new Error('The operation was aborted.');
              err.name = 'AbortError';
              reject(err);
              return;
            }
            sig.addEventListener('abort', () => {
              const err = new Error('The operation was aborted.');
              err.name = 'AbortError';
              reject(err);
            });
          }
        });
      }) as typeof fetch;

      let caughtError: ApiError | null = null;
      try {
        await apiClient('/planning/requests', { timeoutMs: 25 });
      } catch (err) {
        caughtError = err as ApiError;
      }

      assert.notEqual(caughtError, null);
      assert.equal(
        caughtError?.message,
        'Dayform is taking a little longer than usual. Please try again.'
      );
      assert.equal(caughtError?.status, 408);
    } finally {
      Object.defineProperty(globalThis, 'window', {
        value: originalWindow,
        configurable: true,
        writable: true,
      });
      globalThis.fetch = originalFetch;
    }
  });

  it('discards workspace state on load when stored userId does not match the active authenticated user', () => {
    const storage = new MemoryStorage();
    const nowMs = Date.now();
    const nowSec = Math.floor(nowMs / 1000);

    const oldUserToken = createMockJwt({ sub: 'user-old-111', exp: nowSec + 900 });
    const newUserToken = createMockJwt({ sub: 'user-new-222', exp: nowSec + 900 });

    savePersistedAuthSession(oldUserToken, null, storage, nowMs);
    savePersistedWorkspaceState(
      {
        submittedIntent: 'Old user workspace',
        isConfirmed: true,
        currentPlan: createSamplePlan(),
        candidates: [],
        proposedItinerary: null,
      },
      storage,
      nowMs
    );

    // Same user loads workspace -> succeeds
    const loadedForOldUser = loadPersistedWorkspaceState(storage, nowMs);
    assert.notEqual(loadedForOldUser, null);
    assert.equal(loadedForOldUser?.userId, 'user-old-111');

    // Auth session switches to a different user -> workspace state is discarded and deleted
    savePersistedAuthSession(newUserToken, null, storage, nowMs);
    const loadedForNewUser = loadPersistedWorkspaceState(storage, nowMs);
    assert.equal(loadedForNewUser, null);
    assert.equal(storage.has(WORKSPACE_STORAGE_KEY), false);
    assert.equal(storage.clearCalled, false);
  });

  it('removes expired dayform_auth_session_v1 when no refresh token is present and removes legacy careeros/opsos keys', () => {
    const storage = new MemoryStorage();
    const nowMs = Date.now();
    const nowSec = Math.floor(nowMs / 1000);
    const expiredJwt = createMockJwt({ sub: 'user-expired', exp: nowSec - 500 });

    storage.setItem('opsos_access_token', 'legacy-opsos');
    storage.setItem('careeros_access_token', 'legacy-careeros');
    storage.setItem('custom_user_preference', 'dark');
    savePersistedAuthSession(expiredJwt, null, storage, nowMs - 600_000);

    const loaded = loadPersistedAuthSession(storage, nowMs);
    assert.equal(loaded, null);
    assert.equal(storage.has(AUTH_STORAGE_KEY), false);
    assert.equal(storage.has('opsos_access_token'), false);
    assert.equal(storage.has('careeros_access_token'), false);
    assert.equal(storage.getItem('custom_user_preference'), 'dark');
    assert.equal(storage.clearCalled, false);
  });

  it('translates raw technical error strings into clean user-friendly messages', () => {
    assert.equal(
      toUserFriendlyErrorMessage('Access token is invalid or expired.', 401),
      "Your session needed refreshing. We've taken care of it — please try again."
    );
    assert.equal(
      toUserFriendlyErrorMessage('Token does not correspond to an existing user.', 401),
      "Your session needed refreshing. We've taken care of it — please try again."
    );
    assert.equal(
      toUserFriendlyErrorMessage('Failed to fetch'),
      'Dayform is taking a little longer than usual. Please try again.'
    );
    assert.equal(
      toUserFriendlyErrorMessage('AbortError: The operation was aborted'),
      'Dayform is taking a little longer than usual. Please try again.'
    );
    assert.equal(
      toUserFriendlyErrorMessage('Request failed (500)', 500),
      "We couldn't finish building this plan. Your request is still safe — try again."
    );
  });
});
