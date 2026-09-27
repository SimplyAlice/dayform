export type PlanStatus = 'draft' | 'ready' | 'archived';

export type PlanItemType =
  | 'transport'
  | 'activity'
  | 'food'
  | 'accommodation'
  | 'shopping'
  | 'service'
  | 'other';

export type ConstraintType =
  | 'budget_max'
  | 'budget_min'
  | 'time_max'
  | 'time_min'
  | 'distance_max'
  | 'group_size'
  | 'preference'
  | 'requirement';

export type CandidateType = 'place' | 'activity';

export type InformationCategory =
  | 'food'
  | 'culture'
  | 'nature'
  | 'entertainment'
  | 'wellness'
  | 'shopping';

export type ReasonType =
  | 'location'
  | 'budget'
  | 'group_size'
  | 'category'
  | 'duration'
  | 'time_window'
  | 'opening_hours'
  | 'schedule_conflict'
  | 'preference'
  | 'occasion'
  | 'semantic_match'
  | 'exclusion'
  | 'setting'
  | 'mobility'
  | 'general';

export type ReasonOutcome = 'supported' | 'neutral' | 'violated';

export interface DecisionReasonRead {
  type: ReasonType;
  outcome: ReasonOutcome;
  message: string;
}

export interface DecisionCandidateRead {
  option_id: string;
  option_type: CandidateType;
  name: string;
  is_eligible: boolean;
  score: number;
  reasons: DecisionReasonRead[];
  category: InformationCategory;
  cost: string | number | null;
  duration_minutes: number | null;
  location: string | null;
  source: string;
  address?: string | null;
  opening_hours?: string | null;
  freshness?: 'live' | 'recently_verified' | 'cached' | 'fixture' | string | null;
  verified_at?: string | null;
  attribution?: string | null;
}

export interface RecommendationResponse {
  data_source: string;
  is_live: boolean;
  attribution?: string | null;
  freshness?: 'live' | 'recently_verified' | 'cached' | 'fixture' | string | null;
  candidates: DecisionCandidateRead[];
  trade_off_summary?: string | null;
}

export interface ContextRead {
  location: string | null;
  start_time: string | null;
  end_time: string | null;
  group_size: number;
  transport_mode: string | null;
}

export interface ConstraintRead {
  id: string;
  type: ConstraintType;
  value: string;
  numeric_value: string | number | null;
}

export interface PlanItemRead {
  id: string;
  name: string;
  item_type: PlanItemType;
  description: string | null;
  start_time: string | null;
  end_time: string | null;
  duration_minutes: number | null;
  estimated_cost: string | number | null;
  location: string | null;
  position: number;
  status?: string;
}

export interface BudgetRead {
  budget_maximum: string | number | null;
  total_planned_cost: string | number;
  remaining_budget: string | number | null;
  is_over_budget: boolean;
}

export interface UnderstandingRead {
  goal: string;
  occasion: string | null;
  people_count: number | null;
  relationship_context: string | null;
  date_spec: string | null;
  time_window: string | null;
  start_time?: string | null;
  end_time?: string | null;
  time_confidence?: 'approximate' | 'exact' | 'inferred' | string;
  duration_limit_minutes?: number | null;
  location: string | null;
  location_is_inferred: boolean;
  transport_mode?: string | null;
  budget_amount: string | number | null;
  budget_kind: 'hard_max' | 'approximate' | 'preference' | 'none';
  preferences: string[];
  exclusions: string[];
  activity_types: string[];
  semantic_descriptors?: string[];
  setting_preference?: string | null;
  weather_context?: string | null;
  ambiguities: string[];
  provenance: Record<string, string>;
}

export interface PlanTransitionOptionRead {
  provider_id: string;
  provider_name: string;
  mode: string;
  duration_minutes: number | null;
  cost: string | number | null;
  cost_known: boolean;
  currency: string;
  transfers: number;
  confidence: number;
  live_status: string;
  booking_capability: string;
  booking_url?: string | null;
  summary: string;
}

