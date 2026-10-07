import { apiClient } from './client.ts';
import type {
  CreatePlanFromIntentRequest,
  DecisionCandidateRead,
  ExecutionActionType,
  ExecutionResultRead,
  ItineraryFeasibilityRead,
  OrchestratedPlanRead,
  OrchestrateStopInput,
  PlanActionsRead,
  PlanAdaptationRead,
  PlanHealthCheckRead,
  PlanItemRead,
  PlanRead,
  PlanTransitionRead,
  RecommendationResponse,
  SelectOptionRequest,
} from '../types/planning';

/**
 * Creates a structured plan from a free-text intention.
 * Endpoint: POST /api/v1/planning/requests
 */
export async function createPlanFromIntent(
  request: string,
  origin?: string,
  startTime?: string,
  transportPreference?: string
): Promise<PlanRead> {
  const body: CreatePlanFromIntentRequest = {
    request,
    ...(origin && origin.trim() ? { origin: origin.trim() } : {}),
    ...(startTime && startTime.trim() ? { start_time: startTime.trim() } : {}),
    ...(transportPreference && transportPreference.trim() ? { transport_preference: transportPreference.trim() } : {}),
  };
  return apiClient<PlanRead>('/planning/requests', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Retrieves an existing plan by ID.
 * Endpoint: GET /api/v1/planning/plans/{plan_id}
 */
export async function getPlan(planId: string): Promise<PlanRead> {
  return apiClient<PlanRead>(`/planning/plans/${planId}`);
}

/**
 * Retrieves algorithmic recommendations for a plan based on its context.
 * Endpoint: GET /api/v1/planning/plans/{plan_id}/recommendations
 */
export async function getPlanRecommendations(
  planId: string
): Promise<RecommendationResponse> {
  return apiClient<RecommendationResponse>(
    `/planning/plans/${planId}/recommendations`
  );
}

/**
 * Explicitly adds an option to the plan as a PlanItem.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/items/from-option
 */
export async function addOptionToPlan(
  planId: string,
  candidate: DecisionCandidateRead,
  position?: number,
  startTime?: string,
  endTime?: string
): Promise<PlanItemRead> {
  const body: SelectOptionRequest = {
    option_id: candidate.option_id,
    option_type: candidate.option_type,
    position,
    start_time: startTime || null,
    end_time: endTime || null,
  };

  return apiClient<PlanItemRead>(`/planning/plans/${planId}/items/from-option`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * Modifies an existing plan using a conversational tweak.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/modifications
 */
export async function modifyPlan(
  planId: string,
  request: string
): Promise<PlanRead> {
  return apiClient<PlanRead>(`/planning/plans/${planId}/modifications`, {
    method: 'POST',
    body: JSON.stringify({ request }),
  });
}

/**
 * Proposes a non-destructive plan adaptation without committing it.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/adapt
 */
export async function proposePlanAdaptation(
  planId: string,
  request: string
): Promise<PlanAdaptationRead> {
  return apiClient<PlanAdaptationRead>(`/planning/plans/${planId}/adapt`, {
    method: 'POST',
    body: JSON.stringify({ request }),
  });
}

/**
 * Commits an accepted plan adaptation.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/adapt/apply
 */
export async function applyPlanAdaptation(
  planId: string,
  request: string
): Promise<PlanRead> {
  return apiClient<PlanRead>(`/planning/plans/${planId}/adapt/apply`, {
    method: 'POST',
    body: JSON.stringify({ request }),
  });
}

/**
 * Retrieves all available execution actions for a saved plan.
 * Endpoint: GET /api/v1/planning/plans/{plan_id}/actions
 */
export async function getPlanActions(planId: string): Promise<PlanActionsRead> {
  return apiClient<PlanActionsRead>(`/planning/plans/${planId}/actions`);
}

/**
 * Executes a specific action on a plan item.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/items/{item_id}/actions/execute
 */
export async function executePlanAction(
  planId: string,
  itemId: string,
  actionType: ExecutionActionType,
  targetUrl?: string | null
): Promise<ExecutionResultRead> {
  return apiClient<ExecutionResultRead>(
    `/planning/plans/${planId}/items/${itemId}/actions/execute`,
    {
      method: 'POST',
      body: JSON.stringify({ action_type: actionType, target_url: targetUrl || null }),
    }
  );
}

/**
 * Marks an individual plan item as complete.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/items/{item_id}/complete
 */
export async function completePlanItem(
  planId: string,
  itemId: string
): Promise<PlanItemRead> {
  return apiClient<PlanItemRead>(
    `/planning/plans/${planId}/items/${itemId}/complete`,
    {
      method: 'POST',
    }
  );
}

/**
 * Uncompletes an individual plan item.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/items/{item_id}/uncomplete
 */
export async function uncompletePlanItem(
  planId: string,
  itemId: string
): Promise<PlanItemRead> {
  return apiClient<PlanItemRead>(
    `/planning/plans/${planId}/items/${itemId}/uncomplete`,
    {
      method: 'POST',
    }
  );
}

/**
 * Evaluates live real-world intelligence and plan health.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/health-check
 */
export async function checkPlanHealth(
  planId: string
): Promise<PlanHealthCheckRead> {
  return apiClient<PlanHealthCheckRead>(
    `/planning/plans/${planId}/health-check`,
    {
      method: 'POST',
    }
  );
}

export interface PlanTransitionsResponse {
  plan_id: string;
  transitions: PlanTransitionRead[];
  feasibility: ItineraryFeasibilityRead;
}

/**
 * Retrieves physical transitions and feasibility assessment for an itinerary.
 * Endpoint: GET /api/v1/planning/plans/{plan_id}/transitions
 */
export async function getPlanTransitions(
  planId: string
): Promise<PlanTransitionsResponse> {
  return apiClient<PlanTransitionsResponse>(`/planning/plans/${planId}/transitions`);
}

/**
 * Evaluates physical transitions with user-specified preferences.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/transitions/evaluate
 */
export async function evaluatePlanTransitions(
  planId: string,
  preferredModes?: string[],
  partySize: number = 1
): Promise<PlanTransitionsResponse> {
  return apiClient<PlanTransitionsResponse>(
    `/planning/plans/${planId}/transitions/evaluate`,
    {
      method: 'POST',
      body: JSON.stringify({
        preferred_modes: preferredModes || null,
        party_size: partySize,
      }),
    }
  );
}

/**
 * A stop in a proposed itinerary that has not yet been saved to the plan.
 */
export interface ProposedStopInput {
  name?: string;
  location: string;
  start_time?: string | null;
  end_time?: string | null;
  estimated_cost?: string | number | null;
}

/**
 * Produces a complete, transport-aware plan before the user confirms it.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/orchestrate
 *
 * Transport is evaluated first and folded into the returned schedule, so the
 * caller never has to re-derive times or attach mobility after the fact.
 */
export async function orchestratePlan(
  planId: string,
  stops: OrchestrateStopInput[],
  origin?: string | null,
  preferredModes?: string[],
  partySize?: number | null,
  preferredProvider?: string | null,
  selectedLegOptions?: Record<number, string> | null
): Promise<OrchestratedPlanRead> {
  return apiClient<OrchestratedPlanRead>(
    `/planning/plans/${planId}/orchestrate`,
    {
      method: 'POST',
      body: JSON.stringify({
        stops,
        origin: origin && origin.trim() ? origin.trim() : null,
        preferred_modes: preferredModes && preferredModes.length ? preferredModes : null,
        party_size: partySize ?? null,
        preferred_provider: preferredProvider && preferredProvider.trim() ? preferredProvider.trim() : null,
        selected_leg_options: selectedLegOptions || null,
      }),
    }
  );
}

/**
 * Evaluates mobility across a proposed itinerary before the plan is saved.
 * Endpoint: POST /api/v1/planning/plans/{plan_id}/transitions/proposed
 */
export async function evaluateProposedTransitions(
  planId: string,
  stops: ProposedStopInput[],
  preferredModes?: string[],
  partySize: number = 1
): Promise<PlanTransitionsResponse> {
  return apiClient<PlanTransitionsResponse>(
    `/planning/plans/${planId}/transitions/proposed`,
    {
      method: 'POST',
      body: JSON.stringify({
        stops: stops.map((s) => ({
          name: s.name || '',
          location: s.location,
          start_time: s.start_time || null,
          end_time: s.end_time || null,
          estimated_cost: s.estimated_cost ?? null,
        })),
        preferred_modes: preferredModes || null,
        party_size: partySize,
      }),
    }
  );
}

/**
 * Updates a plan's details or context (e.g. origin, transport mode, title).
 * Endpoint: PATCH /api/v1/planning/plans/{plan_id}
 */
export async function updatePlan(
  planId: string,
  changes: {
    title?: string;
    status?: string;
    intention?: string;
    context?: {
      location?: string;
      start_time?: string;
      end_time?: string;
      group_size?: number;
      transport_mode?: string;
      origin?: string;
    };
  }
): Promise<PlanRead> {
  return apiClient<PlanRead>(`/planning/plans/${planId}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  });
}

/**
 * Deletes an existing plan permanently.
 * Endpoint: DELETE /api/v1/planning/plans/{plan_id}
 */
export async function deletePlan(planId: string): Promise<void> {
  return apiClient<void>(`/planning/plans/${planId}`, {
    method: 'DELETE',
  });
}

/**
 * Lists all saved plans for the authenticated user.
 * Endpoint: GET /api/v1/planning/plans
 */
export async function listPlans(): Promise<PlanRead[]> {
  return apiClient<PlanRead[]>('/planning/plans');
}

