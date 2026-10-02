import React, { useState, useRef, useCallback, useEffect } from 'react';
import { StageFrame } from './components/StageFrame';
import type { StageNumber } from './utils/stages';
import { Navigation } from './components/Navigation';
import { IntentInput } from './components/IntentInput';
import type { IntentInputHandle } from './components/IntentInput';
import { LandingStory } from './components/LandingStory';
import { CapabilitiesSection } from './components/CapabilitiesSection';
import { ProposedPlan } from './components/ProposedPlan';
import type { PlanItemCandidateSelection, PlanConfirmMeta } from './components/ProposedPlan';
import { PlanSummary } from './components/PlanSummary';
import { PlanLibrary } from './components/PlanLibrary';
import { Footer } from './components/Footer';
import {
  createPlanFromIntent,
  getPlan,
  getPlanRecommendations,
  addOptionToPlan,
  proposePlanAdaptation,
  applyPlanAdaptation,
  updatePlan,
} from './api/planning';
import {
  buildProposedItinerary,
  getCategoryIcon,
  buildItemSubtitle,
  parseCandidateCost,
} from './utils/itineraryBuilder';
import type { ProposedItinerary, ProposedItineraryItem } from './utils/itineraryBuilder';
import type { DecisionCandidateRead, InformationCategory, PlanRead, PlanAdaptationRead } from './types/planning';
import { IconAlertCircle, IconX, IconArrowLeft, IconPlus } from './components/Icons';
// The Dayform visual system layers on top of the original stylesheet: the
// shared language first, then the M18 surfaces that use it.
import './styles.css';
import './styles/dayform.css';
import './styles/surfaces.css';
import './styles/cinematic.css';
import './styles/scenes.css';
import './styles/execution.css';

