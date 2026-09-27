import type {
  DecisionCandidateRead,
  InformationCategory,
  PlanTransitionRead,
  UnderstandingRead,
} from '../types/planning';

export interface ProposedItineraryItem {
  candidate: DecisionCandidateRead;
  icon: string;
  subtitle: string;
  costNumber: number;
  rationale: string[];
  startTime?: string;
  endTime?: string;
  durationMinutes?: number;
  isApproximate?: boolean;
  action?: 'kept' | 'replaced' | 'removed' | 'rescheduled' | 'added';
  changeReason?: string;
  originalName?: string;
}

export interface ProposedItinerary {
  items: ProposedItineraryItem[];
  alternatives: DecisionCandidateRead[];
  estimatedTotal: number;
  remainingBudget: number | null;
  isOverBudget: boolean;
  narrativeSubheading: string;
  attribution?: string | null;
  freshness?: string | null;
  totalDurationMinutes?: number;
  timeSpanDisplay?: string;
  adaptationSummary?: string;
  isAdaptationProposal?: boolean;
  tradeOffSummary?: string | null;
  removedItems?: Array<{ name: string; reason: string }>;
}

/**
 * Category icons for consumer editorial feel.
 */
export const CATEGORY_ICONS: Record<InformationCategory | string, string> = {
  nature: 'Nature',
  culture: 'Culture',
  food: 'Dining',
  entertainment: 'Entertainment',
  wellness: 'Wellness',
  shopping: 'Shopping',
};

export function getCategoryIcon(category: string): string {
  return CATEGORY_ICONS[category.toLowerCase()] || 'Place';
}

/**
 * Parses numeric cost from string/number safely.
 */
export function parseCandidateCost(cost: string | number | null | undefined): number {
  if (cost === null || cost === undefined) return 0;
  if (typeof cost === 'number') return cost;
  const parsed = parseFloat(cost);
  return isNaN(parsed) ? 0 : parsed;
}

/**
 * Formats a clean subtitle for an itinerary card.
 */
export function buildItemSubtitle(candidate: DecisionCandidateRead): string {
  const parts: string[] = [];

  const categoryName = candidate.category.charAt(0).toUpperCase() + candidate.category.slice(1);
  parts.push(categoryName);

  if (candidate.duration_minutes) {
    parts.push(`${candidate.duration_minutes}m`);
  } else if (candidate.option_type === 'place') {
    parts.push('Flexible time');
  }

  // Location / address
  if (candidate.address) {
    const segments = candidate.address.split(',').map((s) => s.trim());
    if (segments.length >= 2) {
      parts.push(`${segments[0]}, ${segments[1]}`);
    } else {
      parts.push(segments[0]);
    }
  } else if (candidate.location) {
    parts.push(candidate.location);
  }

  return parts.join(' · ');
}

/**
 * Formats currency in South African Rands or Free or Price not listed.
 */
export function formatCurrency(amount: number | string | null | undefined): string {
  if (amount === null || amount === undefined) return 'Price not listed';
  const num = typeof amount === 'number' ? amount : parseFloat(amount);
  if (isNaN(num)) return 'Price not listed';
  if (num === 0) return 'Free';
  return `R${num.toFixed(0)}`;
}

/**
 * Time calculation and slotting helpers.
 */
export function parseTimeToMinutes(timeStr: string): number {
  const parts = timeStr.split(':').map((s) => parseInt(s, 10));
  return (parts[0] || 0) * 60 + (parts[1] || 0);
}

