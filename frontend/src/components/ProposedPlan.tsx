import React, { useState, useEffect, useRef } from 'react';
import type {
  DecisionCandidateRead,
  OrchestratedPlanRead,
  PlanRead,
  PlanTransitionRead,
} from '../types/planning';
import type { ProposedItineraryItem, ProposedItinerary } from '../utils/itineraryBuilder';
import {
  formatCurrency,
  formatExactCurrency,
  knownCandidateCost,
  parseCandidateCost,
  recalculateItinerary,
  humanizeCandidateReasons,
  explainUnmetRequirement,
  summarizeItineraryCosts,
  getTradeOffNote,
  resolveStopLocation,
  travelMinutesForItems,
} from '../utils/itineraryBuilder';
import { orchestratePlan } from '../api/planning';
import { explicitArea, explainOrder, explainStop, planReadiness } from '../utils/planVoice';
import { PlanIdentity } from './PlanIdentity';
import { StageFrame } from './StageFrame';
import { deriveFailureDetails } from '../utils/failureVoice';
import { transportPreferenceForMode } from '../utils/transportPreferences';
import {
  IconClock,
  IconMapPin,
  IconSwap,
  IconTrash,
  IconPlus,
  IconSparkles,
  IconAlertCircle,
  IconX,
  IconNavigation,
  IconExternalLink,
  IconPhone,
  IconCalendar,
  IconCheck,
} from './Icons';
import { TransportLeg } from './TransportLeg';

/**
 * Transport choices the user can state up front. Each maps to M14 transport
 * modes; the server only applies one where it is genuinely applicable, and says
 * so when it is not. An empty selection means "no preference", which leaves the
 * server ranking the options it actually found.
 */
interface TransportChoice {
  label: string;
  modes?: string[];
  providerId?: string;
}

const TRANSPORT_PREFERENCES: Record<string, TransportChoice> = {
  walking: { label: 'Walk', modes: ['walk'], providerId: 'walking' },
  myciti: { label: 'MyCiTi Bus', modes: ['bus'], providerId: 'myciti' },
  metrorail: { label: 'Metrorail', modes: ['train'], providerId: 'prasa_metrorail' },
  uber: { label: 'Uber', modes: ['ride_hail'], providerId: 'uber' },
  bolt: { label: 'Bolt', modes: ['ride_hail'], providerId: 'bolt' },
  public_transport: { label: 'Public transport', modes: ['train', 'bus'] },
};

/** Raw coordinates are not a place name, so they are described rather than shown. */
function describeOrigin(origin: string): string {
  const looksLikeCoords = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/.test(origin.trim());
  return looksLikeCoords ? 'your current location' : origin;
}

/** Combine a proposed stop's HH:MM slot with the plan's calendar date into an ISO instant. */
function toIsoTimestamp(baseDate: Date, hhmm?: string): string | null {
  if (!hhmm) return null;
  const [h, m] = hhmm.split(':').map((v) => parseInt(v, 10));
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  const d = new Date(baseDate);
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

/** Render an ISO instant as a local HH:MM clock time. */
function formatClock(iso?: string | null): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  return `${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`;
}

function venueActionIcon(actionType: string) {
  if (actionType === 'directions') {
    return <IconNavigation size={13} />;
  }
  if (actionType === 'call') {
    return <IconPhone size={13} />;
  }
  if (actionType === 'reserve') {
    return <IconCalendar size={13} />;
  }
  return <IconExternalLink size={13} />;
}

function deriveCandidateActions(candidate: DecisionCandidateRead): Array<{
  action_type: string;
  label: string;
  target_url: string;
  description: string;
}> {
  const actions: Array<{
    action_type: string;
    label: string;
    target_url: string;
    description: string;
  }> = [];

  const address = (candidate.address || candidate.location || '').trim();
  const sourceUrl = candidate.source_url?.trim();
  const phone = candidate.phone?.trim();
  const reservationUrl = candidate.reservation_url?.trim();

  if (sourceUrl && (sourceUrl.startsWith('https://') || sourceUrl.startsWith('http://'))) {
    actions.push({
      action_type: 'open_website',
      label: 'Website',
      target_url: sourceUrl,
      description: `Visit the official website of ${candidate.name}`,
    });
  }

  if (address) {
    const encoded = encodeURIComponent(address);
    actions.push({
      action_type: 'directions',
      label: 'Directions',
      target_url: `https://www.google.com/maps/search/?api=1&query=${encoded}`,
      description: `Get directions to ${address}`,
    });
  }

  if (phone) {
    const digits = phone.replace(/[^\d+]/g, '');
    if (digits) {
      actions.push({
        action_type: 'call',
        label: 'Call',
        target_url: `tel:${digits}`,
        description: `Call ${phone}`,
      });
    }
  }

  if (reservationUrl && (reservationUrl.startsWith('https://') || reservationUrl.startsWith('http://'))) {
    actions.push({
      action_type: 'reserve',
      label: 'Reserve',
      target_url: reservationUrl,
      description: `Open the official booking page for ${candidate.name}`,
    });
  }

  return actions;
}

