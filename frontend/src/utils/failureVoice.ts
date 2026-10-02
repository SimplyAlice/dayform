import type { DecisionCandidateRead, PlanRead } from '../types/planning';
import { knownCandidateCost } from './itineraryBuilder.ts';

export interface FailureDetails {
  headline: string;
  explanation: string;
  recoveryActions: Array<{
    label: string;
    onClick: () => void;
    primary?: boolean;
  }>;
}

/**
 * Derives truthful, consumer-facing failure diagnosis and actionable recovery options
 * when a plan cannot be created with verified candidates.
 */
export function deriveFailureDetails(
  plan: PlanRead,
  candidates: DecisionCandidateRead[],
  budgetMax: number | null,
  onTweakPlan?: (tweak: string) => Promise<void>,
  onModifyIntent?: () => void
): FailureDetails {
  const intentLower = (plan.intention || '').toLowerCase();
  const reqs = plan.understanding?.experience_requirements || [];
  const activityTypes = plan.understanding?.activity_types || [];
  const location = plan.understanding?.location;
  const rawArea = location && !plan.understanding?.location_is_inferred &&
    !/^(cape town|town|city)$/i.test(location.trim()) ? location : null;
  const explicitActivity = /\b(dinner|lunch|breakfast|brunch|coffee|cafe|café)\b/.exec(intentLower)?.[1];
  const activityWord = explicitActivity === 'cafe' || explicitActivity === 'café'
    ? 'coffee stop'
    : explicitActivity || (reqs.includes('meal') || activityTypes.includes('food') ? 'meal' : 'day');
  const isLunch = activityWord === 'lunch';
  const isMealRequest = activityWord === 'dinner' || isLunch || activityWord === 'breakfast' ||
    activityWord === 'brunch' || activityWord === 'meal';
  const headline = activityWord === 'day'
    ? "I couldn't make this day work yet."
    : `I couldn't make that ${activityWord} work.`;

  const area = rawArea || 'the area';
  const areaWithArticle = area.toLowerCase().startsWith('the ') ? area : `the ${area}`;

  const foodCandidates = candidates.filter((c) => c.category === 'food');

  let explanation = `I checked verified places in ${areaWithArticle}, but couldn't find options fitting all your requirements.`;
  const recoveryActions: FailureDetails['recoveryActions'] = [];

  // Check if we found candidates in the area, but the only food option(s) exceed budget
  const hasFoodOverBudget =
    foodCandidates.length > 0 &&
    budgetMax !== null &&
    foodCandidates.every((c) => {
      const cost = knownCandidateCost(c.cost);
      return cost !== null && cost > budgetMax;
    });

  const hasOpeningHoursBlock = foodCandidates.length > 0 && foodCandidates.every((candidate) =>
    candidate.reasons.some((reason) =>
      (reason.type === 'opening_hours' || reason.type === 'time_window') && reason.outcome === 'violated'
    )
  );
  const provenance = plan.understanding?.provenance || {};
  const statedTimePhrase = /\b(?:after|before|at|around|from|until|by)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b/i.exec(plan.intention || '')?.[0].trim();
  const hasExplicitTime = Boolean(statedTimePhrase) ||
    provenance.start_time === 'explicit' || provenance.end_time === 'explicit';

  if (hasFoodOverBudget && budgetMax !== null) {
    explanation = `I found places in ${areaWithArticle}, but the only ${activityWord} option I could verify is above your R${Math.round(budgetMax)} budget.`;

    // Action 1: Widen the area
    recoveryActions.push({
      label: 'Widen the area',
      primary: true,
      onClick: () => {
        onTweakPlan?.(`Widen the area across Cape Town to find ${activityWord} under R${Math.round(budgetMax)}`);
      },
    });

    // Action 2: Raise the budget (neutral, not pushing a specific amount)
    recoveryActions.push({
      label: 'Raise the budget',
      primary: false,
      onClick: () => {
        onTweakPlan?.(`Raise the budget for ${activityWord} in ${areaWithArticle}`);
      },
    });

    // Action 3: Try another spot
    recoveryActions.push({
      label: 'Try another spot',
      primary: false,
      onClick: () => {
        onModifyIntent?.();
      },
    });
  } else if (hasOpeningHoursBlock && isMealRequest) {
    explanation = `I found ${activityWord} options in ${areaWithArticle}, but none is open during the time you asked for.`;

    recoveryActions.push({
      label: 'Change the time',
      primary: true,
      onClick: () => onTweakPlan?.(`Try ${activityWord} at a different time that fits verified opening hours`),
    });
    recoveryActions.push({
      label: 'Widen the area',
      primary: false,
      onClick: () => onTweakPlan?.(`Widen the area across Cape Town to find ${activityWord}`),
    });
    recoveryActions.push({
      label: 'Try another spot',
      primary: false,
      onClick: () => onModifyIntent?.(),
    });
  } else if (candidates.length > 0 && foodCandidates.length === 0 && isMealRequest) {
    explanation = `I found places in ${areaWithArticle}, but none offering verified ${activityWord} options.`;

    recoveryActions.push({
      label: 'Widen the area',
      primary: true,
      onClick: () => {
        onTweakPlan?.(`Widen the area across Cape Town to find ${activityWord}`);
      },
    });
    recoveryActions.push({
      label: 'Try another spot',
      primary: false,
      onClick: () => {
        onModifyIntent?.();
      },
    });
  } else if (candidates.length === 0) {
    explanation = `I couldn't find verified places in ${areaWithArticle} matching what you asked for.`;

    recoveryActions.push({
      label: 'Widen the area',
      primary: true,
      onClick: () => {
        onTweakPlan?.(`Widen the search area across Cape Town`);
      },
    });
    recoveryActions.push({
      label: 'Try another spot',
      primary: false,
      onClick: () => {
        onModifyIntent?.();
      },
    });
  } else {
    // General fallback
    recoveryActions.push({
      label: 'Widen the area',
      primary: true,
      onClick: () => {
        onTweakPlan?.(`Widen the search area`);
      },
    });
    if (budgetMax) {
      recoveryActions.push({
        label: 'Raise the budget',
        primary: false,
        onClick: () => {
          onTweakPlan?.(`Raise the budget to expand available options`);
        },
      });
    }
    recoveryActions.push({
      label: 'Try another spot',
      primary: false,
      onClick: () => {
        onModifyIntent?.();
      },
    });
  }

  if (hasExplicitTime && !recoveryActions.some((action) => action.label === 'Change the time')) {
    recoveryActions.push({
      label: 'Change the time',
      primary: false,
      onClick: () => onTweakPlan?.(`Try this plan at a different time while keeping your area and budget`),
    });
  }

  if (hasExplicitTime && statedTimePhrase && budgetMax !== null && isMealRequest) {
    explanation = `I couldn't verify a ${activityWord} in ${areaWithArticle} that fits ${statedTimePhrase} and stays within your R${Math.round(budgetMax)} budget.`;
  }

  return { headline, explanation, recoveryActions };
}
