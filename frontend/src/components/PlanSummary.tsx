import React, { useEffect, useState } from 'react';
import type {
  ExecutionActionRead,
  PlanActionsRead,
  PlanHealthCheckRead,
  PlanRead,
  PlanTransitionRead,
} from '../types/planning';
import {
  checkPlanHealth,
  completePlanItem,
  executePlanAction,
  getPlanActions,
  getPlanTransitions,
  uncompletePlanItem,
} from '../api/planning';
import { TransitionBadge } from './TransitionBadge';
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
  IconPlus,
} from './Icons';

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

  const remaining = plan.budget?.remaining_budget;
  const isOverBudget = plan.budget?.is_over_budget;
  const groupSize = plan.context?.group_size || 1;
  const groupLabel = groupSize > 1 ? `${groupSize} people` : '1 person';

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

  useEffect(() => {
    fetchActions();
    fetchHealth();
    fetchTransitions();
  }, [plan.id, plan.updated_at, plan.items.length]);

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

  return (
    <div className="saved-plan-container">
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
              <span>SAVED PLAN</span>
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

        <h1 className="saved-plan-title">{plan.title || 'Your Confirmed Itinerary'}</h1>
        <p className="saved-plan-intention">“{plan.intention}”</p>

        <div className="saved-meta-row">
          {plan.context?.location && (
            <div className="saved-meta-item">
              <IconMapPin size={14} />
              <span>{plan.context.location}</span>
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

      {/* Refined Budget Bar */}
      {plan.budget && (
        <div className="saved-budget-bar">
          <div className="saved-budget-stat">
            <span className="saved-stat-label">Budget ceiling</span>
            <span className="saved-stat-val">
              {formatCurrency(plan.budget.budget_maximum)}
            </span>
          </div>
          <div className="saved-budget-stat">
            <span className="saved-stat-label">Planned total</span>
            <span className="saved-stat-val primary">
              {formatCurrency(plan.budget.total_planned_cost)}
            </span>
          </div>
          <div className="saved-budget-stat">
            <span className="saved-stat-label">Remaining</span>
            <span className={`saved-stat-val ${isOverBudget ? 'alert' : 'positive'}`}>
              {formatCurrency(remaining)}
            </span>
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
            {plan.items.map((item, idx) => {
              const isLast = idx === plan.items.length - 1;
              const itemActionsData = planActions?.items.find((i) => i.item_id === item.id);
              const isItemCompleted = itemActionsData?.item_status === 'completed';
              const actions = itemActionsData?.actions || [];

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

                      {item.location && (
                        <div className="saved-stop-address">
                          <IconMapPin size={13} />
                          <span>{item.location}</span>
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

                            return (
                              <button
                                key={act.id}
                                type="button"
                                className={`contextual-action-btn ${
                                  act.action_type === 'mark_complete'
                                    ? isItemCompleted
                                      ? 'undo'
                                      : 'complete'
                                    : ''
                                }`}
                                disabled={isBusy}
                                onClick={() => handleActionClick(item.id, act)}
                                title={act.description || act.label}
                              >
                                {actionIcon}
                                <span>{isBusy ? 'Opening...' : act.label}</span>
                              </button>
                            );
                          })}
                        </div>
                      )}

                      {/* Mobility Transition to Next Stop */}
                      {!isLast && transitions[idx] && (
                        <TransitionBadge transition={transitions[idx]} />
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
    </div>
  );
};
