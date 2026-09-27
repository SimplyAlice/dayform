import React, { useState, useEffect, useRef } from 'react';
import type { DecisionCandidateRead, PlanRead, PlanTransitionRead } from '../types/planning';
import type { ProposedItineraryItem, ProposedItinerary } from '../utils/itineraryBuilder';
import {
  formatCurrency,
  parseCandidateCost,
  recalculateItinerary,
  humanizeCandidateReasons,
  getTradeOffNote,
  findTransitionBetween,
  resolveStopLocation,
  travelMinutesForItems,
} from '../utils/itineraryBuilder';
import { evaluateProposedTransitions } from '../api/planning';
import {
  IconArrowRight,
  IconClock,
  IconMapPin,
  IconSwap,
  IconTrash,
  IconPlus,
  IconSparkles,
  IconAlertCircle,
  IconX,
} from './Icons';
import { TransitionBadge } from './TransitionBadge';

/** Combine a proposed stop's HH:MM slot with the plan's calendar date into an ISO instant. */
function toIsoTimestamp(baseDate: Date, hhmm?: string): string | null {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(':').map((v) => parseInt(v, 10));
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  const d = new Date(baseDate);
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

interface ProposedPlanProps {
  plan: PlanRead;
  initialItinerary: ProposedItinerary;
  allCandidates: DecisionCandidateRead[];
  budgetMax: number | null;
  onConfirm: (selectedCandidates: DecisionCandidateRead[]) => Promise<void>;
  isSaving: boolean;
  onModifyIntent: () => void;
  onTweakPlan?: (tweakText: string) => Promise<void>;
  isTweaking?: boolean;
  isAdaptationReview?: boolean;
  adaptationSummary?: string;
  onAcceptAdaptation?: () => Promise<void>;
  onRejectAdaptation?: () => void;
}

export const ProposedPlan: React.FC<ProposedPlanProps> = ({
  plan,
  initialItinerary,
  allCandidates,
  budgetMax,
  onConfirm,
  isSaving,
  onModifyIntent,
  onTweakPlan,
  isTweaking = false,
  isAdaptationReview = false,
  adaptationSummary,
  onAcceptAdaptation,
  onRejectAdaptation,
}) => {
  const [itinerary, setItinerary] = useState<ProposedItinerary>(initialItinerary);
  const [swappingIndex, setSwappingIndex] = useState<number | null>(null);
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [customTweak, setCustomTweak] = useState('');
  const [transitions, setTransitions] = useState<PlanTransitionRead[]>([]);
  // Travel minutes already folded into the current schedule, so re-applying the
  // same transitions is a no-op and the schedule/transition cycle settles.
  const appliedTravelRef = useRef<string>('');

  useEffect(() => {
    setItinerary(initialItinerary);
    appliedTravelRef.current = '';
  }, [initialItinerary]);

  const groupSize = plan.context?.group_size || 1;

  // Mobility between proposed stops. A proposal is not persisted yet, so transitions
  // are requested for the visible stop sequence rather than read from the plan.
  const stopSignature = itinerary.items
    .map((it) => `${resolveStopLocation(it) || ''}|${it.startTime || ''}|${it.endTime || ''}`)
    .join('~');

  useEffect(() => {
    const baseDate = plan.context?.start_time ? new Date(plan.context.start_time) : new Date();

    const stops = itinerary.items
      .map((it) => {
        const location = resolveStopLocation(it);
        if (!location) return null;
        return {
          name: it.candidate.name,
          location,
          start_time: toIsoTimestamp(baseDate, it.startTime),
          end_time: toIsoTimestamp(baseDate, it.endTime),
          estimated_cost: it.costNumber,
        };
      })
      .filter((s): s is NonNullable<typeof s> => s !== null);

    if (stops.length < 2) {
      setTransitions([]);
      return;
    }

    let cancelled = false;
    evaluateProposedTransitions(plan.id, stops, undefined, groupSize)
      .then((res) => {
        if (cancelled) return;
        const next = res.transitions || [];
        setTransitions(next);

        // Reserve the real travel time before the schedule is judged feasible.
        // Durations come from the M15 transitions themselves; legs with an unknown
        // duration contribute nothing, and M15 still reports those windows honestly.
        setItinerary((prev) => {
          const travel = travelMinutesForItems(prev.items, next);
          const signature = travel.join(',');
          if (signature === appliedTravelRef.current) return prev;
          appliedTravelRef.current = signature;
          return recalculateItinerary(
            prev.items,
            allCandidates,
            budgetMax,
            plan.understanding,
            prev.tradeOffSummary ?? null,
            travel
          );
        });
      })
      .catch((err) => {
        // Mobility is additive context: a lookup failure must not break the proposal.
        console.error('Failed to load proposed transitions:', err);
        if (!cancelled) setTransitions([]);
      });

    return () => {
      cancelled = true;
    };
  }, [plan.id, stopSignature, groupSize, plan.context?.start_time]);

  // Swap an item in slot index with an alternative candidate
  const handleSwap = (slotIndex: number, newCandidate: DecisionCandidateRead) => {
    const updatedItems = [...itinerary.items];
    updatedItems[slotIndex] = {
      candidate: newCandidate,
      icon: newCandidate.category,
      subtitle: newCandidate.address || newCandidate.location || '',
      costNumber: parseCandidateCost(newCandidate.cost),
      rationale: humanizeCandidateReasons(newCandidate, budgetMax, groupSize, plan.understanding),
    };

    const recalculated = recalculateItinerary(updatedItems, allCandidates, budgetMax, plan.understanding, itinerary.tradeOffSummary, travelMinutesForItems(updatedItems, transitions));
    setItinerary(recalculated);
    setSwappingIndex(null);
  };

  // Remove an item from the proposed itinerary
  const handleRemove = (slotIndex: number) => {
    const updatedItems = itinerary.items.filter((_, idx) => idx !== slotIndex);
    const recalculated = recalculateItinerary(updatedItems, allCandidates, budgetMax, plan.understanding, itinerary.tradeOffSummary, travelMinutesForItems(updatedItems, transitions));
    setItinerary(recalculated);
    if (swappingIndex === slotIndex) {
      setSwappingIndex(null);
    }
  };

  // Add an alternative candidate to the itinerary
  const handleAdd = (candidate: DecisionCandidateRead) => {
    const newItem: ProposedItineraryItem = {
      candidate,
      icon: candidate.category,
      subtitle: candidate.address || candidate.location || '',
      costNumber: parseCandidateCost(candidate.cost),
      rationale: humanizeCandidateReasons(candidate, budgetMax, groupSize, plan.understanding),
    };
    const updatedItems = [...itinerary.items, newItem];
    const recalculated = recalculateItinerary(updatedItems, allCandidates, budgetMax, plan.understanding, itinerary.tradeOffSummary, travelMinutesForItems(updatedItems, transitions));
    setItinerary(recalculated);
    setShowAddMenu(false);
  };

  const handleConfirmClick = async () => {
    const candidatesToPersist = itinerary.items.map((i) => i.candidate);
    await onConfirm(candidatesToPersist);
  };

  // Financial Rollup Calculations
  const totalCost = itinerary.estimatedTotal;
  const budgetBudgeted = budgetMax !== null && budgetMax > 0;
  const remaining = itinerary.remainingBudget;
  const perPersonCost = groupSize > 1 ? Math.round(totalCost / groupSize) : null;
  const progressPercent = budgetBudgeted ? Math.min(100, Math.round((totalCost / budgetMax) * 100)) : 100;

  return (
    <div className="magazine-itinerary-stage">
      {/* Adaptation Review Callout */}
      {(isAdaptationReview || itinerary.isAdaptationProposal) && (
        <div className="magazine-adaptation-banner">
          <div className="adaptation-banner-tag">
            <IconSparkles size={14} />
            <span>ADAPTATION CALCULATED · MINIMAL DIFF</span>
          </div>
          <p className="adaptation-banner-narrative">
            {adaptationSummary || itinerary.adaptationSummary || 'Adapted itinerary according to your requested change.'}
          </p>
        </div>
      )}

      {/* Transit Feasibility Notice */}
      {plan.feasibility && !plan.feasibility.is_feasible && plan.feasibility.issues.length > 0 && (
        <div className="magazine-adaptation-banner" style={{ borderColor: 'var(--color-coral)', background: 'var(--color-coral-subtle)' }}>
          <div className="adaptation-banner-tag" style={{ color: 'var(--color-coral)' }}>
            <IconAlertCircle size={14} />
            <span>TRANSIT FEASIBILITY NOTICE</span>
          </div>
          <p className="adaptation-banner-narrative" style={{ color: 'var(--color-ink)' }}>
            {plan.feasibility.issues.join(' · ')}
          </p>
        </div>
      )}

      {/* Dramatic Magazine Spread Headline */}
      <div className="magazine-spread-header">
        <div className="spread-masthead-meta">
          <span className="spread-flag">DAYFORM / PROPOSED ITINERARY</span>
          <span className="spread-date">
            {plan.understanding?.date_spec ? plan.understanding.date_spec.toUpperCase() : 'TODAY / UPCOMING'}
            {itinerary.timeSpanDisplay && ` · ${itinerary.timeSpanDisplay.toUpperCase()}`}
          </span>
          <span className="spread-freshness">✓ VERIFIED LOCAL VENUES</span>
        </div>

        <h1 className="spread-main-title">
          YOUR <em>DAY.</em>
        </h1>

        <div className="spread-intention-quote">
          <span className="quote-mark">“</span>
          <span className="quote-text">{plan.intention}</span>
          <span className="quote-mark">”</span>
        </div>

        <p className="spread-sub-narrative">
          {itinerary.narrativeSubheading || 'Here’s what I’d do: a coherent, timed sequence balancing budget, pacing, and atmosphere.'}
        </p>
      </div>

      {/* High-Contrast Editorial Budget Block (Phase 6) */}
      <div className="editorial-budget-matrix">
        <div className="budget-stat-cell">
          <span className="stat-cell-kicker">BUDGET CEILING</span>
          <span className="stat-cell-value">
            {budgetBudgeted ? formatCurrency(budgetMax) : 'FLEXIBLE'}
          </span>
          <span className="stat-cell-sub">
            {groupSize > 1 ? `${groupSize} people total` : 'Solo plan'}
          </span>
        </div>

        <div className="budget-cell-divider" />

        <div className="budget-stat-cell highlight-used">
          <span className="stat-cell-kicker">ESTIMATED TOTAL</span>
          <span className="stat-cell-value coral">{formatCurrency(totalCost)}</span>
          <span className="stat-cell-sub">
            {perPersonCost !== null ? `~${formatCurrency(perPersonCost)} / person` : 'Complete outing'}
          </span>
        </div>

        <div className="budget-cell-divider" />

        <div className="budget-stat-cell">
          <span className="stat-cell-kicker">
            {itinerary.isOverBudget ? 'OVER LIMIT' : 'REMAINING'}
          </span>
          <span className={`stat-cell-value ${itinerary.isOverBudget ? 'alert' : 'butter'}`}>
            {remaining !== null && remaining >= 0
              ? `${formatCurrency(remaining)}`
              : remaining !== null
              ? `+${formatCurrency(Math.abs(remaining))}`
              : 'IN BUDGET'}
          </span>
          <span className="stat-cell-sub">
            {itinerary.isOverBudget ? 'Exceeds target limit' : 'Left to spare'}
          </span>
        </div>
      </div>

      {budgetBudgeted && (
        <div className="editorial-budget-track">
          <div
            className={`budget-track-fill ${itinerary.isOverBudget ? 'over' : ''}`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      )}

      {/* Honest Planner’s Note (Phase 6 Evidence Distinction) */}
      {itinerary.tradeOffSummary && (
        <div className="editorial-planner-note">
          <div className="note-accent-bar" />
          <div className="note-content">
            <span className="note-label">✦ TRANSPARENT PLANNING EVIDENCE</span>
            <p className="note-body">{itinerary.tradeOffSummary}</p>
          </div>
        </div>
      )}

      {/* Magazine Timeline Spread */}
      <div className="magazine-timeline-stream">
        {itinerary.items.length === 0 ? (
          <div className="empty-stream-state">
            <h3 className="empty-title">All stops removed from this plan.</h3>
            <p className="empty-sub">Add a place from alternatives or re-run your intention.</p>
            {itinerary.alternatives.length > 0 && (
              <button
                type="button"
                className="btn-editorial-outline"
                onClick={() => setShowAddMenu(true)}
              >
                <IconPlus size={14} />
                <span>Add a place from alternatives</span>
              </button>
            )}
          </div>
        ) : (
          itinerary.items.map((item, idx) => {
            const isSwapping = swappingIndex === idx;
            const isLast = idx === itinerary.items.length - 1;
            const stepNum = String(idx + 1).padStart(2, '0');
            const categoryName = item.candidate.category.toUpperCase();
            const nextTransition = findTransitionBetween(item, itinerary.items[idx + 1], transitions);

            return (
              <article key={item.candidate.option_id} className={`journey-entry ${isLast ? 'last' : ''}`}>
                {/* Asymmetric Left Anchor: Time & Giant Number */}
                <div className="journey-anchor-col">
                  <div className="journey-time-box">
                    <span className="journey-time-val">
                      {item.startTime || 'FLEX'}
                    </span>
                    {item.endTime && (
                      <span className="journey-time-end">UNTIL {item.endTime}</span>
                    )}
                  </div>

                  <div className="journey-num-watermark">
                    {stepNum}
                  </div>
                </div>

                {/* Vertical Architectural Rail */}
                <div className="journey-rail">
                  <div className="rail-marker" />
                  {!isLast && <div className="rail-line" />}
                </div>

                {/* Main Stop Content Spread */}
                <div className="journey-content-block">
                  {/* Top Kicker Bar */}
                  <div className="journey-kicker-bar">
                    <div className="journey-tags-group">
                      <span className={`journey-category-tag tag-${item.candidate.category}`}>
                        {categoryName}
                      </span>
                      {item.durationMinutes && (
                        <span className="journey-duration-tag">
                          <IconClock size={11} />
                          <span>{item.durationMinutes} MIN</span>
                        </span>
                      )}
                      {item.action === 'rescheduled' && (
                        <span className="action-tag rescheduled">RESCHEDULED</span>
                      )}
                      {item.action === 'replaced' && (
                        <span className="action-tag replaced">
                          REPLACED {item.originalName ? `(${item.originalName})` : ''}
                        </span>
                      )}
                      {item.action === 'kept' && (
                        <span className="action-tag kept">KEPT</span>
                      )}
                    </div>

                    <div className="journey-price-badge">
                      {item.costNumber === 0 ? 'FREE ENTRY' : formatCurrency(item.costNumber)}
                    </div>
                  </div>

                  {/* Headline & Address */}
                  <h2 className="journey-venue-title">{item.candidate.name}</h2>
                  {(item.candidate.address || item.candidate.location) && (
                    <div className="journey-address-line">
                      <IconMapPin size={13} className="pin-icon" />
                      <span>{item.candidate.address || item.candidate.location}</span>
                    </div>
                  )}

                  {/* Verified Evidence Strip */}
                  <div className="journey-evidence-strip">
                    {item.candidate.opening_hours && (
                      <span className="evidence-pill">
                        <IconClock size={11} />
                        <span>HOURS: {item.candidate.opening_hours}</span>
                        <span className="evidence-check">✓</span>
                      </span>
                    )}
                    <span className="evidence-pill">
                      <span>VERIFIED VENUE</span>
                      <span className="evidence-check">✓</span>
                    </span>
                    {budgetMax !== null && item.costNumber <= budgetMax && (
                      <span className="evidence-pill">
                        <span>FITS BUDGET</span>
                        <span className="evidence-check">✓</span>
                      </span>
                    )}
                  </div>

                  {/* Editorial Rationale */}
                  {item.rationale && item.rationale.length > 0 && (
                    <div className="journey-rationale-section">
                      <div className="rationale-kicker">WHY THIS STOP:</div>
                      <div className="rationale-text">
                        {item.rationale.join(' · ')}
                      </div>
                    </div>
                  )}

                  {/* Interactive Controls (Swap / Remove) */}
                  <div className="journey-controls-strip">
                    {itinerary.alternatives.length > 0 && (
                      <button
                        type="button"
                        className={`btn-journey-action ${isSwapping ? 'active' : ''}`}
                        onClick={() => setSwappingIndex(isSwapping ? null : idx)}
                        disabled={isSaving}
                      >
                        <IconSwap size={13} />
                        <span>{isSwapping ? 'CLOSE ALTERNATIVES' : 'SWAP VENUE'}</span>
                      </button>
                    )}

                    <button
                      type="button"
                      className="btn-journey-action delete"
                      onClick={() => handleRemove(idx)}
                      disabled={isSaving}
                    >
                      <IconTrash size={13} />
                      <span>REMOVE STOP</span>
                    </button>
                  </div>

                  {/* Swap Alternatives Drawer */}
                  {isSwapping && (
                    <div className="journey-swap-drawer">
                      <div className="drawer-header-strip">
                        <span>SELECT ALTERNATIVE FOR STOP {stepNum}:</span>
                        <button
                          type="button"
                          className="btn-drawer-dismiss"
                          onClick={() => setSwappingIndex(null)}
                        >
                          <IconX size={14} />
                        </button>
                      </div>

                      <div className="drawer-options-list">
                        {itinerary.alternatives.map((alt) => {
                          const tradeOff = getTradeOffNote(alt, item.candidate);
                          return (
                            <div key={alt.option_id} className="drawer-option-row">
                              <div className="option-info">
                                <div className="option-title-row">
                                  <span className="option-name">{alt.name}</span>
                                  <span className="option-tradeoff">{tradeOff}</span>
                                </div>
                                <div className="option-meta">
                                  <span>{alt.category.toUpperCase()}</span>
                                  <span>·</span>
                                  <span>{formatCurrency(alt.cost)}</span>
                                  {alt.duration_minutes && <span>· {alt.duration_minutes}M</span>}
                                  {alt.location && <span>· {alt.location}</span>}
                                </div>
                              </div>

                              <button
                                type="button"
                                className="btn-select-alt"
                                onClick={() => handleSwap(idx, alt)}
                              >
                                SELECT
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {/* Mobility Transition to Next Stop */}
                  {!isLast && nextTransition && <TransitionBadge transition={nextTransition} />}
                </div>
              </article>
            );
          })
        )}
      </div>

      {/* Add Another Stop Trigger */}
      {itinerary.items.length > 0 && itinerary.items.length < 5 && itinerary.alternatives.length > 0 && !showAddMenu && (
        <div className="journey-add-section">
          <button
            type="button"
            className="btn-journey-add"
            onClick={() => setShowAddMenu(true)}
            disabled={isSaving}
          >
            <IconPlus size={15} />
            <span>ADD ANOTHER STOP TO YOUR DAY</span>
          </button>
        </div>
      )}

      {/* Add Alternative Drawer */}
      {showAddMenu && itinerary.alternatives.length > 0 && (
        <div className="journey-add-drawer">
          <div className="drawer-header-strip">
            <span>AVAILABLE LOCAL PLACES TO ADD:</span>
            <button
              type="button"
              className="btn-drawer-dismiss"
              onClick={() => setShowAddMenu(false)}
            >
              <IconX size={14} />
            </button>
          </div>

          <div className="drawer-options-list">
            {itinerary.alternatives.map((alt) => (
              <div key={alt.option_id} className="drawer-option-row">
                <div className="option-info">
                  <div className="option-title-row">
                    <span className="option-name">{alt.name}</span>
                  </div>
                  <div className="option-meta">
                    <span>{alt.category.toUpperCase()}</span>
                    <span>·</span>
                    <span>{formatCurrency(alt.cost)}</span>
                    {alt.location && <span>· {alt.location}</span>}
                  </div>
                </div>

                <button
                  type="button"
                  className="btn-select-alt"
                  onClick={() => handleAdd(alt)}
                >
                  ADD TO PLAN
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Signature Adaptation Block: "SOMETHING CHANGED?" (Phase 7) */}
      {onTweakPlan && (
        <section className="magazine-adaptation-section">
          <div className="adaptation-hero-header">
            <span className="adaptation-kicker">ADAPTIVE RE-PLANNING</span>
            <h3 className="adaptation-title">Something changed?</h3>
            <p className="adaptation-lead">
              Plans change. Dayform changes with them. Tell the engine what happened and it’ll recalculate stops, times, and budgets with minimal diff.
            </p>
          </div>

          <div className="adaptation-chips-strip">
            {[
              { label: 'MAKE IT CHEAPER', key: 'Make it cheaper' },
              { label: 'KEEP IT INDOORS', key: 'Sheltered / indoor only' },
              { label: 'ADD 2 PEOPLE', key: 'Add 2 people' },
              { label: 'RUNNING 45M LATE', key: 'Running 45m late' },
              { label: 'MOVE TO SUNDAY', key: 'Shift to Sunday' },
            ].map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="adaptation-preset-btn"
                disabled={isTweaking || isSaving}
                onClick={() => onTweakPlan(chip.key)}
              >
                <span>+</span>
                <span>{chip.label}</span>
              </button>
            ))}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (customTweak.trim() && !isTweaking && !isSaving) {
                onTweakPlan(customTweak.trim());
                setCustomTweak('');
              }
            }}
            className="adaptation-command-bar"
          >
            <input
              type="text"
              value={customTweak}
              onChange={(e) => setCustomTweak(e.target.value)}
              placeholder="e.g. Kloof Street House is fully booked, or keep total under R800..."
              disabled={isTweaking || isSaving}
              className="adaptation-input-field"
            />
            <button
              type="submit"
              disabled={!customTweak.trim() || isTweaking || isSaving}
              className="adaptation-submit-btn"
            >
              {isTweaking ? 'RECALCULATING...' : 'REWORK PLAN'}
            </button>
          </form>
        </section>
      )}

      {/* Removed Stops Warning if Adaptation Removed Items */}
      {itinerary.removedItems && itinerary.removedItems.length > 0 && (
        <div className="adaptation-removed-banner">
          <div className="removed-banner-title">
            <IconAlertCircle size={15} />
            <span>REMOVED STOPS (COULD NOT FIT REVISED CONSTRAINTS):</span>
          </div>
          <ul className="removed-items-list">
            {itinerary.removedItems.map((rem, rIdx) => (
              <li key={rIdx}>
                <strong>{rem.name}</strong> — {rem.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Bottom Main Confirm / Actions Strip */}
      <div className="magazine-bottom-strip">
        {isAdaptationReview ? (
          <div className="adaptation-actions-duo">
            <button
              type="button"
              className="btn-magazine-primary"
              onClick={onAcceptAdaptation}
              disabled={isSaving || isTweaking}
            >
              {isSaving ? 'APPLYING CHANGES...' : 'ACCEPT ADAPTATION ✓'}
            </button>

            <button
              type="button"
              className="btn-magazine-secondary"
              onClick={onRejectAdaptation}
              disabled={isSaving || isTweaking}
            >
              KEEP ORIGINAL PLAN
            </button>
          </div>
        ) : (
          <div className="normal-actions-duo">
            <button
              type="button"
              className="btn-magazine-primary hero-size"
              onClick={handleConfirmClick}
              disabled={isSaving || isTweaking || itinerary.items.length === 0}
            >
              {isSaving ? (
                'SAVING YOUR PLAN...'
              ) : (
                <>
                  <span>LOOKS GOOD · SAVE THIS PLAN</span>
                  <IconArrowRight size={18} />
                </>
              )}
            </button>

            <button
              type="button"
              className="btn-magazine-ghost"
              onClick={onModifyIntent}
              disabled={isSaving}
            >
              TRY A DIFFERENT INTENTION
            </button>
          </div>
        )}
      </div>

      {itinerary.attribution && (
        <div className="magazine-spread-colophon">
          Place, map, and hours data sourced from {itinerary.attribution}
        </div>
      )}
    </div>
  );
};
