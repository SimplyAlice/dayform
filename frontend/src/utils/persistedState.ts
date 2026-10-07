/**
 * Versioned, schema-validated browser storage management for Dayform.
 *
 * Ensures that stale, expired, malformed, or schema-incompatible values in
 * Local Storage never crash startup or strand the user with failing API calls.
 * Never calls `localStorage.clear()` — only removes specific Dayform keys when
 * they fail validation or expire.
 */

import type { ConstraintRead, DecisionCandidateRead, PlanItemRead, PlanRead } from '../types/planning';
import type { ProposedItinerary, ProposedItineraryItem } from './itineraryBuilder';

export const AUTH_STORAGE_KEY = 'dayform_auth_session_v1';
export const LEGACY_AUTH_KEYS = [
  'dayform_access_token',
  'opsos_access_token',
  'careeros_access_token',
] as const;
export const AUTH_SCHEMA_VERSION = 1;

export const WORKSPACE_STORAGE_KEY = 'dayform_workspace_state_v1';
export const LEGACY_WORKSPACE_KEYS = ['dayform_workspace_state', 'dayform_active_plan'] as const;
export const WORKSPACE_SCHEMA_VERSION = 1;

/** Maximum age for persisted active workspace draft state (7 days). */
export const MAX_WORKSPACE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/** Minimum remaining lifetime required before a JWT access token is considered expired (60s). */
export const JWT_EXPIRY_BUFFER_SECONDS = 60;

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface PersistedAuthSessionV1 {
  version: typeof AUTH_SCHEMA_VERSION;
  accessToken: string;
  refreshToken: string | null;
  updatedAt: number;
}

export interface PersistedWorkspaceStateV1 {
  version: typeof WORKSPACE_SCHEMA_VERSION;
  savedAt: number;
  submittedIntent: string;
  isConfirmed: boolean;
  currentPlan: PlanRead;
  candidates: DecisionCandidateRead[];
  proposedItinerary: ProposedItinerary | null;
}

function getDefaultStorage(): StorageLike | null {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Access to window.localStorage can throw SecurityError in strict privacy modes
  }
  return null;
}

