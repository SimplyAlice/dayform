import React, { useEffect, useState } from 'react';
import type {
  ExecutionActionRead,
  PlanActionsRead,
  PlanHealthCheckRead,
  PlanRead,
  PlanTransitionRead,
  OrchestratedPlanRead,
} from '../types/planning';
import {
  checkPlanHealth,
  completePlanItem,
  executePlanAction,
  getPlanActions,
  getPlanTransitions,
  uncompletePlanItem,
  orchestratePlan,
} from '../api/planning';
import { TransitionBadge } from './TransitionBadge';
import { TransportLeg } from './TransportLeg';
import { formatExactCurrency, summarizeItineraryCosts } from '../utils/itineraryBuilder';
import { planSummaryLine, planTitle } from '../utils/planVoice';
import { StageFrame } from './StageFrame';
import {
  CategoryIcon,
  IconClock,
  IconMapPin,
  IconRefresh,
  IconCheck,
  IconNavigation,
  IconExternalLink,
  IconPhone,
  IconCalendar,
  IconUndo,
  IconAlertCircle,
  IconX,
  IconArrowRight,
  IconArrowUpRight,
  IconPlus,
} from './Icons';

function describeOrigin(origin: string): string {
  const looksLikeCoords = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/.test(origin.trim());
  return looksLikeCoords ? 'your current location' : origin;
}

interface PlanSummaryProps {
  plan: PlanRead;
  onStartNew?: () => void;
  onTweakPlan?: (tweakText: string) => Promise<void>;
  isTweaking?: boolean;
}