export function formatMinutesToTime(totalMins: number): string {
  const norm = ((totalMins % 1440) + 1440) % 1440;
  const h = Math.floor(norm / 60);
  const m = norm % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function getBaseStartTimeMinutes(understanding?: UnderstandingRead | null): { minutes: number; isApproximate: boolean } {
  if (understanding?.start_time) {
    return {
      minutes: parseTimeToMinutes(understanding.start_time),
      isApproximate: understanding.time_confidence === 'approximate',
    };
  }
  if (understanding?.time_window) {
    const win = understanding.time_window.toLowerCase();
    if (win === 'morning') return { minutes: 9 * 60 + 30, isApproximate: true };
    if (win === 'lunch' || win === 'noon') return { minutes: 12 * 60, isApproximate: true };
    if (win === 'afternoon') return { minutes: 13 * 60 + 30, isApproximate: true };
    if (win === 'evening') return { minutes: 18 * 60, isApproximate: true };
    if (win === 'night') return { minutes: 20 * 60, isApproximate: true };
  }
  return { minutes: 11 * 60, isApproximate: true };
}

/**
 * Resolve the address a mobility provider can geocode for a proposed stop.
 */
export function resolveStopLocation(item: ProposedItineraryItem): string | null {
  const raw = item.candidate.address || item.candidate.location;
  if (!raw) return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Locate the mobility transition joining two consecutive proposed stops, if one exists.
 */
export function findTransitionBetween(
  from: ProposedItineraryItem,
  to: ProposedItineraryItem | undefined,
  transitions: PlanTransitionRead[]
): PlanTransitionRead | null {
  if (!to) return null;
  const fromLoc = resolveStopLocation(from);
  const toLoc = resolveStopLocation(to);
  if (!fromLoc || !toLoc) return null;
  return (
    transitions.find(
      (t) =>
        t.from_location?.trim().toLowerCase() === fromLoc.toLowerCase() &&
        t.to_location?.trim().toLowerCase() === toLoc.toLowerCase()
    ) || null
  );
}

/**
 * Per-leg travel minutes taken from the actual M15 transitions.
 *
 * A leg whose duration is unknown contributes 0 minutes rather than a guessed
 * buffer, so the schedule never invents transport time. Those legs also stay
 * flagged by M15 feasibility, which reports the missing window truthfully.
 */
export function travelMinutesForItems(
  items: ProposedItineraryItem[],
  transitions: PlanTransitionRead[]
): number[] {
  return items.slice(0, -1).map((item, idx) => {
    const transition = findTransitionBetween(item, items[idx + 1], transitions);
    return transition?.duration_minutes ?? 0;
  });
}

export function assignTimeSlots(
  items: ProposedItineraryItem[],
  understanding?: UnderstandingRead | null,
  travelMinutes: number[] = []
): ProposedItineraryItem[] {
  if (items.length === 0) return [];
  const base = getBaseStartTimeMinutes(understanding);
  let currentCursor = base.minutes;

  return items.map((item, idx) => {
    const dur = item.candidate.duration_minutes || (item.candidate.option_type === 'place' ? 90 : 60);
    const startStr = formatMinutesToTime(currentCursor);
    const endCursor = currentCursor + dur;
    const endStr = formatMinutesToTime(endCursor);
    // The next stop begins only after the activity AND the travel leg complete.
    currentCursor = endCursor + (travelMinutes[idx] ?? 0);

    return {
      ...item,
      startTime: startStr,
      endTime: endStr,
      durationMinutes: dur,
      isApproximate: base.isApproximate,
    };
  });
}

/**
 * Humanizes backend machine decision reasons into warm, conversational explanations.
 * Eliminates machine scores, internal IDs, and technical provenance.
 */
export function humanizeCandidateReasons(
  candidate: DecisionCandidateRead,
  budgetMax: number | null,
  groupSize: number = 1,
  understanding?: UnderstandingRead | null
): string[] {
  const humanReasons: string[] = [];
  const cost = parseCandidateCost(candidate.cost);

  // 1. Budget rationale (warm, consumer wording)
  if (candidate.cost === null || candidate.cost === undefined) {
    humanReasons.push('Menu or admission prices vary by choice.');
  } else if (cost === 0) {
    humanReasons.push('Free to enjoy — zero impact on your budget.');
  } else if (budgetMax !== null && cost <= budgetMax) {
    humanReasons.push(`Fits comfortably within your ${formatCurrency(budgetMax)} budget.`);
  }

  // 2. Real opening hours & temporal rationale from decision engine (filter out robotic weather/rules text)
  if (candidate.reasons) {
    for (const r of candidate.reasons) {
      if (r.type === 'opening_hours' && r.outcome === 'supported' && r.message) {
        // Only include if not robotic
        if (!r.message.toLowerCase().includes('weather forecast') && !r.message.toLowerCase().includes('indoor venue')) {
          humanReasons.push(r.message);
        }
      } else if (r.type === 'time_window' && r.outcome === 'supported' && r.message) {
        if (!r.message.toLowerCase().includes('weather forecast')) {
          humanReasons.push(r.message);
        }
      }
    }
  }

  // 3. Occasion rationale
  if (understanding?.occasion === 'date') {
    const guests = understanding.people_count ?? 2;
    humanReasons.push(
      guests === 2
        ? 'Romantic and relaxed atmosphere for two.'
        : `Romantic and relaxed atmosphere for your group of ${guests}.`
    );
  } else if (understanding?.occasion === 'birthday') {
    humanReasons.push('A celebratory setting well suited for a special occasion.');
  } else if (understanding?.occasion === 'friends') {
    humanReasons.push('Lively, easygoing setting for a group of friends.');
  }

  // 4. Group suitability
  if (groupSize > 1 && !humanReasons.some((h) => h.includes('group'))) {
    humanReasons.push(`Comfortable table space and flow for ${groupSize} guests.`);
  }

  // 5. Category context
  if (candidate.category === 'nature' && !humanReasons.some((h) => h.includes('scenic') || h.includes('outdoor'))) {
    humanReasons.push('Scenic, open-air setting to take in the surroundings.');
  } else if (candidate.category === 'culture' && !humanReasons.some((h) => h.includes('cultural'))) {
    humanReasons.push('Adds a rich cultural highlight to your day.');
  } else if (candidate.category === 'food' && !humanReasons.some((h) => h.includes('food') || h.includes('cuisine') || h.includes('dinner'))) {
    humanReasons.push('Standout local kitchen known for memorable food and hospitality.');
  }

  // Fallback to any positive message from backend reasons if filtered list is small
  if (candidate.reasons) {
    for (const r of candidate.reasons) {
      if (r.outcome === 'supported' && r.message) {
        const cleanMsg = r.message.replace(/R0\.00/g, 'R0');
        const lower = cleanMsg.toLowerCase();
        // Strict filter against robotic internal text
        if (
          !lower.includes('weather forecast') &&
          !lower.includes('indoor venue') &&
          !lower.includes('budget constraint met') &&
          !lower.includes('score') &&
          !humanReasons.includes(cleanMsg)
        ) {
          humanReasons.push(cleanMsg);
        }
      }
    }
  }

  return humanReasons.slice(0, 2);
}

/**
 * Calculates trade-off note when comparing an alternative candidate to a current slot.
 */
export function getTradeOffNote(
  altCandidate: DecisionCandidateRead,
  currentCandidate?: DecisionCandidateRead
): string {
  const altCost = parseCandidateCost(altCandidate.cost);
  if (!currentCandidate) {
    return formatCurrency(altCost);
  }

  const currentCost = parseCandidateCost(currentCandidate.cost);
  const diff = altCost - currentCost;

  if (diff < 0) {
    return `Saves ${formatCurrency(Math.abs(diff))}`;
  } else if (diff > 0) {
    return `+${formatCurrency(diff)} more`;
  }
  return `Same cost (${formatCurrency(altCost)})`;
}

/**
 * Builds a natural, conversational narrative subheading for the proposed plan.
 */
export function buildProposalNarrative(
  items: ProposedItineraryItem[],
  _budgetMax: number | null,
  remainingBudget: number | null,
  understanding?: UnderstandingRead | null
): string {
  const categories = new Set(items.map((i) => i.candidate.category));
  const guests = understanding?.people_count ?? 2;
  // Copy must follow the extracted group size, not a fixed couple.
  const couplePhrase = guests === 2 ? 'the two of you' : `all ${guests} of you`;

  if (understanding?.duration_limit_minutes) {
    const hours = Math.round(understanding.duration_limit_minutes / 60);
    const hrsStr = hours === 1 ? '1-hour' : `${hours}-hour`;
    if (understanding.occasion === 'date') {
      return `A focused ${hrsStr} date outing tailored for ${couplePhrase}.`;
    }
    if (understanding.occasion === 'birthday') {
      return `A celebratory ${hrsStr} birthday plan tailored to your time limit.`;
    }
    if (understanding.occasion === 'friends') {
      return `A fun ${hrsStr} plan for your group, perfectly sized for your time.`;
    }
    return `A concise ${hrsStr} sequence designed to fit your exact time window.`;
  }

  if (understanding?.occasion === 'date') {
    if (remainingBudget !== null && remainingBudget > 0) {
      return `A romantic outing designed for ${couplePhrase}, with ${formatCurrency(remainingBudget)} left to spare.`;
    }
    return `A relaxed, memorable date outing tailored for ${couplePhrase}.`;
  }

  if (understanding?.occasion === 'birthday') {
    const forWho = understanding.relationship_context ? ` for your ${understanding.relationship_context}` : '';
    if (remainingBudget !== null && remainingBudget > 0) {
      return `A celebratory birthday plan${forWho}, with ${formatCurrency(remainingBudget)} left to spare.`;
    }
    return `A thoughtful birthday celebration${forWho} tailored to what you asked for.`;
  }

  if (understanding?.occasion === 'friends') {
    const countStr = understanding.people_count ? `the ${understanding.people_count} of you` : 'your group';
    if (remainingBudget !== null && remainingBudget > 0) {
      return `A fun outing for ${countStr}, with ${formatCurrency(remainingBudget)} left in your budget.`;
    }
    return `A fun group plan tailored for ${countStr}.`;
  }

  if (categories.has('food') && (categories.has('nature') || categories.has('culture'))) {
    if (remainingBudget !== null && remainingBudget > 0) {
      return `A balanced plan with something fun to do, good food, and ${formatCurrency(remainingBudget)} left in your budget.`;
    }
    return 'A balanced plan with something fun to do and great food.';
  }

  if (categories.has('food')) {
    return 'A delicious, food-forward experience tailored to your group.';
  }

  if (categories.has('culture') || categories.has('nature')) {
    return 'A scenic, engaging day out designed to match your pace.';
  }

  return 'A thoughtful sequence designed to make the most of your time and budget.';
}


/**
 * Assembles a coherent proposed itinerary from ranked recommendation candidates.
 *
 * Understanding-aware and constraint-respecting:
 * - Strictly filters out candidates violating exclusions (e.g. no outdoor, not fancy).
 * - Prioritizes requested themes (food, outdoors, culture, date) when present.
 * - Otherwise builds a varied, non-repetitive sequence across categories.
 * - Strictly enforces budget limits.
 */
export function buildProposedItinerary(
  candidates: DecisionCandidateRead[],
  budgetMax: number | null,
  _intentText: string = '',
  groupSize: number = 1,
  understanding?: UnderstandingRead | null,
  tradeOffSummary?: string | null
): ProposedItinerary {
  let eligible = candidates.filter((c) => c.is_eligible);

  // Client-side safety filter against exclusions
  if (understanding?.exclusions && understanding.exclusions.length > 0) {
    if (understanding.exclusions.includes('no_outdoors')) {
      eligible = eligible.filter((c) => c.category !== 'nature');
    }
    if (understanding.exclusions.includes('no_alcohol') || understanding.exclusions.includes('no_loud_bars')) {
      eligible = eligible.filter((c) => {
        const nameLower = c.name.toLowerCase();
        return !nameLower.includes('bar') && !nameLower.includes('cocktail') && !nameLower.includes('pub') && !nameLower.includes('brewery');
      });
    }
    if (understanding.exclusions.includes('not_too_fancy')) {
      eligible = eligible.filter((c) => {
        const cost = parseCandidateCost(c.cost);
        const nameLower = c.name.toLowerCase();
        return cost < 400 && !nameLower.includes('fine dining') && !nameLower.includes('luxury');
      });
    }
  }

  if (eligible.length === 0) {
    return {
      items: [],
      alternatives: [],
      estimatedTotal: 0,
      remainingBudget: budgetMax,
      isOverBudget: false,
      narrativeSubheading: tradeOffSummary || 'Explore options to build your plan.',
      tradeOffSummary: tradeOffSummary || null,
    };
  }

  const durationLimit = understanding?.duration_limit_minutes || null;
  const deadlineMins = understanding?.end_time ? parseTimeToMinutes(understanding.end_time) : null;
  const baseStart = getBaseStartTimeMinutes(understanding).minutes;

  const selectedCandidates: DecisionCandidateRead[] = [];
  const selectedOptionIds = new Set<string>();
  const selectedCategories = new Set<string>();
  let currentCost = 0;
  let accumulatedDuration = 0;

  const canAddCandidate = (candidate: DecisionCandidateRead): boolean => {
    const cost = parseCandidateCost(candidate.cost);
    if (budgetMax !== null && currentCost + cost > budgetMax) {
      return false;
    }
    const dur = candidate.duration_minutes || (candidate.option_type === 'place' ? 90 : 60);
    if (durationLimit !== null && accumulatedDuration + dur > durationLimit) {
      return false;
    }
    if (deadlineMins !== null && baseStart + accumulatedDuration + dur > deadlineMins) {
      return false;
    }
    return true;
  };

  const addCandidate = (candidate: DecisionCandidateRead) => {
    selectedCandidates.push(candidate);
    selectedOptionIds.add(candidate.option_id);
    selectedCategories.add(candidate.category);
    currentCost += parseCandidateCost(candidate.cost);
    const dur = candidate.duration_minutes || (candidate.option_type === 'place' ? 90 : 60);
    accumulatedDuration += dur;
  };

  // 1. If user has a strong focus or activity_type preference, pick top candidate from that category first
  const preferredCats = understanding?.activity_types || [];
  if (preferredCats.length > 0) {
    for (const cat of preferredCats) {
      const match = eligible.find((c) => c.category === cat && !selectedOptionIds.has(c.option_id));
      if (match && canAddCandidate(match)) {
        addCandidate(match);
        break;
      }
    }
  }

  // 2. Add candidates with category diversity up to 3 items, staying within budget & time
  const maxItems = 3;
  for (const candidate of eligible) {
    if (selectedCandidates.length >= maxItems) break;
    if (selectedOptionIds.has(candidate.option_id)) continue;
    if (!canAddCandidate(candidate)) continue;

    if (!selectedCategories.has(candidate.category) || selectedCandidates.length === 0) {
      addCandidate(candidate);
    }
  }

  // 3. Fallback: if we still have room, budget, and time, fill with any remaining eligible items
  if (selectedCandidates.length < maxItems) {
    for (const candidate of eligible) {
      if (selectedCandidates.length >= maxItems) break;
      if (selectedOptionIds.has(candidate.option_id)) continue;
      if (!canAddCandidate(candidate)) continue;

      addCandidate(candidate);
    }
  }

  // Map selected candidates to itinerary items with humanized rationale
  const rawItems: ProposedItineraryItem[] = selectedCandidates.map((candidate) => ({
    candidate,
    icon: getCategoryIcon(candidate.category),
    subtitle: buildItemSubtitle(candidate),
    costNumber: parseCandidateCost(candidate.cost),
    rationale: humanizeCandidateReasons(candidate, budgetMax, groupSize, understanding),
  }));

  const items = assignTimeSlots(rawItems, understanding);

  const alternatives = eligible.filter((c) => !selectedOptionIds.has(c.option_id));
  const remainingBudget = budgetMax !== null ? budgetMax - currentCost : null;
  const isOverBudget = remainingBudget !== null && remainingBudget < 0;
  const narrativeSubheading = buildProposalNarrative(items, budgetMax, remainingBudget, understanding);
  const attribution = candidates.find((c) => c.attribution)?.attribution || null;
  const freshness = candidates.find((c) => c.freshness)?.freshness || null;
  const totalDurationMinutes = items.reduce((sum, i) => sum + (i.durationMinutes || 0), 0);
  const timeSpanDisplay = items.length > 0 && items[0].startTime && items[items.length - 1].endTime
    ? `${items[0].startTime} – ${items[items.length - 1].endTime}`
    : undefined;

  return {
    items,
    alternatives,
    estimatedTotal: currentCost,
    remainingBudget,
    isOverBudget,
    narrativeSubheading,
    attribution,
    freshness,
    totalDurationMinutes,
    timeSpanDisplay,
    tradeOffSummary: tradeOffSummary || null,
  };
}

/**
 * Recalculates totals, time slots, and narrative when items are swapped or removed.
 */
export function recalculateItinerary(
  items: ProposedItineraryItem[],
  allEligibleCandidates: DecisionCandidateRead[],
  budgetMax: number | null,
  understanding?: UnderstandingRead | null,
  tradeOffSummary?: string | null,
  travelMinutes: number[] = []
): ProposedItinerary {
  const slottedItems = assignTimeSlots(items, understanding, travelMinutes);
  const currentCost = slottedItems.reduce((sum, item) => sum + item.costNumber, 0);
  const selectedIds = new Set(slottedItems.map((i) => i.candidate.option_id));
  const alternatives = allEligibleCandidates.filter((c) => !selectedIds.has(c.option_id));
  const remainingBudget = budgetMax !== null ? budgetMax - currentCost : null;
  const isOverBudget = remainingBudget !== null && remainingBudget < 0;
  const narrativeSubheading = buildProposalNarrative(slottedItems, budgetMax, remainingBudget, understanding);
  const attribution = allEligibleCandidates.find((c) => c.attribution)?.attribution || null;
  const freshness = allEligibleCandidates.find((c) => c.freshness)?.freshness || null;
  const totalDurationMinutes = slottedItems.reduce((sum, i) => sum + (i.durationMinutes || 0), 0);
  const timeSpanDisplay = slottedItems.length > 0 && slottedItems[0].startTime && slottedItems[slottedItems.length - 1].endTime
    ? `${slottedItems[0].startTime} – ${slottedItems[slottedItems.length - 1].endTime}`
    : undefined;

  return {
    items: slottedItems,
    alternatives,
    estimatedTotal: currentCost,
    remainingBudget,
    isOverBudget,
    narrativeSubheading,
    attribution,
    freshness,
    totalDurationMinutes,
    timeSpanDisplay,
    tradeOffSummary: tradeOffSummary || null,
  };
}