export const App: React.FC = () => {
  const [currentPlan, setCurrentPlan] = useState<PlanRead | null>(null);
  const [candidates, setCandidates] = useState<DecisionCandidateRead[]>([]);
  const [proposedItinerary, setProposedItinerary] = useState<ProposedItinerary | null>(null);
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [submittedIntent, setSubmittedIntent] = useState<string>('');

  const [viewMode, setViewMode] = useState<'landing' | 'workspace' | 'library'>(() => {
    if (typeof window !== 'undefined') {
      if (window.location.pathname === '/library') return 'library';
      if (window.location.pathname === '/workspace') return 'workspace';
    }
    return 'landing';
  });

  const handleSwitchView = useCallback((mode: 'landing' | 'workspace' | 'library') => {
    setViewMode(mode);
    const targetPath = mode === 'library' ? '/library' : mode === 'workspace' ? '/workspace' : '/';
    if (window.location.pathname !== targetPath) {
      window.history.pushState(null, '', targetPath);
    }
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const path = window.location.pathname;
      if (path === '/library') {
        setViewMode('library');
      } else if (path === '/workspace') {
        setViewMode('workspace');
      } else {
        setViewMode('landing');
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const [isAdaptationReview, setIsAdaptationReview] = useState(false);
  const [proposedAdaptation, setProposedAdaptation] = useState<PlanAdaptationRead | null>(null);
  const [lastTweakText, setLastTweakText] = useState('');
  const [previousItinerary, setPreviousItinerary] = useState<ProposedItinerary | null>(null);

  const [isPlanning, setIsPlanning] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isTweaking, setIsTweaking] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const intentInputRef = useRef<IntentInputHandle>(null);
  // The story advances to a named scene rather than to a container, because a
  // container now holds three of them and the reader should be taken to the
  // one that has just been earned.
  const moveToScene = useCallback((stage: StageNumber, delay = 120) => {
    const selector = `.df-scene[data-stage="${String(stage).padStart(2, '0')}"]`;

    const go = () => {
      const scene = document.querySelector(selector);
      if (scene) scene.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    // The scene is usually not in the document yet when a plan resolves, so
    // wait for it rather than scrolling to nothing. Bounded, and it gives up
    // rather than polling forever.
    let attempts = 0;
    const waitForScene = () => {
      if (document.querySelector(selector)) {
        go();
        // A scene that has only just mounted is still growing: the traces and
        // ledgers above it stagger in, which moves the target down the page
        // after we have already scrolled to it. Land again once it has settled,
        // so the payoff is what the reader is actually looking at.
        setTimeout(go, 900);
        return;
      }
      if (attempts < 80) {
        attempts += 1;
        setTimeout(waitForScene, 50);
      }
    };

    setTimeout(waitForScene, delay);
  }, []);

  // Flow Step 1: User submits an intention (with optional origin, startTime, transportPreference)
  const handleIntentSubmit = async (
    intent: string,
    origin?: string,
    startTime?: string,
    transportPreference?: string
  ) => {
    setIsPlanning(true);
    setErrorMessage(null);
    setIsConfirmed(false);
    setProposedItinerary(null);
    setSubmittedIntent(intent);
    handleSwitchView('workspace');

    // Scroll cleanly to the workspace view
    window.scrollTo({ top: 0, behavior: 'smooth' });

    try {
      // 1. Create plan aggregate from intent (POST /api/v1/planning/requests)
      const plan = await createPlanFromIntent(intent, origin, startTime, transportPreference);
      setCurrentPlan(plan);

      // 2. Fetch tailored recommendations (GET /api/v1/planning/plans/{id}/recommendations)
      const recsResponse = await getPlanRecommendations(plan.id);
      const allRecs = recsResponse.candidates || [];
      setCandidates(allRecs);

      // 3. Extract budget ceiling from constraints if present
      const budgetConstraint = plan.constraints?.find((c) => c.type === 'budget_max');
      const budgetMax = budgetConstraint?.numeric_value
        ? parseFloat(String(budgetConstraint.numeric_value))
        : null;

      const groupSize = plan.context?.group_size || 1;

      // 4. Assemble coherent proposed itinerary ("Here's what I'd do")
      const proposal = buildProposedItinerary(allRecs, budgetMax, intent, groupSize, plan.understanding, recsResponse.trade_off_summary);
      setProposedItinerary(proposal);

      // The itinerary is the payoff, so that is where the reader arrives.
      moveToScene(4, 150);
    } catch (err: unknown) {
      console.error('Planning error:', err);
      const msg = err instanceof Error ? err.message : 'Failed to create plan.';
      setErrorMessage(msg);
    } finally {
      setIsPlanning(false);
    }
  };

  // Conversational Plan Modification & Adaptive Planning ("Tweak this plan")
  const handleTweakPlan = async (tweakText: string) => {
    if (!currentPlan) return;
    setIsTweaking(true);
    setErrorMessage(null);

    try {
      // 1. Propose adaptation with minimal change and diffs
      const adaptation = await proposePlanAdaptation(currentPlan.id, tweakText);
      setProposedAdaptation(adaptation);
      setLastTweakText(tweakText);
      setPreviousItinerary(proposedItinerary);

      // 2. Fetch fresh candidates in case new category/location options are needed
      const recsResponse = await getPlanRecommendations(currentPlan.id);
      const allRecs = recsResponse.candidates || [];
      setCandidates(allRecs);

      // 3. Assemble adapted proposed itinerary from diffs
      const adaptedItems: ProposedItineraryItem[] = [];
      const removedItems: Array<{ name: string; reason: string }> = [];

      for (const diff of adaptation.diffs) {
        if (diff.action === 'removed') {
          removedItems.push({
            name: diff.original_name || 'Stop',
            reason: diff.reason,
          });
          continue;
        }

        const candidateName = diff.new_name || diff.original_name || 'Stop';
        const candidateCategory: InformationCategory = (diff.item_type === 'food' ? 'food' : 'culture');
        const matchingCand: DecisionCandidateRead = allRecs.find(
          (c) => c.option_id === diff.candidate_option_id || c.name.toLowerCase() === candidateName.toLowerCase()
        ) || {
          option_id: diff.candidate_option_id || diff.original_item_id || 'opt-' + Math.random(),
          option_type: 'place' as const,
          name: candidateName,
          is_eligible: true,
          score: 90,
          reasons: [],
          category: candidateCategory,
          cost: diff.new_cost !== undefined && diff.new_cost !== null ? String(diff.new_cost) : null,
          duration_minutes: 60,
          location: diff.location || null,
          source: 'fixture',
        };

        const itemStart = diff.new_start_time ? diff.new_start_time.substring(11, 16) : undefined;
        const itemEnd = diff.new_end_time ? diff.new_end_time.substring(11, 16) : undefined;

        adaptedItems.push({
          candidate: matchingCand,
          icon: getCategoryIcon(matchingCand.category),
          subtitle: buildItemSubtitle(matchingCand),
          costNumber: parseCandidateCost(diff.new_cost ?? matchingCand.cost),
          rationale: [diff.reason],
          startTime: itemStart,
          endTime: itemEnd,
          action: diff.action,
          changeReason: diff.reason,
          originalName: diff.original_name || undefined,
        });
      }

      const budgetConstraint = currentPlan.constraints?.find((c) => c.type === 'budget_max');
      const budgetMax = budgetConstraint?.numeric_value
        ? parseFloat(String(budgetConstraint.numeric_value))
        : null;

      const adaptedProposal: ProposedItinerary = {
        items: adaptedItems,
        alternatives: allRecs.filter((c) => !adaptedItems.some((ai) => ai.candidate.name.toLowerCase() === c.name.toLowerCase())),
        estimatedTotal: parseFloat(String(adaptation.new_total_cost || 0)),
        remainingBudget: budgetMax ? budgetMax - parseFloat(String(adaptation.new_total_cost || 0)) : null,
        isOverBudget: budgetMax ? parseFloat(String(adaptation.new_total_cost || 0)) > budgetMax : false,
        narrativeSubheading: adaptation.narrative_summary,
        adaptationSummary: adaptation.narrative_summary,
        isAdaptationProposal: true,
        removedItems,
        attribution: proposedItinerary?.attribution,
        freshness: proposedItinerary?.freshness,
      };

      setProposedItinerary(adaptedProposal);
      setIsAdaptationReview(true);
      setIsConfirmed(false);

      moveToScene(4, 100);
    } catch (err: unknown) {
      console.error('Error adapting plan:', err);
      const msg = err instanceof Error ? err.message : 'Failed to adapt plan.';
      setErrorMessage(msg);
    } finally {
      setIsTweaking(false);
    }
  };

  // Flow: User accepts the proposed adaptation
  const handleAcceptAdaptation = async () => {
    if (!currentPlan || !lastTweakText) return;
    setIsSaving(true);
    setErrorMessage(null);

    try {
      const updatedPlan = await applyPlanAdaptation(currentPlan.id, lastTweakText);
      setCurrentPlan(updatedPlan);
      setIsAdaptationReview(false);
      setProposedAdaptation(null);
      setIsConfirmed(true);
      moveToScene(6, 100);
    } catch (err: unknown) {
      console.error('Error applying adaptation:', err);
      const msg = err instanceof Error ? err.message : 'Failed to apply changes.';
      setErrorMessage(msg);
    } finally {
      setIsSaving(false);
    }
  };

  // Flow: User keeps existing plan (rejects adaptation proposal)
  const handleRejectAdaptation = () => {
    if (previousItinerary) {
      setProposedItinerary(previousItinerary);
    }
    setIsAdaptationReview(false);
    setProposedAdaptation(null);
    if (currentPlan && currentPlan.items.length > 0) {
      setIsConfirmed(true);
    }
  };

  // Flow Step 2: User confirms the proposed itinerary ("Looks good")
  const handleConfirmPlan = async (
    selectedCandidates: DecisionCandidateRead[],
    scheduledItems?: PlanItemCandidateSelection[],
    meta?: PlanConfirmMeta,
    customTitle?: string
  ) => {
    if (!currentPlan) return;

    setIsSaving(true);
    setErrorMessage(null);

    try {
      if (customTitle && customTitle.trim() && customTitle.trim() !== currentPlan.title) {
        try {
          await updatePlan(currentPlan.id, {
            title: customTitle.trim(),
          });
        } catch (titleErr) {
          console.warn('Failed to persist custom title:', titleErr);
        }
      }

      if (meta?.origin || meta?.transportPreference) {
        try {
          await updatePlan(currentPlan.id, {
            context: {
              origin: meta.origin || undefined,
              transport_mode: meta.transportPreference || undefined,
            },
          });
        } catch (ctxErr) {
          console.warn('Failed to persist origin/transport preference to plan context:', ctxErr);
        }
      }
      if (scheduledItems && scheduledItems.length > 0) {
        for (const item of scheduledItems) {
          await addOptionToPlan(
            currentPlan.id,
            item.candidate,
            item.position,
            item.startTime,
            item.endTime
          );
        }
      } else {
        // Persist each selected candidate to the authoritative backend plan
        for (const candidate of selectedCandidates) {
          await addOptionToPlan(currentPlan.id, candidate);
        }
      }

      // Refresh plan from database (GET /api/v1/planning/plans/{plan_id})
      const refreshed = await getPlan(currentPlan.id);
      setCurrentPlan(refreshed);
      setIsConfirmed(true);

      // The saved day is the last scene; go there rather than to the top.
      moveToScene(6, 100);
    } catch (err: unknown) {
      console.error('Error confirming plan:', err);
      const msg = err instanceof Error ? err.message : 'Failed to save plan.';
      setErrorMessage(msg);
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenSavedPlan = async (planId: string) => {
    setIsPlanning(true);
    setErrorMessage(null);
    try {
      const plan = await getPlan(planId);
      setCurrentPlan(plan);
      setSubmittedIntent(plan.intention || plan.title || 'Saved plan');

      const recsResponse = await getPlanRecommendations(plan.id);
      const allRecs = recsResponse.candidates || [];
      setCandidates(allRecs);

      const budgetConstraint = plan.constraints?.find((c) => c.type === 'budget_max');
      const budgetMax = budgetConstraint?.numeric_value
        ? parseFloat(String(budgetConstraint.numeric_value))
        : null;
      const groupSize = plan.context?.group_size || 1;

      const proposal = buildProposedItinerary(
        allRecs,
        budgetMax,
        plan.intention,
        groupSize,
        plan.understanding,
        recsResponse.trade_off_summary
      );
      setProposedItinerary(proposal);

      if (plan.items && plan.items.length > 0) {
        setIsConfirmed(true);
      } else {
        setIsConfirmed(false);
      }

      handleSwitchView('workspace');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      console.error('Failed to open saved plan:', err);
      setErrorMessage('Could not open the selected plan.');
    } finally {
      setIsPlanning(false);
    }
  };

  const handleStartNew = () => {
    setCurrentPlan(null);
    setProposedItinerary(null);
    setCandidates([]);
    setIsConfirmed(false);
    setIsAdaptationReview(false);
    setProposedAdaptation(null);
    setErrorMessage(null);
    setSubmittedIntent('');
    handleSwitchView('landing');
    intentInputRef.current?.reset?.();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleFocusHeroInput = () => {
    if (viewMode !== 'landing') {
      handleSwitchView('landing');
      setTimeout(() => {
        intentInputRef.current?.focus();
      }, 100);
    } else {
      intentInputRef.current?.focus();
    }
  };

  const budgetConstraint = currentPlan?.constraints?.find((c) => c.type === 'budget_max');
  const budgetMax = budgetConstraint?.numeric_value
    ? parseFloat(String(budgetConstraint.numeric_value))
    : null;

  const hasActivePlan = Boolean(currentPlan || isPlanning);



  return (
    <div className={`product-canvas ${viewMode === 'workspace' ? 'workspace-canvas' : ''}`}>
      {/* Decorative ambient emoji layer removed for clean editorial presentation */}

      {/* The running folio: six scenes, always in the same order.

          It stays out of the way on the landing screen, which already tells the
          same six-stage story in the user's own words. The folio is for people
          who are actually inside the day — it appears the moment the story
          starts, and from then on it is the only place the six stages are named,
      {/* The running folio (StageRail) omitted from workspace to preserve focused consumer UX */}

      {/* Top Floating Navigation */}
      <Navigation
        hasActivePlan={hasActivePlan}
        isPlanning={isPlanning}
        onNewPlan={handleStartNew}
        onFocusInput={handleFocusHeroInput}
        viewMode={viewMode}
        onSwitchView={handleSwitchView}
      />

      {/* Main Experience Flow */}
      <main className="product-main">
        {/* Error Notification Toast */}
        {errorMessage && (
          <div className="editorial-error-toast" role="alert">
            <div className="error-toast-content">
              <IconAlertCircle size={18} className="error-toast-icon" />
              <span>{errorMessage}</span>
            </div>
            <button
              type="button"
              className="error-toast-close"
              onClick={() => setErrorMessage(null)}
              aria-label="Dismiss error"
            >
              <IconX size={15} />
            </button>
          </div>
        )}

        {/* =========================================================================
            VIEW MODE 1: CINEMATIC LANDING EXPERIENCE
            ========================================================================= */}
        {viewMode === 'landing' && (
          <div className="landing-view-container">
            {/* Active Plan Resumption Banner (if user navigated to overview while a plan is active) */}
            {hasActivePlan && (
              <div className="landing-banner-wrap">
                <div className="active-plan-banner" onClick={() => handleSwitchView('workspace')}>
                  <div className="active-plan-banner-text">
                    <span className="live-status-dot" />
                    <span>You have an active plan in progress: <strong>“{submittedIntent}”</strong></span>
                  </div>
                  <button type="button" className="active-plan-banner-btn">
                    <span>Resume plan</span>
                    <span className="banner-arrow">→</span>
                  </button>
                </div>
              </div>
            )}

            {/* Cinematic Hero & Command Surface */}
            <IntentInput
              ref={intentInputRef}
              onSubmit={handleIntentSubmit}
              isLoading={isPlanning}
            />

            {/* Sticky Scroll Storytelling Section (6 Chapters) */}
            <LandingStory onStartPlanning={handleFocusHeroInput} />

            {/* Engine Architecture & Capabilities Grid */}
            <CapabilitiesSection onStartPlanning={handleFocusHeroInput} />
          </div>
        )}

        {/* =========================================================================
            VIEW MODE 2: FOCUSED PLANNING WORKSPACE
            ========================================================================= */}
        {viewMode === 'workspace' && (
          <div className="workspace-view-container animate-fade-in">
            {/* The intention stays on screen for the whole workspace, because
                every scene below is an answer to it. It is held at the meta
                scale so it informs without competing. */}
            <div className="workspace-top-bar df-workspace-margin">
              <button
                type="button"
                className="workspace-back-btn"
                onClick={() => handleSwitchView('landing')}
                title="Back to the beginning"
              >
                <IconArrowLeft size={15} />
                <span>Back</span>
              </button>

              <p className="workspace-intent-display">
                <span className="intent-display-text" title={submittedIntent}>
                  “{submittedIntent}”
                </span>
              </p>

              <button
                type="button"
                className="workspace-new-plan-btn"
                onClick={handleStartNew}
                title="Start a new plan from scratch"
              >
                <IconPlus size={14} />
                <span>New plan</span>
              </button>
            </div>

            {/* Assembling / Thinking State (Phase 9) */}
            {/* Scene 03, while it is happening. The steps named here are the
                ones the engine is genuinely running, in the order it runs them,
                so this is a caption on real work rather than a reassuring
                animation. Nothing is claimed that is not about to be shown. */}
            {isPlanning && (
              <StageFrame
                stage={3}
                className="df-thinking-scene"
                title="One moment."
                lede="Reading what you actually meant, then checking it against what is really open, really there, and really within reach."
              >
                <ol className="df-thinking-steps">
                  {[
                    { n: '01', t: 'Reading the intention', d: 'Pulling out the time, the place, the people, the money and the mood.' },
                    { n: '02', t: 'Finding real places', d: 'Searching what is genuinely nearby and genuinely open.' },
                    { n: '03', t: 'Checking them against you', d: 'Hours, area, budget and what you asked for, one by one.' },
                    { n: '04', t: 'Putting them in order', d: 'Working out the travel between each one, then building the day around it.' },
                  ].map((step) => (
                    <li key={step.n} className="df-thinking-step">
                      <span className="df-thinking-step-n">{step.n}</span>
                      <span className="df-thinking-step-body">
                        <span className="df-thinking-step-t">{step.t}</span>
                        <span className="df-thinking-step-d">{step.d}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              </StageFrame>
            )}

            {/* Error Recovery State in Workspace (Phase 9) */}
            {!isPlanning && errorMessage && !currentPlan && (
              <div className="workspace-error-state animate-fade-in">
                <div className="error-icon-box">
                  <IconAlertCircle size={28} />
                </div>
                <h3 className="error-title">Couldn’t give shape to this plan</h3>
                <p className="error-subtitle">{errorMessage}</p>
                <button
                  type="button"
                  className="btn-editorial-primary"
                  onClick={handleStartNew}
                >
                  <span>Try another intention</span>
                </button>
              </div>
            )}

            {/* Proposed Plan Stage */}
            {!isPlanning && currentPlan && proposedItinerary && !isConfirmed && (
              <div className="proposal-stage-container animate-fade-in">
                <ProposedPlan
                  key={`${currentPlan.id}-${currentPlan.updated_at || ''}-${proposedItinerary.estimatedTotal}-${isAdaptationReview ? 'review' : 'normal'}`}
                  plan={currentPlan}
                  initialItinerary={proposedItinerary}
                  allCandidates={candidates}
                  budgetMax={budgetMax}
                  onConfirm={handleConfirmPlan}
                  isSaving={isSaving}
                  onModifyIntent={handleStartNew}
                  onTweakPlan={handleTweakPlan}
                  isTweaking={isTweaking}
                  isAdaptationReview={isAdaptationReview}
                  adaptationSummary={proposedAdaptation?.narrative_summary}
                  onAcceptAdaptation={handleAcceptAdaptation}
                  onRejectAdaptation={handleRejectAdaptation}
                />
              </div>
            )}

            {/* Confirmed / Saved Plan Stage */}
            {!isPlanning && currentPlan && isConfirmed && (
              <div className="saved-stage-container animate-fade-in">
                <PlanSummary
                  plan={currentPlan}
                  onStartNew={handleStartNew}
                  onTweakPlan={handleTweakPlan}
                  isTweaking={isTweaking}
                />
              </div>
            )}

          </div>
        )}

        {/* =========================================================================
            VIEW MODE 3: PLAN LIBRARY
            ========================================================================= */}
        {viewMode === 'library' && (
          <div className="library-view-container animate-fade-in">
            <PlanLibrary
              onOpenPlan={handleOpenSavedPlan}
              onNewPlan={handleStartNew}
            />
          </div>
        )}
      </main>

      {/* Edge-to-Edge Solid Black Editorial Footer */}
      <Footer
        onStartPlanning={viewMode === 'landing' ? handleFocusHeroInput : handleStartNew}
        onOpenLibrary={() => handleSwitchView('library')}
      />
    </div>
  );
};

export default App;