export interface PlanItemCandidateSelection {
  candidate: DecisionCandidateRead;
  position?: number;
  startTime?: string;
  endTime?: string;
}

export interface PlanConfirmMeta {
  origin?: string;
  transportPreference?: string;
}

interface ProposedPlanProps {
  plan: PlanRead;
  initialItinerary: ProposedItinerary;
  allCandidates: DecisionCandidateRead[];
  budgetMax: number | null;
  onConfirm: (
    selectedCandidates: DecisionCandidateRead[],
    scheduledItems?: PlanItemCandidateSelection[],
    meta?: PlanConfirmMeta,
    customTitle?: string
  ) => Promise<void> | void;
  isSaving: boolean;
  onModifyIntent: () => void;
  onTweakPlan?: (tweakText: string) => Promise<void>;
  isTweaking?: boolean;
  isAdaptationReview?: boolean;  adaptationSummary?: string;
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
  // The server-produced, transport-aware schedule. Transport is resolved before
  // these times exist, so the timeline already contains the travel.
  const [orchestrated, setOrchestrated] = useState<OrchestratedPlanRead | null>(null);
  const [orchestrating, setOrchestrating] = useState(false);
  // The starting location is typed first and confirmed second, so a location the
  // user did not confirm is never sent to planning as their origin.
  const [originDraft, setOriginDraft] = useState('');
  const [origin, setOrigin] = useState<string | null>(null);
  const [editingOrigin, setEditingOrigin] = useState(false);
  const originFieldRef = useRef<HTMLInputElement | null>(null);
  // The user's transport choice, applied by the server wherever it is viable.
  const [transportPreference, setTransportPreference] = useState<string>(() =>
    transportPreferenceForMode(plan.understanding?.transport_mode || plan.context?.transport_mode)
  );
  // User selections for specific individual transport legs
  const [selectedLegOptions, setSelectedLegOptions] = useState<Record<number, string>>({});
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [savePlanTitle, setSavePlanTitle] = useState('');
  const [saveConfirmation, setSaveConfirmation] = useState<string | null>(null);

  const handleSelectLegOption = (legIndex: number, optionId: string) => {
    setSelectedLegOptions((prev) => ({
      ...prev,
      [legIndex]: optionId,
    }));
  };

  const handleTransportPreferenceChange = (key: string) => {
    setTransportPreference((prev) => (prev === key ? '' : key));
    setSelectedLegOptions({});
  };

  // Travel minutes already folded into the current schedule, so re-applying the
  // same transitions is a no-op and the schedule/transition cycle settles.
  const appliedTravelRef = useRef<string>('');

  useEffect(() => {
    setItinerary(initialItinerary);
    appliedTravelRef.current = '';
  }, [initialItinerary]);