export const PlanSummary: React.FC<PlanSummaryProps> = ({
  plan,
  onStartNew,
  onTweakPlan,
  isTweaking = false,
}) => {
  const [tweakInput, setTweakInput] = useState('');
  const [planActions, setPlanActions] = useState<PlanActionsRead | null>(null);
  const [healthCheck, setHealthCheck] = useState<PlanHealthCheckRead | null>(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);
  const [transitions, setTransitions] = useState<PlanTransitionRead[]>(plan.transitions || []);
  const [executingActionId, setExecutingActionId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    message: string;
    type: 'info' | 'success' | 'error';
  } | null>(null);

  const formatCurrency = (val: string | number | null | undefined) => {
    if (val === null || val === undefined) return '—';
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? String(val) : `R${num.toFixed(0)}`;
  };

  const groupSize = plan.context?.group_size || 1;
  const groupLabel = groupSize > 1 ? `${groupSize} people` : '1 person';
  const origin = plan.understanding?.origin || plan.context?.origin || null;

  // Load execution actions whenever plan changes
  const fetchActions = async () => {
    try {
      const actionsData = await getPlanActions(plan.id);
      setPlanActions(actionsData);
    } catch (err) {
      console.error('Failed to load plan execution actions:', err);
    }
  };

  // Evaluate live intelligence health check
  const fetchHealth = async () => {
    setIsCheckingHealth(true);
    try {
      const health = await checkPlanHealth(plan.id);
      setHealthCheck(health);
    } catch (err) {
      console.error('Failed to check live plan health:', err);
    } finally {
      setIsCheckingHealth(false);
    }
  };

  const [orchestrated, setOrchestrated] = useState<OrchestratedPlanRead | null>(null);
  const savedBudgetMax = plan.budget?.budget_maximum == null
    ? null
    : Number(plan.budget.budget_maximum);
  const savedCostSummary = summarizeItineraryCosts(
    plan.items.map((item) => item.estimated_cost),
    orchestrated?.feasibility.total_known_transition_cost ?? null,
    orchestrated?.feasibility.has_unknown_transition_costs ?? plan.items.length > 0,
    savedBudgetMax
  );
  const remaining = savedCostSummary.remainingBudget;
  const isOverBudget = savedCostSummary.isOverBudget;

  // Fetch transitions if not already attached
  const fetchTransitions = async () => {
    if (plan.transitions && plan.transitions.length > 0) {
      setTransitions(plan.transitions);
      return;
    }
    try {
      const data = await getPlanTransitions(plan.id);
      setTransitions(data.transitions || []);
    } catch (err) {
      console.error('Failed to load plan transitions:', err);
    }
  };

  // Orchestrate saved itinerary to resolve transport corridors, timetables, and opening hours
  const fetchOrchestrated = async () => {
    if (!plan.items || plan.items.length === 0) return;
    try {
      const stops = plan.items.map((item) => ({
        name: item.name,
        location: item.location || item.name,
        option_id: item.id,
        start_time: item.start_time || undefined,
        end_time: item.end_time || undefined,
        estimated_cost: item.estimated_cost != null ? Number(item.estimated_cost) : undefined,
        category: item.item_type,
        duration_minutes: item.duration_minutes ?? undefined,
        description: item.description ?? undefined,
      }));
      const res = await orchestratePlan(
        plan.id,
        stops,
        origin,
        undefined,
        groupSize
      );
      setOrchestrated(res);
      if (res.legs && res.legs.length > 0) {
        setTransitions(res.legs.map((l) => l.transition));
      }
    } catch (err) {
      console.warn('Could not orchestrate saved plan transport:', err);
    }
  };

  useEffect(() => {
    fetchActions();
    fetchHealth();
    fetchTransitions();
    fetchOrchestrated();
  }, [plan.id, plan.updated_at, plan.items.length]);

  const legOffset = orchestrated?.origin_resolved ? 1 : 0;
  const originLeg = orchestrated?.origin_resolved ? orchestrated.legs?.[0] : null;

  const handleActionClick = async (itemId: string, action: ExecutionActionRead) => {
    setExecutingActionId(action.id);
    try {
      if (action.action_type === 'mark_complete') {
        const itemActions = planActions?.items.find((i) => i.item_id === itemId);
        const isCurrentlyCompleted = itemActions?.item_status === 'completed';

        if (isCurrentlyCompleted) {
          await uncompletePlanItem(plan.id, itemId);
          setFeedback({
            message: 'Marked stop as planned.',
            type: 'info',
          });
        } else {
          await completePlanItem(plan.id, itemId);
          setFeedback({
            message: 'Marked stop as completed.',
            type: 'success',
          });
        }
        await fetchActions();
        return;
      }

      // External Navigation Actions: Website, Directions, Reserve, Calendar
      if (action.target_url) {
        if (action.action_type === 'call') {
          window.location.assign(action.target_url);
        } else {
          window.open(action.target_url, '_blank', 'noopener,noreferrer');
        }
      }

      // Call execution endpoint to log action and obtain honest narrative message
      const result = await executePlanAction(
        plan.id,
        itemId,
        action.action_type,
        action.target_url
      );

      const feedbackType =
        result.status === 'failed' || result.status === 'unavailable'
          ? 'error'
          : result.action_type === 'reserve'
          ? 'info'
          : 'success';

      setFeedback({
        message: result.message,
        type: feedbackType,
      });

      await fetchActions();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Action could not be completed.';
      setFeedback({
        message: `Action issue: ${msg}`,
        type: 'error',
      });
    } finally {
      setExecutingActionId(null);
    }
  };

  const planProgression = planActions?.plan_status || 'ready';
  const completedStopsCount =
    planActions?.items.filter((i) => i.item_status === 'completed').length || 0;

  // The same naming the proposal used, so the plan keeps its identity once saved.
  //
  // The stored plan title is a template — "Southern Suburbs Day Out · ~R400" — and
  // it is honest but it says nothing about the day. The name derived from the
  // stops themselves ("A Slow Afternoon in Southern Suburbs") is the one worth
  // leading with, so it wins whenever there is something to derive it from. The
  // stored title is still shown, quietly, because it carries the budget figure
  // the derived name does not.
  const derivedTitle = planTitle(plan.understanding, plan.items);
  const savedTitle = plan.items.length > 0 ? derivedTitle : plan.title || derivedTitle;
  const savedSummary = planSummaryLine(plan.items);
  const storedTitle = plan.title && plan.title !== savedTitle ? plan.title : null;

  return (
    <StageFrame
      stage={6}
      className="saved-plan-container df-light df-light--quiet"
      title={<>Now go live <em>your day.</em></>}
      lede="This is the plan. Everything below is somewhere real, with what you need once you are on your way."
    >
      {/* Toast Feedback Notification */}
      {feedback && (
        <div className={`editorial-toast ${feedback.type}`}>
          <div className="toast-text-wrap">
            <span className="toast-dot" />
            <span>{feedback.message}</span>
          </div>
          <button
            type="button"
            className="toast-close-btn"
            onClick={() => setFeedback(null)}
          >
            <IconX size={14} />
          </button>
        </div>
      )}

      {/* Plan Header */}
      <div className="saved-plan-header">
        <div className="saved-header-top">
          <div className="saved-status-ribbon">
            <span className="saved-badge">
              <IconCheck size={13} />
              <span>Saved plan</span>
            </span>

            {planProgression === 'completed' ? (
              <span className="progression-pill completed">Completed</span>
            ) : planProgression === 'in_progress' ? (
              <span className="progression-pill in-progress">
                In progress · {completedStopsCount} of {plan.items.length} done
              </span>
            ) : (
              <span className="progression-pill ready">Ready</span>
            )}
          </div>

          {/* Live Intelligence Product Feature */}
          <div className="live-intelligence-widget">
            {healthCheck && (
              <div
                className={`live-intelligence-indicator ${
                  healthCheck.health_status === 'healthy' ? 'healthy' : 'warning'
                }`}
              >
                <span className="live-pulse-dot" />
                <span className="live-status-text">
                  {healthCheck.health_status === 'healthy'
                    ? 'Live checks · All good'
                    : 'Live checks · Update detected'}
                </span>
              </div>
            )}

            <button
              type="button"
              className="btn-live-check"
              onClick={fetchHealth}
              disabled={isCheckingHealth}
              title="Refresh real-world status"
            >
              <IconRefresh size={13} className={isCheckingHealth ? 'spin' : ''} />
              <span>{isCheckingHealth ? 'Checking...' : 'Check live'}</span>
            </button>
          </div>
        </div>

        <p className="saved-plan-title">{savedTitle}</p>
        <p className="saved-plan-summary">{savedSummary}</p>
        {storedTitle && <p className="saved-plan-stored-title">{storedTitle}</p>}
        <p className="saved-plan-intention">“{plan.intention}”</p>

        <div className="saved-meta-row">
          {plan.context?.location && (
            <div className="saved-meta-item">
              <IconMapPin size={14} />
              <span>{plan.context.location}</span>
            </div>
          )}
          {origin && (
            <div className="saved-meta-item">
              <IconNavigation size={14} />
              <span>Starts from {origin}</span>
            </div>
          )}
          <div className="saved-meta-item">
            <IconCalendar size={14} />
            <span>{groupLabel}</span>
          </div>
        </div>
      </div>

      {/* Assistant-Grade Live Update Banner */}
      {healthCheck && healthCheck.health_status === 'action_required' && (
        <div className="live-assistant-alert">
          <div className="assistant-alert-content">
            <div className="assistant-alert-icon-box">
              <IconAlertCircle size={18} />
            </div>
            <div className="assistant-alert-text">
              <h4 className="assistant-alert-title">{healthCheck.headline}</h4>
              <p className="assistant-alert-narrative">{healthCheck.narrative}</p>
            </div>
          </div>
          <div className="assistant-alert-actions">
            {onTweakPlan && healthCheck.recommended_adaptation_prompt && (
              <button
                type="button"
                className="btn-assistant-review"
                onClick={() => onTweakPlan(healthCheck.recommended_adaptation_prompt!)}
                disabled={isTweaking}
              >
                <span>{isTweaking ? 'Adapting...' : 'Review proposed adaptation'}</span>
                <IconArrowRight size={14} />
              </button>
            )}
            <button
              type="button"
              className="btn-assistant-dismiss"
              onClick={() => setHealthCheck(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Budget & financial clarity: open, prominent, actionable */}
      {plan.budget && (
        <div className="saved-budget-card">
          <div className="saved-budget-header">
            <span className="saved-budget-kicker">BUDGET & FINANCIAL SUMMARY</span>
            <span className={`saved-budget-status-pill ${isOverBudget ? 'is-over' : savedCostSummary.hasUnknownCosts ? 'is-unverified' : 'is-under'}`}>
              {isOverBudget ? 'Over limit' : savedCostSummary.hasUnknownCosts ? 'Cost unavailable' : 'In budget'}
            </span>
          </div>
          <div className="saved-budget-grid">
            <div className="saved-budget-cell">
              <span className="saved-cell-label">Budget ceiling</span>
              <span className="saved-cell-val">
                {formatCurrency(plan.budget.budget_maximum)}
              </span>
            </div>
            <div className="saved-budget-cell">
              <span className="saved-cell-label">Planned total</span>
              <span className="saved-cell-val is-primary">
                {savedCostSummary.totalLabel}
              </span>
            </div>
            <div className="saved-budget-cell">
              <span className="saved-cell-label">Remaining</span>
              <span className={`saved-cell-val ${isOverBudget ? 'is-alert' : 'is-positive'}`}>
                {remaining !== null ? formatExactCurrency(remaining) : savedBudgetMax !== null ? 'Unavailable' : 'Flexible'}
              </span>
            </div>
            {groupSize > 1 && (
              <div className="saved-budget-cell">
                <span className="saved-cell-label">Per person ({groupLabel})</span>
                <span className="saved-cell-val">
                  {savedCostSummary.hasUnknownCosts
                    ? 'Price unavailable'
                    : formatCurrency(Math.round(savedCostSummary.knownTotal / groupSize))}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Editorial Stops List */}
      <div className="saved-itinerary-section">
        <div className="saved-section-header">
          <h3 className="saved-section-title">
            Itinerary stops
            <span className="stops-count">({plan.items.length})</span>
          </h3>
        </div>

        {plan.items.length === 0 ? (
          <div className="empty-itinerary">
            <p>No items in this plan.</p>
          </div>
        ) : (
          <div className="saved-stops-timeline">
            {/* Origin corridor leg if origin was stated */}
            {origin && originLeg && (
              <div className="saved-origin-leg-wrap">
                <TransportLeg leg={originLeg} legIndex={0} />
              </div>
            )}
            {origin && !originLeg && (
              <div className="saved-origin-start-badge">
                <div className="origin-badge-info">
                  <IconNavigation size={14} />
                  <span>Starting out from <strong>{describeOrigin(origin)}</strong></span>
                </div>
                {plan.items[0] && (
                  <a
                    href={`https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(plan.items[0].location || plan.items[0].name)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="saved-origin-directions-link"
                    title="Get directions from origin to first stop"
                  >
                    <span>Directions to {plan.items[0].name}</span>
                    <IconArrowUpRight size={12} />
                  </a>
                )}
              </div>
            )}

            {plan.items.map((item, idx) => {
              const isLast = idx === plan.items.length - 1;
              const itemActionsData = planActions?.items.find((i) => i.item_id === item.id);
              const isItemCompleted = itemActionsData?.item_status === 'completed';
              const schedStop = orchestrated?.stops?.find((s) => s.name === item.name);
              const actions: ExecutionActionRead[] =
                itemActionsData?.actions && itemActionsData.actions.length > 0
                  ? itemActionsData.actions
                  : (schedStop?.actions || []).map((va, vIdx) => ({
                      id: `act-${item.id}-${vIdx}`,
                      item_id: item.id,
                      action_type: va.action_type,
                      label: va.label,
                      target_url: va.target_url,
                      is_available: true,
                      status: 'available',
                      description: va.description,
                    }));
              const rawHours = itemActionsData?.opening_hours || schedStop?.opening_hours;
              const formattedHours = rawHours
                ? (/^open/i.test(rawHours.trim()) ? rawHours.trim() : `Open ${rawHours.trim()}`)
                : 'Opening hours unavailable';
              const address = itemActionsData?.address || schedStop?.address || item.location;
              const contactHint = itemActionsData?.contact_hint || schedStop?.contact_hint;
              const nextLeg = orchestrated?.legs?.[legOffset + idx];

              // Check for stop-level live signal
              const stopSignal = healthCheck?.signals?.find(
                (s) =>
                  s.target_item_id === item.id ||
                  s.target_name.toLowerCase().includes(item.name.toLowerCase()) ||
                  item.name.toLowerCase().includes(s.target_name.toLowerCase())
              );

              return (
                <div
                  key={item.id || idx}
                  className={`saved-stop-node ${isItemCompleted ? 'completed' : ''} ${isLast ? 'last' : ''}`}
                >
                  {/* Timeline Node Spine */}
                  <div className="saved-spine">
                    <div className="saved-marker">
                      {isItemCompleted ? (
                        <IconCheck size={13} className="completed-check" />
                      ) : (
                        <CategoryIcon category={item.item_type} size={13} />
                      )}
                    </div>
                    {!isLast && <div className="saved-spine-line" />}
                  </div>

                  {/* Stop Content Card */}
                  <div className="saved-stop-card">
                    <div className="saved-stop-main">
                      <div className="saved-stop-meta-line">
                        <span className="saved-stop-category">{item.item_type.toUpperCase()}</span>
                        {item.start_time && (
                          <div className="saved-stop-time">
                            <IconClock size={12} />
                            <span>{new Date(item.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                        )}
                        <span className="saved-stop-cost">
                          {formatCurrency(item.estimated_cost)}
                        </span>
                      </div>

                      <div className="saved-stop-title-row">
                        <h4 className="saved-stop-name">{item.name}</h4>
                        {isItemCompleted && (
                          <span className="completed-tag">Completed</span>
                        )}
                      </div>

                      {address && (
                        <div className="saved-stop-address">
                          <IconMapPin size={13} />
                          <span>{address}</span>
                        </div>
                      )}

                      {formattedHours && (
                        <div className="saved-stop-hours">
                          <IconClock size={12} />
                          <span>{formattedHours}</span>
                        </div>
                      )}

                      {contactHint && (
                        <div className="saved-stop-contact-hint">
                          <span>{contactHint}</span>
                        </div>
                      )}

                      {/* Real-World Stop Signal Notice */}
                      {stopSignal && (
                        <div
                          className={`stop-live-notice ${
                            stopSignal.is_meaningful_change ? 'warning' : 'healthy'
                          }`}
                        >
                          <span className="notice-dot" />
                          <span>{stopSignal.message}</span>
                        </div>
                      )}

                      {/* Secondary Contextual Actions */}
                      {actions.length > 0 && (
                        <div className="saved-stop-actions">
                          {actions.map((act) => {
                            const isBusy = executingActionId === act.id;
                            let actionIcon = <IconExternalLink size={14} />;

                            if (act.action_type === 'directions') {
                              actionIcon = <IconNavigation size={14} />;
                            } else if (act.action_type === 'call') {
                              actionIcon = <IconPhone size={14} />;
                            } else if (act.action_type === 'reserve' || act.action_type === 'add_to_calendar') {
                              actionIcon = <IconCalendar size={14} />;
                            } else if (act.action_type === 'mark_complete') {
                              actionIcon = isItemCompleted ? <IconUndo size={14} /> : <IconCheck size={14} />;
                            }

                            /* One primary action per stop, and the rest are
                               consequences of being there. */
                            const isPrimary = act.action_type === 'directions';

                            return (
                              <button
                                key={act.id}
                                type="button"
                                className={[
                                  'contextual-action-btn',
                                  isPrimary ? 'is-primary' : 'is-secondary',
                                  act.action_type === 'mark_complete'
                                    ? isItemCompleted
                                      ? 'undo'
                                      : 'complete'
                                    : '',
                                ]
                                  .filter(Boolean)
                                  .join(' ')}
                                disabled={isBusy}
                                onClick={() => handleActionClick(item.id, act)}
                                title={act.description || act.label}
                              >
                                {actionIcon}
                                <span>{isBusy ? 'Opening…' : act.label}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* Mobility Transition to Next Stop */}
                      {!isLast && nextLeg && (
                        <div className="saved-leg-transition">
                          <TransportLeg leg={nextLeg} legIndex={legOffset + idx} />
                        </div>
                      )}
                      {!isLast && !nextLeg && transitions[idx] && (
                        <TransitionBadge
                          transition={transitions[idx]}
                          fromLabel={item.location || item.name}
                          toLabel={plan.items[idx + 1]?.location || plan.items[idx + 1]?.name}
                        />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Something Changed? Conversational Adaptation */}
      {onTweakPlan && (
        <div className="saved-adaptation-box">
          <div className="saved-adaptation-header">
            <h4 className="saved-adaptation-title">Something changed?</h4>
            <p className="saved-adaptation-subtitle">
              Tell me what happened and I’ll rework the plan while preserving your context.
            </p>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (tweakInput.trim() && !isTweaking) {
                onTweakPlan(tweakInput.trim());
              }
            }}
            className="saved-adaptation-form"
          >
            <input
              type="text"
              value={tweakInput}
              onChange={(e) => setTweakInput(e.target.value)}
              placeholder="e.g. Kloof Street House is fully booked, or keep it under R600..."
              disabled={isTweaking}
              className="saved-adaptation-input"
            />
            <button
              type="submit"
              disabled={!tweakInput.trim() || isTweaking}
              className="btn-editorial-primary"
            >
              {isTweaking ? 'Adapting...' : 'Adapt plan'}
            </button>
          </form>
        </div>
      )}

      {/* Bottom Footer Actions */}
      {onStartNew && (
        <div className="saved-footer-actions">
          <button
            type="button"
            className="btn-editorial-secondary"
            onClick={onStartNew}
          >
            <IconPlus size={15} />
            <span>Plan something else</span>
          </button>
        </div>
      )}
    </StageFrame>
  );
};