export interface PlanTransitionRead {
  id: string;
  from_item_id?: string | null;
  to_item_id?: string | null;
  from_location: string;
  to_location: string;
  departure_time?: string | null;
  arrival_time?: string | null;
  duration_minutes?: number | null;
  mode: string;
  provider_id: string;
  provider_name: string;
  cost?: string | number | null;
  cost_known: boolean;
  currency: string;
  transfers: number;
  confidence: number;
  live_status: string;
  booking_capability: string;
  booking_url?: string | null;
  summary: string;
  is_feasible: boolean;
  feasibility_issue?: string | null;
  available_options?: PlanTransitionOptionRead[];
}

export interface ItineraryFeasibilityRead {
  is_feasible: boolean;
  deadline_respected: boolean;
  budget_respected: boolean;
  transitions_feasible: boolean;
  issues: string[];
  warnings: string[];
  total_transition_duration_minutes: number;
  total_known_transition_cost: string | number;
  has_unknown_transition_costs: boolean;
}

export interface PlanRead {
  id: string;
  intention: string;
  title: string | null;
  status: PlanStatus;
  created_at: string;
  updated_at: string;
  context: ContextRead | null;
  constraints: ConstraintRead[];
  items: PlanItemRead[];
  budget: BudgetRead;
  understanding?: UnderstandingRead | null;
  transitions?: PlanTransitionRead[];
  feasibility?: ItineraryFeasibilityRead | null;
}

export interface CreatePlanFromIntentRequest {
  request: string;
}

export interface PlanModifyRequest {
  request: string;
}

export interface SelectOptionRequest {
  option_id: string;
  option_type: CandidateType;
  position?: number | null;
  start_time?: string | null;
  end_time?: string | null;
}

export type ItemAction = 'kept' | 'replaced' | 'removed' | 'rescheduled' | 'added';

export interface ItemDiffRead {
  action: ItemAction;
  original_item_id?: string | null;
  original_name?: string | null;
  new_name?: string | null;
  original_start_time?: string | null;
  new_start_time?: string | null;
  original_end_time?: string | null;
  new_end_time?: string | null;
  original_cost?: number | string | null;
  new_cost?: number | string | null;
  location?: string | null;
  item_type?: string | null;
  reason: string;
  candidate_option_id?: string | null;
  candidate_option_type?: string | null;
}

export interface PlanAdaptationRead {
  plan_id: string;
  changes_detected: string[];
  narrative_summary: string;
  diffs: ItemDiffRead[];
  adapted_items: PlanItemRead[];
  new_start_time?: string | null;
  new_end_time?: string | null;
  new_total_cost: number | string;
  budget_delta?: number | string | null;
  is_feasible: boolean;
  feasibility_note?: string | null;
}

export interface ApplyAdaptationRequest {
  request: string;
}

export type ExecutionActionType =
  | 'open_website'
  | 'directions'
  | 'call'
  | 'reserve'
  | 'add_to_calendar'
  | 'mark_complete';

export type ExecutionActionStatus =
  | 'available'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'unavailable';

export interface ExecutionActionRead {
  id: string;
  item_id: string;
  action_type: ExecutionActionType;
  label: string;
  target_url?: string | null;
  is_available: boolean;
  status: ExecutionActionStatus;
  description?: string | null;
}

export interface PlanItemActionsRead {
  item_id: string;
  item_name: string;
  item_status: string;
  actions: ExecutionActionRead[];
}

export interface PlanActionsRead {
  plan_id: string;
  plan_status: string;
  items: PlanItemActionsRead[];
}

export interface ExecutionResultRead {
  action_type: string;
  status: string;
  message: string;
  target_url?: string | null;
  item_status: string;
  plan_status: string;
}

export type PlanHealthStatus = 'healthy' | 'warning' | 'action_required';

export interface LiveSignalRead {
  source: string;
  signal_type: string;
  observed_at: string;
  freshness: string;
  target_name: string;
  target_item_id?: string | null;
  change_type: string;
  is_meaningful_change: boolean;
  message: string;
}

export interface PlanHealthCheckRead {
  plan_id: string;
  health_status: PlanHealthStatus;
  headline: string;
  narrative: string;
  signals: LiveSignalRead[];
  checked_at: string;
  recommended_adaptation_prompt?: string | null;
  proposed_adaptation?: PlanAdaptationRead | null;
}