  // An origin stated in the plan itself is the confirmed one; nothing is inferred.
  useEffect(() => {
    const stated = plan.understanding?.origin || plan.context?.origin || null;
    setOrigin(stated || null);
    setOriginDraft(stated || '');
    setEditingOrigin(!stated);
    setTransportPreference(transportPreferenceForMode(
      plan.understanding?.transport_mode || plan.context?.transport_mode
    ));
    setSelectedLegOptions({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.id]);

  const groupSize = plan.context?.group_size || 1;

  // The orchestrated stop at the same position as this item. Transport has
  // already been folded into these times on the server.
  // The server may remove a stop to satisfy a hard constraint, so the presented
  // itinerary follows the validated one. Times are matched by name rather than
  // position so a removed stop cannot shift another stop's window.
  const orchestratedStops = orchestrated?.stops;
  const orchestratedStop = (item: ProposedItineraryItem) =>
    orchestratedStops?.find((stop) => stop.name === item.candidate.name) ?? null;
  const visibleItems = orchestratedStops
    ? itinerary.items.filter((item) => orchestratedStops.some((stop) => stop.name === item.candidate.name))
    : itinerary.items;

  // Legs include an origin leg when an origin is known, so between-stop legs
  // start one position later in that case, and the origin leg is shown before
  // the first stop rather than being dropped.
  const legOffset = orchestrated?.origin_resolved ? 1 : 0;
  const legAfter = (idx: number) => orchestrated?.legs?.[legOffset + idx] ?? null;
  const originLeg = orchestrated?.origin_resolved ? orchestrated?.legs?.[0] ?? null : null;

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
          option_id: it.candidate.option_id,
          start_time: toIsoTimestamp(baseDate, it.startTime),
          end_time: toIsoTimestamp(baseDate, it.endTime),
          estimated_cost: it.costNumber,
          address: it.candidate.address || location,
          opening_hours: it.candidate.opening_hours ?? null,
          phone: it.candidate.phone ?? null,
          source_url: it.candidate.source_url ?? null,
          reservation_url: it.candidate.reservation_url ?? null,
          category: it.candidate.category,
          duration_minutes: it.candidate.duration_minutes ?? it.durationMinutes ?? null,
          // The provider's own words travel with the stop so the server can
          // check coverage against real evidence.
          description: it.candidate.description ?? null,
        };
      })
      .filter((s): s is NonNullable<typeof s> => s !== null);

    if (stops.length === 0) {
      // Still ask the server to validate. An empty stop list is a legitimate
      // outcome when nothing suitable exists in the area the user asked for,
      // and the server is the only thing that can say why. Short-circuiting
      // here would leave the user looking at an unexplained empty plan.
      setOrchestrating(true);
      orchestratePlan(plan.id, [], origin, undefined, groupSize)
        .then((res) => {
          setOrchestrated(res);
          setTransitions([]);
        })
        .catch(() => {
          setOrchestrated(null);
          setTransitions([]);
        })
        .finally(() => setOrchestrating(false));
      return;
    }

    let cancelled = false;
    setOrchestrating(true);
    // The confirmed origin and the stated transport choice both drive transport
    // evaluation, so both re-run the orchestration when they change.
    const prefChoice = TRANSPORT_PREFERENCES[transportPreference];
    const preferredModes = prefChoice?.modes;
    const preferredProvider = prefChoice?.providerId || null;
    orchestratePlan(
      plan.id,
      stops,
      origin,
      preferredModes,
      groupSize,
      preferredProvider,
      selectedLegOptions
    )
      .then((res) => {
        if (cancelled) return;
        setOrchestrated(res);
        setTransitions(Array.isArray(res?.legs) ? res.legs.map((leg) => leg.transition) : []);
      })
      .catch((err) => {
        // Mobility is additive context: a lookup failure must not break the
        // proposal, but the user is no longer shown a schedule we cannot trust.
        console.error('Failed to orchestrate plan:', err);
        if (!cancelled) {
          setOrchestrated(null);
          setTransitions([]);
        }
      })
      .finally(() => {
        if (!cancelled) setOrchestrating(false);
      });

    return () => {
      cancelled = true;
    };
  }, [plan.id, stopSignature, groupSize, plan.context?.start_time, origin, transportPreference, selectedLegOptions]);

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

  // A plan that knowingly misses a hard constraint is not the user's plan yet.
  // A plan that misses a stated *requirement* is still a real, savable day — but
  // it must not be presented as the whole thing they asked for, so the two cases
  // are decided separately rather than by one "looks good" label.
  const readiness = planReadiness(orchestrated, orchestrated?.coverage);
  const blockedByValidation = readiness.kind === 'blocked';
  const partiallySatisfied = readiness.kind === 'partial';

  const handleOpenSaveModal = () => {
    if (blockedByValidation) return;
    const defaultTitle = plan.title || plan.intention || 'My Cape Town Day';
    setSavePlanTitle(defaultTitle);
    setShowSaveModal(true);
  };

  const handleExecuteSave = async () => {
    setShowSaveModal(false);
    // Persist what is actually being shown, so a stop the planner removed to
    // satisfy a constraint is not quietly saved behind the user's back.
    const candidatesToPersist = visibleItems.map((i) => i.candidate);
    const scheduledToPersist: PlanItemCandidateSelection[] = visibleItems.map((item, index) => {
      const scheduled = orchestratedStop(item);
      return {
        candidate: item.candidate,
        position: index,
        startTime: scheduled?.start_time || undefined,
        endTime: scheduled?.end_time || undefined,
      };
    });
    const finalTitle = savePlanTitle.trim() || undefined;
    await onConfirm(
      candidatesToPersist,
      scheduledToPersist,
      {
        origin: origin || undefined,
        transportPreference: transportPreference || undefined,
      },
      finalTitle
    );
    setSaveConfirmation(
      finalTitle ? `"${finalTitle}" saved to your Plan Library.` : 'Plan saved to your Plan Library.'
    );
    setTimeout(() => setSaveConfirmation(null), 5000);
  };

  // Roll up only the stops that survived orchestration, plus selected transport.
  const budgetBudgeted = budgetMax !== null;
  const costSummary = summarizeItineraryCosts(
    visibleItems.map((item) => orchestratedStop(item)?.estimated_cost ?? item.candidate.cost),
    orchestrated?.feasibility?.total_known_transition_cost,
    orchestrated?.feasibility?.has_unknown_transition_costs ?? false,
    budgetMax
  );
  const totalCost = costSummary.knownTotal;
  const totalCostLabel = costSummary.totalLabel;
  const remaining = costSummary.remainingBudget;
  const isOverBudget = costSummary.isOverBudget;
  const perPersonCost = groupSize > 1 && !costSummary.hasUnknownCosts
    ? Math.round(totalCost / groupSize)
    : null;
  const hasCompleteCostRollup = Boolean(orchestrated && !orchestrating);
  const progressPercent = budgetBudgeted && budgetMax > 0 && !costSummary.hasUnknownCosts
    ? Math.min(100, Math.round((totalCost / budgetMax) * 100))
    : 0;

  // Early return: clean consumer failure state if no qualifying stops were found
  if (visibleItems.length === 0) {
    const failure = deriveFailureDetails(plan, allCandidates, budgetMax, onTweakPlan, onModifyIntent);

    return (
      <div className="magazine-itinerary-stage animate-fade-in">
        <div className="df-failure-card">
          <div className="df-failure-icon-box">
            <IconAlertCircle size={28} />
          </div>
          <h2 className="df-failure-headline">{failure.headline}</h2>
          <p className="df-failure-explanation">{failure.explanation}</p>

          <div className="df-failure-actions">
            {failure.recoveryActions.map((action, idx) => (
              <button
                key={idx}
                type="button"
                className={action.primary ? 'btn-editorial-primary' : 'btn-editorial-secondary'}
                onClick={action.onClick}
                disabled={isTweaking || isSaving}
              >
                <span>{action.label}</span>
              </button>
            ))}
          </div>

          {onTweakPlan && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (customTweak.trim() && !isTweaking && !isSaving) {
                  onTweakPlan(customTweak.trim());
                  setCustomTweak('');
                }
              }}
              className="df-failure-custom-bar"
            >
              <input
                type="text"
                value={customTweak}
                onChange={(e) => setCustomTweak(e.target.value)}
                placeholder="Or tell me what to adjust in your own words…"
                disabled={isTweaking || isSaving}
                aria-label="Tell Dayform what to adjust"
                className="adaptation-input-field"
              />
              <button
                type="submit"
                disabled={!customTweak.trim() || isTweaking || isSaving}
                className="adaptation-submit-btn"
              >
                {isTweaking ? 'Reworking…' : 'Rework'}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  // The itinerary is introduced as the afternoon it actually is, rather than as
  // a heading that could belong to any plan.
  const windowWord = (plan.understanding?.time_window ?? '').toLowerCase();
  const sceneTitle = /^morning/.test(windowWord)
    ? 'Your morning.'
    : /^evening|^night|^late/.test(windowWord)
      ? 'Your evening.'
      : /^lunch/.test(windowWord)
        ? 'Your lunch.'
        : 'Your afternoon.';

  return (
    <div className="magazine-itinerary-stage">
      {/* 04 — THE ITINERARY */}
      <StageFrame
        stage={4}
        hideStageMeta={true}
        className="df-itinerary-scene"
        title={sceneTitle}
        lede={`${visibleItems.length === 1 ? 'One place' : `${visibleItems.length} places`}, in an order you can actually walk, at times that work with real opening hours.`}
      >
        {/* The plan's identity: What is my day, when am I going, and how much will it cost */}
        <PlanIdentity
          understanding={plan.understanding}
          items={visibleItems}
          orchestrated={orchestrated}
          fallbackSpan={itinerary.timeSpanDisplay}
          totalCost={hasCompleteCostRollup ? totalCost : undefined}
          totalCostLabel={totalCostLabel}
          budgetMax={budgetMax}
          isOverBudget={isOverBudget}
          hasUnknownCosts={costSummary.hasUnknownCosts}
        />

        {/* Clear editorial notification if any requirement could not be satisfied */}
        {(() => {
          const unmet = orchestrated?.coverage?.items?.filter((item) => !item.is_covered) || [];
          if (!unmet.length) return null;
          return (
            <div className="df-requirement-notice is-unmet" role="alert">
              <IconAlertCircle size={14} />
              <span>
                {unmet.map((item) => explainUnmetRequirement(
                  item,
                  allCandidates,
                  orchestrated?.removed_stops,
                  budgetMax,
                  explicitArea(plan.understanding)
                )).join(' ')}
              </span>
            </div>
          );
        })()}

        {/* Where the day starts from. It changes the schedule, so it sits with
            the itinerary rather than being buried in settings — but it is a
            control, not a headline, so it is held at the meta scale. */}
        <div className="origin-panel df-origin-strip">
          <div className="origin-panel-head">
            <span className="origin-panel-label">Starting from</span>
            {origin && !editingOrigin && (
              <span className="origin-resolved-chip">
                <IconMapPin size={12} />
                {describeOrigin(origin)}
              </span>
            )}
          </div>

          <div className="origin-panel-controls">
            {(editingOrigin || !origin) && (
              <>
                <input
                  ref={originFieldRef}
                  type="text"
                  className="origin-input"
                  placeholder="Search for a starting location…"
                  value={originDraft}
                  onChange={(e) => setOriginDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && originDraft.trim()) {
                      e.preventDefault();
                      setOrigin(originDraft.trim());
                      setEditingOrigin(false);
                    }
                  }}
                  aria-label="Search for a starting location"
                />
                <button
                  type="button"
                  className="btn-origin-locate"
                  onClick={() => {
                    /* Only ever used after the user grants location permission. */
                    if (!navigator.geolocation) return;
                    navigator.geolocation.getCurrentPosition(
                      (pos) => {
                        const coords = `${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`;
                        setOriginDraft(coords);
                        /* An explicit opt-in click is the user's confirmation. */
                        setOrigin(coords);
                        setEditingOrigin(false);
                      },
                      () => {
                        /* Permission denied or unavailable: leave origin unset. */
                      }
                    );
                  }}
                >
                  Use my location
                </button>
                <button
                  type="button"
                  className="btn-origin-confirm"
                  disabled={!originDraft.trim()}
                  onClick={() => {
                    setOrigin(originDraft.trim());
                    setEditingOrigin(false);
                  }}
                >
                  Set this
                </button>
              </>
            )}

            {origin && editingOrigin && (
              <button
                type="button"
                className="btn-origin-change"
                onClick={() => {
                  setOrigin(null);
                  setEditingOrigin(false);
                  originFieldRef.current?.focus();
                }}
              >
                Remove starting point
              </button>
            )}

            {origin && !editingOrigin && (
              <button
                type="button"
                className="btn-origin-change"
                onClick={() => {
                  setEditingOrigin(true);
                  setTimeout(() => originFieldRef.current?.focus(), 0);
                }}
              >
                Change
              </button>
            )}
          </div>

          {!origin && (
            <p className="origin-panel-hint">
              Without a starting point, travel to your first stop is not in the schedule yet.
            </p>
          )}

          {/* Transport is a planning input, so the user states how they move. */}
          <div className="transport-preference">
            <span className="transport-preference-label">Getting around</span>
            <div className="transport-preference-options" role="group" aria-label="Transport preference">
              <button
                type="button"
                className={`transport-preference-chip${transportPreference === '' ? ' is-active' : ''}`}
                aria-pressed={transportPreference === ''}
                onClick={() => handleTransportPreferenceChange('')}
              >
                Best match
              </button>
              {Object.entries(TRANSPORT_PREFERENCES).map(([key, pref]) => (
                <button
                  key={key}
                  type="button"
                  className={`transport-preference-chip${transportPreference === key ? ' is-active' : ''}`}
                  aria-pressed={transportPreference === key}
                  onClick={() => handleTransportPreferenceChange(key)}
                >
                  {pref.label}
                </button>
              ))}
            </div>
            {orchestrated?.transport_preference_note && (
              <p className="transport-preference-note">
                <IconAlertCircle size={12} />
                <span>{orchestrated.transport_preference_note}</span>
              </p>
            )}
          </div>
        </div>

        {orchestrating && (
          <div className="orchestration-status">Working out how you get between each stop…</div>
        )}

        {/* ------------------------------------------------------------------
            THE DAY ITSELF
            ------------------------------------------------------------------ */}
        {itinerary.items.length === 0 ? (
          <div className="empty-stream-state">
            <h3 className="empty-title">No stops left in this plan.</h3>
            <p className="empty-sub">Add a place from the alternatives, or start again with a different intention.</p>
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
          <>
            {/* Why the day is in this order, when opening hours actually force it. */}
            {(() => {
              const order = explainOrder(orchestrated?.stops ?? []);
              if (!order) return null;
              return (
                <div className="df-order-note">
                  <span className="df-order-kicker">{order.headline}</span>
                  <span className="df-order-detail">{order.detail}</span>
                </div>
              );
            })()}

            {/* How the user gets from their stated origin to the first stop. */}
            {originLeg && (
              <TransportLeg
                leg={originLeg}
                legIndex={0}
                onSelectOption={handleSelectLegOption}
              />
            )}
            {visibleItems.map((item, idx) => {
            const isSwapping = swappingIndex === idx;
            const isLast = idx === visibleItems.length - 1;
            const stepNum = String(idx + 1).padStart(2, '0');
            const categoryName = item.candidate.category.toUpperCase();
            const scheduled = orchestratedStop(item);
            const stopCost = scheduled?.estimated_cost ?? item.candidate.cost;
            const startLabel = formatClock(scheduled?.start_time) || item.startTime || 'FLEX';
            const endLabel = formatClock(scheduled?.end_time) || item.endTime;
            const nextLeg = legAfter(idx);
            const rawHours = item.candidate.opening_hours || scheduled?.opening_hours;
            const formattedHours = rawHours
              ? (/^open/i.test(rawHours.trim()) ? rawHours.trim() : `Open ${rawHours.trim()}`)
              : 'Opening hours unavailable';
            // Why this stop, answered from the constraints it actually satisfies.
            const why = explainStop(item.candidate, scheduled ?? null, {
              budgetMax,
              area: explicitArea(plan.understanding),
              cost: item.costNumber,
            });

            return (
              <article key={item.candidate.option_id} className={`journey-entry ${isLast ? 'last' : ''}`}>
                {/* Asymmetric Left Anchor: Time & Giant Number */}
                <div className="journey-anchor-col">
                  <div className="journey-time-box">
                    <span className="journey-time-val">
                      {startLabel}
                    </span>
                    {endLabel && (
                      <span className="journey-time-end">until {endLabel}</span>
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
                  <div className="journey-kicker-bar">
                    <div className="journey-tags-group">
                      <span className={`journey-category-tag tag-${item.candidate.category}`}>
                        {categoryName}
                      </span>
                      {item.durationMinutes && (
                        <span className="journey-duration-tag">
                          <IconClock size={11} />
                          <span>{item.durationMinutes} min</span>
                        </span>
                      )}
                      {item.action === 'rescheduled' && (
                        <span className="action-tag rescheduled">Rescheduled</span>
                      )}
                      {item.action === 'replaced' && (
                        <span className="action-tag replaced">
                          Replaced {item.originalName ? `(${item.originalName})` : ''}
                        </span>
                      )}
                      {item.action === 'kept' && (
                        <span className="action-tag kept">Kept</span>
                      )}
                    </div>

                    <div className="journey-price-badge">
                      {knownCandidateCost(stopCost) === null
                        ? 'Price not listed'
                        : knownCandidateCost(stopCost) === 0
                          ? 'Free entry'
                          : formatExactCurrency(knownCandidateCost(stopCost)!)}
                    </div>
                  </div>

                  <h3 className="journey-venue-title">{item.candidate.name}</h3>
                  {(item.candidate.address || item.candidate.location || formattedHours) && (
                    <div className="journey-venue-meta-row">
                      {(item.candidate.address || item.candidate.location) && (
                        <div className="journey-address-line">
                          <IconMapPin size={13} className="pin-icon" />
                          <span>{item.candidate.address || item.candidate.location}</span>
                        </div>
                      )}
                      {formattedHours && (
                        <div className="journey-hours-line">
                          <IconClock size={13} className="hours-icon" />
                          <span>{formattedHours}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* The planner's reasoning, in one sentence, from real data. */}
                  {why.reasons.length > 0 && (
                    <div className="df-why">
                      <span className="df-why-kicker">{why.headline}</span>
                      <span className="df-why-text">
                        {why.reasons.map((r) => r.charAt(0).toUpperCase() + r.slice(1)).join(' · ')}
                      </span>
                    </div>
                  )}

                  {/* Real venue actions (Directions, Website, Reserve, Call) placed ahead of editing controls */}
                  {(() => {
                    const stopActions = (scheduled?.actions && scheduled.actions.length > 0)
                      ? scheduled.actions
                      : deriveCandidateActions(item.candidate);
                    const contactHint = scheduled?.contact_hint;

                    if (stopActions.length === 0 && !contactHint) return null;

                    return (
                      <div className="venue-detail">
                        <div className="venue-actions">
                          {stopActions.map((action) => (
                            <a
                              key={`${action.action_type}-${action.target_url}`}
                              href={action.target_url}
                              target={action.action_type === 'call' ? undefined : '_blank'}
                              rel={action.action_type === 'call' ? undefined : 'noopener noreferrer'}
                              className={`venue-action venue-action-${action.action_type}`}
                              title={action.description || action.label}
                            >
                              {venueActionIcon(action.action_type)}
                              <span>{action.label}</span>
                            </a>
                          ))}
                          {contactHint && (
                            <span className="venue-action-hint">{contactHint}</span>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  {/* Secondary itinerary editing controls (Swap / Remove) */}
                  <div className="journey-controls-strip">
                    {itinerary.alternatives.length > 0 && (
                      <button
                        type="button"
                        className={`btn-journey-action ${isSwapping ? 'active' : ''}`}
                        onClick={() => setSwappingIndex(isSwapping ? null : idx)}
                        disabled={isSaving}
                      >
                        <IconSwap size={13} />
                        <span>{isSwapping ? 'Close alternatives' : 'Swap venue'}</span>
                      </button>
                    )}

                    <button
                      type="button"
                      className="btn-journey-action delete"
                      onClick={() => handleRemove(idx)}
                      disabled={isSaving}
                    >
                      <IconTrash size={13} />
                      <span>Remove stop</span>
                    </button>
                  </div>

                  {/* Swap Alternatives Drawer */}
                  {isSwapping && (
                    <div className="journey-swap-drawer">
                      <div className="drawer-header-strip">
                        <span>Instead of this, how about</span>
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
                                  {alt.duration_minutes && <span>· {alt.duration_minutes}m</span>}
                                  {alt.location && <span>· {alt.location}</span>}
                                </div>
                              </div>

                              <button
                                type="button"
                                className="btn-select-alt"
                                onClick={() => handleSwap(idx, alt)}
                              >
                                Swap
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Transport to the next stop, already inside the schedule */}
                  {!isLast && nextLeg && (
                    <TransportLeg
                      leg={nextLeg}
                      legIndex={legOffset + idx}
                      onSelectOption={handleSelectLegOption}
                    />
                  )}
                </div>
              </article>
            );
          })}
            </>
        )}

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
              <span>Add a place</span>
            </button>
          </div>
        )}

        {/* Add Alternative Drawer */}
        {showAddMenu && itinerary.alternatives.length > 0 && (
          <div className="journey-add-drawer">
            <div className="drawer-header-strip">
              <span>Places nearby you could add</span>
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
                    Add
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Anything the plan could not satisfy is stated, never presented as
            done. These sit after the day itself, because that is what they are
            about. */}
        {orchestrated && !orchestrating && orchestrated.is_valid === false && (
          <div className="plan-conflict" role="alert">
            <div className="plan-conflict-head">
              <IconAlertCircle size={13} />
              <span>A few items couldn't be fitted into this schedule</span>
            </div>
            {orchestrated.conflicts && orchestrated.conflicts.length > 0 && (
              <ul className="plan-conflict-list">
                {orchestrated.conflicts.map((conflict, index) => (
                  <li key={`${conflict.kind}-${index}`}>{conflict.message}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {orchestrated && !orchestrating && orchestrated.removed_stops && orchestrated.removed_stops.length > 0 && (
          <div className="plan-conflict is-notice">
            <div className="plan-conflict-head">
              <IconAlertCircle size={13} />
              <span>Adjusted to fit what you asked for</span>
            </div>
            <ul className="plan-conflict-list">
              {orchestrated.removed_stops.map((stop) => (
                <li key={stop.name}>
                  <strong>{stop.name}</strong> was removed because {stop.reason}.
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* ------------------------------------------------------------------
            THE DETAILS
            Budget, travel, evidence and caveats are all real and all worth
            having. They were competing with the day itself, so they now wait to
            be asked for — still on the page, still readable, just not shouting
            over the thing the user came for.
            ------------------------------------------------------------------ */}
        {orchestrated && !orchestrating && (
          <div className="df-summary-section">
            <div className="df-summary-header-row">
              <h3 className="df-summary-section-heading">Budget and timing summary</h3>
              <div className="df-budget-pill-wrapper">
                <span className="df-budget-summary-pill">
                  {budgetBudgeted ? `${totalCostLabel} of ${formatCurrency(budgetMax)}` : totalCostLabel}
                </span>
                {budgetBudgeted && (
                  <span className={`df-budget-status-pill ${isOverBudget ? 'is-over' : costSummary.hasUnknownCosts ? 'is-unverified' : 'is-under'}`}>
                    {isOverBudget ? 'Over limit' : costSummary.hasUnknownCosts ? 'Cost unavailable' : 'In budget'}
                  </span>
                )}
              </div>
            </div>

            {/* Directly visible budget summary */}
            <div className="editorial-budget-matrix">
              <div className="budget-stat-cell">
                <span className="stat-cell-kicker">Budget ceiling</span>
                <span className="stat-cell-value">
                  {budgetBudgeted ? formatCurrency(budgetMax) : 'FLEXIBLE'}
                </span>
                <span className="stat-cell-sub">
                  {groupSize > 1 ? `${groupSize} people total` : 'Solo plan'}
                </span>
              </div>

              <div className="budget-cell-divider" />

              <div className="budget-stat-cell highlight-used">
                <span className="stat-cell-kicker">Estimated total</span>
                  <span className="stat-cell-value coral">{totalCostLabel}</span>
                <span className="stat-cell-sub">
                  {costSummary.hasUnknownCosts
                    ? 'Some prices are unavailable'
                    : perPersonCost !== null ? `~${formatCurrency(perPersonCost)} / person` : 'Complete outing'}
                </span>
              </div>

              <div className="budget-cell-divider" />

              <div className="budget-stat-cell">
                <span className="stat-cell-kicker">
                  {itinerary.isOverBudget ? 'Over limit' : 'Remaining'}
                </span>
                <span className={`stat-cell-value ${itinerary.isOverBudget ? 'alert' : 'butter'}`}>
                  {remaining !== null && remaining >= 0
                    ? `${formatExactCurrency(remaining)}`
                    : remaining !== null
                      ? `+${formatExactCurrency(Math.abs(remaining))}`
                      : budgetBudgeted ? 'Unavailable' : 'Flexible'}
                </span>
                <span className="stat-cell-sub">
                  {costSummary.hasUnknownCosts
                    ? 'Some prices are unavailable'
                    : isOverBudget ? 'Exceeds target limit' : budgetBudgeted ? 'Left to spare' : 'No ceiling set'}
                </span>
              </div>
            </div>

            {budgetBudgeted && budgetMax > 0 && !costSummary.hasUnknownCosts && (
              <div className="editorial-budget-track">
                <div
                  className={`budget-track-fill ${itinerary.isOverBudget ? 'over' : ''}`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            )}

            {itinerary.attribution && (
              <p className="df-support df-colophon">
                Place, map and hours data from {itinerary.attribution}
              </p>
            )}
          </div>
        )}

        {/* The save decision. Distinct states, and a blocked plan says so
            rather than offering a button that will not work. */}
        <div className="df-confirm-container">
          {isAdaptationReview ? (
            <div className="adaptation-actions-duo">
              <button
                type="button"
                className="btn-magazine-primary"
                onClick={onAcceptAdaptation}
                disabled={isSaving || isTweaking}
              >
                {isSaving ? 'Applying changes…' : 'Keep these changes'}
              </button>

              <button
                type="button"
                className="btn-magazine-secondary"
                onClick={onRejectAdaptation}
                disabled={isSaving || isTweaking}
              >
                Go back to the original
              </button>
            </div>
          ) : (
            <section className={`df-confirm-card is-${readiness.kind}`} aria-label="Plan confirmation">
              <div className="df-confirm-badge-wrap">
                <span className={`df-confirm-badge is-${readiness.kind}`}>
                  {readiness.kind === 'ready'
                    ? 'Ready'
                    : readiness.kind === 'partial'
                      ? 'Partly shaped'
                      : 'Not yet'}
                </span>
              </div>

              <h2 className="df-confirm-heading">{readiness.headline}</h2>

              <p className="df-confirm-copy">{readiness.detail}</p>

              <div className="df-confirm-actions">
                <button
                  type="button"
                  className={`btn-confirm-save is-${readiness.kind}`}
                  onClick={handleOpenSaveModal}
                  disabled={isSaving || isTweaking || itinerary.items.length === 0 || blockedByValidation}
                >
                  {isSaving ? (
                    'Saving your plan…'
                  ) : blockedByValidation ? (
                    'Not savable yet'
                  ) : (
                    readiness.actionLabel ?? 'Save this plan'
                  )}
                </button>

                <button
                  type="button"
                  className="btn-confirm-restart"
                  onClick={onModifyIntent}
                  disabled={isSaving}
                >
                  Start again
                </button>
              </div>

              {saveConfirmation && (
                <div className="save-confirmation-alert animate-fade-in" role="status">
                  <IconCheck size={16} />
                  <span>{saveConfirmation}</span>
                </div>
              )}

              {partiallySatisfied && (
                <p className="df-confirm-aside">
                  Saving keeps only the stops above. The missing{' '}
                  {readiness.missing.join(' and ')} is noted on the plan, so you can see exactly
                  what you got.
                </p>
              )}
            </section>
          )}
        </div>
      </StageFrame>

      {/* Save Plan Modal Dialog */}
      {showSaveModal && (
        <div className="df-modal-overlay" onClick={() => setShowSaveModal(false)}>
          <div
            className="df-modal-box save-plan-modal animate-scale-up"
            role="dialog"
            aria-labelledby="save-plan-dialog-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="df-modal-header">
              <h3 id="save-plan-dialog-title" className="df-modal-title">Save plan</h3>
              <button
                type="button"
                className="btn-modal-close"
                onClick={() => setShowSaveModal(false)}
                aria-label="Close"
              >
                <IconX size={16} />
              </button>
            </div>

            <div className="df-modal-body">
              <p className="df-modal-lead">
                Give your plan a title, or save it with the default name.
              </p>
              <label htmlFor="save-plan-title-input" className="df-sr-only">
                Plan name
              </label>
              <input
                id="save-plan-title-input"
                type="text"
                className="df-modal-input"
                value={savePlanTitle}
                onChange={(e) => setSavePlanTitle(e.target.value)}
                placeholder="e.g. Saturday in Observatory"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleExecuteSave();
                  }
                }}
              />
            </div>

            <div className="df-modal-footer">
              <button
                type="button"
                className="btn-magazine-ghost"
                onClick={() => setShowSaveModal(false)}
                disabled={isSaving}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn-magazine-primary df-modal-cta"
                onClick={handleExecuteSave}
                disabled={isSaving}
              >
                {isSaving ? 'Saving…' : 'Save plan'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================
          05 — THE ADAPTATION
          The world changes and Dayform changes only what needed changing. The
          scene is deliberately quieter than the itinerary above it: this is an
          epilogue, not a second pitch.
          =================================================================== */}
      {onTweakPlan && (
        <StageFrame
          stage={5}
          hideStageMeta={true}
          className="df-adaptation-scene df-light df-light--still"
          title="Something changed?"
          lede="Tell me what happened and I'll rework the day around it — changing only what has to change."
        >
          {(isAdaptationReview || itinerary.isAdaptationProposal) && (
            <div className="magazine-adaptation-banner df-adaptation-outcome">
              <div className="adaptation-banner-tag">
                <IconSparkles size={14} />
                <span>Reworked — only what needed changing</span>
              </div>
              <p className="adaptation-banner-narrative">
                {adaptationSummary || itinerary.adaptationSummary || 'Adapted around your change.'}
              </p>
            </div>
          )}

          {itinerary.removedItems && itinerary.removedItems.length > 0 && (
            <div className="adaptation-removed-banner">
              <div className="removed-banner-title">
                <IconAlertCircle size={15} />
                <span>What this cost</span>
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

          <div className="adaptation-chips-strip">
            {[
              { label: 'Make it cheaper', key: 'Make it cheaper' },
              { label: 'Keep it indoors', key: 'Sheltered / indoor only' },
              { label: 'Two more people', key: 'Add 2 people' },
              { label: 'Running 45m late', key: 'Running 45m late' },
              { label: 'Move to Sunday', key: 'Shift to Sunday' },
            ].map((chip) => (
              <button
                key={chip.key}
                type="button"
                className="adaptation-preset-btn"
                disabled={isTweaking || isSaving}
                onClick={() => onTweakPlan(chip.key)}
              >
                {chip.label}
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
              placeholder="Or tell me in your own words…"
              disabled={isTweaking || isSaving}
              aria-label="Tell Dayform what changed"
              className="adaptation-input-field"
            />
            <button
              type="submit"
              disabled={!customTweak.trim() || isTweaking || isSaving}
              className="adaptation-submit-btn"
            >
              {isTweaking ? 'Reworking…' : 'Rework'}
            </button>
          </form>
        </StageFrame>
      )}
    </div>
  );
};