export function safeGetItem(key: string, storage: StorageLike | null = getDefaultStorage()): string | null {
  if (!storage) return null;
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

export function safeSetItem(key: string, value: string, storage: StorageLike | null = getDefaultStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function safeRemoveItem(key: string, storage: StorageLike | null = getDefaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    // Ignore storage removal errors in restricted environments
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value !== 'undefined' && value !== 'null';
}

function decodeBase64Url(segment: string): string | null {
  try {
    const normalized = segment.replace(/-/g, '+').replace(/_/g, '/');
    const padLength = (4 - (normalized.length % 4)) % 4;
    const padded = normalized + '='.repeat(padLength);
    if (typeof atob === 'function') {
      return atob(padded);
    }
    if (typeof Buffer !== 'undefined') {
      return Buffer.from(padded, 'base64').toString('utf-8');
    }
    return null;
  } catch {
    return null;
  }
}

export interface JwtPayloadClaims {
  sub?: unknown;
  exp?: unknown;
  iat?: unknown;
}

export function parseJwtPayload(token: unknown): JwtPayloadClaims | null {
  if (!isNonEmptyString(token)) return null;
  const parts = token.trim().split('.');
  if (parts.length !== 3) return null;
  if (!parts[0] || !parts[1] || !parts[2]) return null;

  const decoded = decodeBase64Url(parts[1]);
  if (!decoded) return null;

  try {
    const parsed: unknown = JSON.parse(decoded);
    if (!isPlainObject(parsed)) return null;
    return parsed as JwtPayloadClaims;
  } catch {
    return null;
  }
}

export function extractJwtSubject(token: unknown): string | null {
  const payload = parseJwtPayload(token);
  if (!payload || !isNonEmptyString(payload.sub)) {
    return null;
  }
  return payload.sub.trim();
}

/**
 * Validates that a token is a well-formed, non-expired JWT with a valid subject claim.
 */
export function isValidJwtAccessToken(
  token: unknown,
  nowMs: number = Date.now(),
  bufferSeconds: number = JWT_EXPIRY_BUFFER_SECONDS
): token is string {
  const payload = parseJwtPayload(token);
  if (!payload) return false;

  if (!isNonEmptyString(payload.sub)) {
    return false;
  }

  if (typeof payload.exp !== 'number' || !Number.isFinite(payload.exp)) {
    return false;
  }

  const expiresAtMs = payload.exp * 1000;
  return expiresAtMs > nowMs + bufferSeconds * 1000;
}

/**
 * Loads and validates the persisted auth session.
 *
 * - Migrates a valid legacy `dayform_access_token` into the versioned v1 schema.
 * - Discards expired, corrupted, or schema-incompatible tokens immediately so
 *   startup never uses a dead bearer token.
 */
export function loadPersistedAuthSession(
  storage: StorageLike | null = getDefaultStorage(),
  nowMs: number = Date.now()
): PersistedAuthSessionV1 | null {
  if (!storage) return null;

  // Always clean up obsolete milestone keys if present
  safeRemoveItem('opsos_access_token', storage);
  safeRemoveItem('careeros_access_token', storage);

  const rawSession = safeGetItem(AUTH_STORAGE_KEY, storage);
  if (rawSession !== null) {
    // Also clean up legacy key if both exist
    safeRemoveItem('dayform_access_token', storage);

    try {
      const parsed: unknown = JSON.parse(rawSession);
      if (!isPlainObject(parsed) || parsed.version !== AUTH_SCHEMA_VERSION) {
        safeRemoveItem(AUTH_STORAGE_KEY, storage);
        return null;
      }

      const accessToken = isNonEmptyString(parsed.accessToken) ? parsed.accessToken.trim() : '';
      const refreshToken = isNonEmptyString(parsed.refreshToken) ? parsed.refreshToken.trim() : null;
      const updatedAt = typeof parsed.updatedAt === 'number' && Number.isFinite(parsed.updatedAt)
        ? parsed.updatedAt
        : nowMs;

      if (isValidJwtAccessToken(accessToken, nowMs)) {
        return {
          version: AUTH_SCHEMA_VERSION,
          accessToken,
          refreshToken,
          updatedAt,
        };
      }

      // If the access token is expired/invalid but a valid refresh token exists,
      // preserve the refresh token so the client can attempt a token refresh first.
      if (refreshToken) {
        return {
          version: AUTH_SCHEMA_VERSION,
          accessToken: '',
          refreshToken,
          updatedAt,
        };
      }

      safeRemoveItem(AUTH_STORAGE_KEY, storage);
      return null;
    } catch {
      safeRemoveItem(AUTH_STORAGE_KEY, storage);
      return null;
    }
  }

  // Check legacy raw token key (`dayform_access_token`)
  const legacyToken = safeGetItem('dayform_access_token', storage);
  if (legacyToken !== null) {
    safeRemoveItem('dayform_access_token', storage);

    if (isValidJwtAccessToken(legacyToken, nowMs)) {
      const migrated: PersistedAuthSessionV1 = {
        version: AUTH_SCHEMA_VERSION,
        accessToken: legacyToken.trim(),
        refreshToken: null,
        updatedAt: nowMs,
      };
      savePersistedAuthSession(migrated.accessToken, null, storage, nowMs);
      return migrated;
    }
  }

  return null;
}

export function savePersistedAuthSession(
  accessToken: string,
  refreshToken: string | null = null,
  storage: StorageLike | null = getDefaultStorage(),
  nowMs: number = Date.now()
): boolean {
  if (!storage) return false;
  if (!isNonEmptyString(accessToken)) {
    clearPersistedAuthSession(storage);
    return false;
  }

  for (const legacyKey of LEGACY_AUTH_KEYS) {
    safeRemoveItem(legacyKey, storage);
  }

  const envelope: PersistedAuthSessionV1 = {
    version: AUTH_SCHEMA_VERSION,
    accessToken: accessToken.trim(),
    refreshToken: isNonEmptyString(refreshToken) ? refreshToken.trim() : null,
    updatedAt: nowMs,
  };

  return safeSetItem(AUTH_STORAGE_KEY, JSON.stringify(envelope), storage);
}

export function clearPersistedAuthSession(storage: StorageLike | null = getDefaultStorage()): void {
  if (!storage) return;
  safeRemoveItem(AUTH_STORAGE_KEY, storage);
  for (const legacyKey of LEGACY_AUTH_KEYS) {
    safeRemoveItem(legacyKey, storage);
  }
}

/* -------------------------------------------------------------------------- */
/* Workspace State Validation & Persistence                                   */
/* -------------------------------------------------------------------------- */

function isValidPlanItem(value: unknown): value is PlanItemRead {
  if (!isPlainObject(value)) return false;
  return (
    isNonEmptyString(value.id) &&
    isNonEmptyString(value.name) &&
    isNonEmptyString(value.item_type) &&
    typeof value.position === 'number' &&
    Number.isFinite(value.position)
  );
}

function isValidPlanConstraint(value: unknown): value is ConstraintRead {
  if (!isPlainObject(value)) return false;
  return isNonEmptyString(value.id) && isNonEmptyString(value.type) && typeof value.value === 'string';
}

export function validatePlanRead(value: unknown): PlanRead | null {
  if (!isPlainObject(value)) return null;
  if (!isNonEmptyString(value.id) || !isNonEmptyString(value.intention) || !isNonEmptyString(value.status)) {
    return null;
  }

  if (value.items !== undefined && !Array.isArray(value.items)) {
    return null;
  }
  const rawItems = Array.isArray(value.items) ? value.items : [];
  const validItems: PlanItemRead[] = [];
  for (const item of rawItems) {
    if (!isValidPlanItem(item)) return null;
    validItems.push(item);
  }

  if (value.constraints !== undefined && !Array.isArray(value.constraints)) {
    return null;
  }
  const rawConstraints = Array.isArray(value.constraints) ? value.constraints : [];
  const validConstraints: ConstraintRead[] = [];
  for (const constraint of rawConstraints) {
    if (!isValidPlanConstraint(constraint)) return null;
    validConstraints.push(constraint);
  }

  return {
    ...(value as unknown as PlanRead),
    id: value.id,
    intention: value.intention,
    status: value.status as PlanRead['status'],
    items: validItems,
    constraints: validConstraints,
  };
}

export function validateDecisionCandidate(value: unknown): DecisionCandidateRead | null {
  if (!isPlainObject(value)) return null;
  if (
    !isNonEmptyString(value.option_id) ||
    !isNonEmptyString(value.name) ||
    !isNonEmptyString(value.category) ||
    typeof value.is_eligible !== 'boolean' ||
    typeof value.score !== 'number' ||
    !Number.isFinite(value.score) ||
    !Array.isArray(value.reasons)
  ) {
    return null;
  }
  return value as unknown as DecisionCandidateRead;
}

function isValidProposedItineraryItem(value: unknown): value is ProposedItineraryItem {
  if (!isPlainObject(value)) return false;
  if (!validateDecisionCandidate(value.candidate)) return false;
  if (typeof value.icon !== 'string' || typeof value.subtitle !== 'string') return false;
  if (typeof value.costNumber !== 'number' || !Number.isFinite(value.costNumber)) return false;
  if (!Array.isArray(value.rationale)) return false;
  return true;
}

export function validateProposedItinerary(value: unknown): ProposedItinerary | null {
  if (!isPlainObject(value)) return null;
  if (!Array.isArray(value.items) || !Array.isArray(value.alternatives)) {
    return null;
  }
  if (typeof value.estimatedTotal !== 'number' || !Number.isFinite(value.estimatedTotal)) {
    return null;
  }
  if (typeof value.isOverBudget !== 'boolean') {
    return null;
  }
  if (value.remainingBudget !== null && (typeof value.remainingBudget !== 'number' || !Number.isFinite(value.remainingBudget))) {
    return null;
  }

  for (const item of value.items) {
    if (!isValidProposedItineraryItem(item)) return null;
  }
  for (const alt of value.alternatives) {
    if (!validateDecisionCandidate(alt)) return null;
  }

  return value as unknown as ProposedItinerary;
}

export function loadPersistedWorkspaceState(
  storage: StorageLike | null = getDefaultStorage(),
  nowMs: number = Date.now()
): PersistedWorkspaceStateV1 | null {
  if (!storage) return null;

  for (const legacyKey of LEGACY_WORKSPACE_KEYS) {
    safeRemoveItem(legacyKey, storage);
  }

  const raw = safeGetItem(WORKSPACE_STORAGE_KEY, storage);
  if (raw === null) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isPlainObject(parsed)) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    if (parsed.version !== WORKSPACE_SCHEMA_VERSION) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    if (typeof parsed.savedAt !== 'number' || !Number.isFinite(parsed.savedAt)) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    if (nowMs - parsed.savedAt > MAX_WORKSPACE_AGE_MS) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    if (!isNonEmptyString(parsed.submittedIntent) || typeof parsed.isConfirmed !== 'boolean') {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    const currentPlan = validatePlanRead(parsed.currentPlan);
    if (!currentPlan) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    if (!Array.isArray(parsed.candidates)) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    const candidates: DecisionCandidateRead[] = [];
    for (const c of parsed.candidates) {
      const validCand = validateDecisionCandidate(c);
      if (!validCand) {
        safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
        return null;
      }
      candidates.push(validCand);
    }

    let proposedItinerary: ProposedItinerary | null = null;
    if (parsed.proposedItinerary !== null && parsed.proposedItinerary !== undefined) {
      proposedItinerary = validateProposedItinerary(parsed.proposedItinerary);
      if (!proposedItinerary) {
        safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
        return null;
      }
    }

    // An unconfirmed workspace requires a valid proposedItinerary to render
    if (!parsed.isConfirmed && !proposedItinerary) {
      safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
      return null;
    }

    return {
      version: WORKSPACE_SCHEMA_VERSION,
      savedAt: parsed.savedAt,
      submittedIntent: parsed.submittedIntent,
      isConfirmed: parsed.isConfirmed,
      currentPlan,
      candidates,
      proposedItinerary,
    };
  } catch {
    safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
    return null;
  }
}

export function savePersistedWorkspaceState(
  state: Omit<PersistedWorkspaceStateV1, 'version' | 'savedAt'>,
  storage: StorageLike | null = getDefaultStorage(),
  nowMs: number = Date.now()
): boolean {
  if (!storage) return false;

  const validPlan = validatePlanRead(state.currentPlan);
  if (!validPlan || !isNonEmptyString(state.submittedIntent)) {
    clearPersistedWorkspaceState(storage);
    return false;
  }

  const envelope: PersistedWorkspaceStateV1 = {
    version: WORKSPACE_SCHEMA_VERSION,
    savedAt: nowMs,
    submittedIntent: state.submittedIntent,
    isConfirmed: Boolean(state.isConfirmed),
    currentPlan: validPlan,
    candidates: Array.isArray(state.candidates) ? state.candidates : [],
    proposedItinerary: state.proposedItinerary,
  };

  return safeSetItem(WORKSPACE_STORAGE_KEY, JSON.stringify(envelope), storage);
}

export function clearPersistedWorkspaceState(storage: StorageLike | null = getDefaultStorage()): void {
  if (!storage) return;
  safeRemoveItem(WORKSPACE_STORAGE_KEY, storage);
  for (const legacyKey of LEGACY_WORKSPACE_KEYS) {
    safeRemoveItem(legacyKey, storage);
  }
}
