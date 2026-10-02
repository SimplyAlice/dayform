import type {
  DecisionCandidateRead,
  InformationCategory,
  RequirementCoverageRead,
  PlanTransitionRead,
  UnderstandingRead,
} from '../types/planning';

export interface ProposedItineraryItem {
  candidate: DecisionCandidateRead;
  icon: string;
  subtitle: string;
  costNumber: number | null;
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
export function parseCandidateCost(cost: string | number | null | undefined): number | null {
  return knownCandidateCost(cost);
}

export function knownCandidateCost(cost: string | number | null | undefined): number | null {
  if (cost === null || cost === undefined || (typeof cost === 'string' && !cost.trim())) return null;
  const parsed = typeof cost === 'number' ? cost : parseFloat(cost);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatExactCurrency(amount: number): string {
  const rounded = Math.round((amount + Number.EPSILON) * 100) / 100;
  return Number.isInteger(rounded) ? formatCurrency(rounded) : `R${rounded.toFixed(2)}`;
}

export interface ItineraryCostSummary {
  knownTotal: number;
  hasUnknownCosts: boolean;
  totalLabel: string;
  remainingBudget: number | null;
  isOverBudget: boolean;
}

export function summarizeItineraryCosts(
  stopCosts: Array<string | number | null | undefined>,
  knownTransportCost: string | number | null | undefined,
  hasUnknownTransportCost: boolean,
  budgetMax: number | null
): ItineraryCostSummary {
  const knownStopCosts = stopCosts.map(knownCandidateCost);
  const knownTransport = knownCandidateCost(knownTransportCost) ?? 0;
  const knownTotal = Math.round(
    knownStopCosts.reduce<number>((sum, cost) => sum + (cost ?? 0), knownTransport) * 100
  ) / 100;
  const hasUnknownCosts = knownStopCosts.some((cost) => cost === null) || hasUnknownTransportCost;
  const amount = knownTotal === 0 ? 'R0' : formatExactCurrency(knownTotal);

  return {
    knownTotal,
    hasUnknownCosts,
    totalLabel: hasUnknownCosts
      ? knownTotal === 0 ? 'Price unavailable' : `At least ${amount}`
      : amount,
    remainingBudget: budgetMax !== null && !hasUnknownCosts
      ? Math.round((budgetMax - knownTotal) * 100) / 100
      : null,
    isOverBudget: budgetMax !== null && knownTotal > budgetMax,
  };
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

export function parseOpeningMinutes(hoursStr?: string | null): number | null {
  if (!hoursStr) return null;
  const m = /(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/.exec(hoursStr);
  if (m) {
    return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
  }
  return null;
}

export function parseClosingMinutes(hoursStr?: string | null): number | null {
  if (!hoursStr) return null;
  const m = /(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/.exec(hoursStr);
  if (m) {
    return parseInt(m[3], 10) * 60 + parseInt(m[4], 10);
  }
  return null;
}

export function assignTimeSlots(
  items: ProposedItineraryItem[],
  understanding?: UnderstandingRead | null,
  travelMinutes: number[] = []
): ProposedItineraryItem[] {
  if (items.length === 0) return [];
  const base = getBaseStartTimeMinutes(understanding);
  let currentCursor = base.minutes;

  // If Stop 1 opens after the base start time, adjust start to when it actually opens
  if (items[0]?.candidate.opening_hours) {
    const openMins = parseOpeningMinutes(items[0].candidate.opening_hours);
    if (openMins !== null && currentCursor < openMins) {
      currentCursor = openMins;
    }
  }

  return items.map((item, idx) => {
    // If subsequent stop opens later than arrival, push cursor to its opening time
    if (idx > 0 && item.candidate.opening_hours) {
      const openMins = parseOpeningMinutes(item.candidate.opening_hours);
      if (openMins !== null && currentCursor < openMins) {
        currentCursor = openMins;
      }
    }

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
  } else if (cost !== null && budgetMax !== null && cost <= budgetMax) {
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
  if (altCost === null || currentCost === null) {
    return 'Price not listed';
  }
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

  if (understanding?.experience_requirements?.includes('quiet_focus')) {
    const budgetNote = remainingBudget !== null && remainingBudget > 0 ? `, with ${formatCurrency(remainingBudget)} left in your budget.` : '.';
    const isCozy = understanding.preferences?.includes('cozy') || understanding.semantic_descriptors?.includes('cozy');
    const vibeWord = isCozy ? 'cozy' : 'quiet';
    return `A ${vibeWord} afternoon spot to relax and read${budgetNote}`;
  }

  if (understanding?.experience_requirements?.includes('painting')) {
    const budgetNote = remainingBudget !== null && remainingBudget > 0 ? `, with ${formatCurrency(remainingBudget)} left to spare.` : '.';
    return `A scenic outdoor spot tailored for painting and creative time${budgetNote}`;
  }

  if (understanding?.experience_requirements?.includes('shopping')) {
    const budgetNote = remainingBudget !== null && remainingBudget > 0 ? `, with ${formatCurrency(remainingBudget)} left in your budget.` : '.';
    return `A curated shopping outing tailored to your afternoon${budgetNote}`;
  }

  if (understanding?.experience_requirements?.includes('historic_streets')) {
    const budgetNote = remainingBudget !== null && remainingBudget > 0 ? `, with ${formatCurrency(remainingBudget)} left in your budget.` : '.';
    return `A walk through historic streets and architecture${budgetNote}`;
  }

  if (categories.has('food') && (categories.has('nature') || categories.has('culture'))) {
    if (remainingBudget !== null && remainingBudget > 0) {
      return `A balanced plan with something fun to do, good food, and ${formatCurrency(remainingBudget)} left in your budget.`;
    }
    return 'A balanced plan with something fun to do and great food.';
  }

  if (items.length === 1 && categories.has('food')) {
    const budgetNote = remainingBudget !== null && remainingBudget > 0 ? `, with ${formatCurrency(remainingBudget)} left in your budget.` : '.';
    return `A standout dining experience tailored to your request${budgetNote}`;
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
 * Haversine distance in kilometers between two geo coordinates.
 */
export function calculateHaversineDistance(
  lat1?: number | null,
  lon1?: number | null,
  lat2?: number | null,
  lon2?: number | null
): number | null {
  if (lat1 == null || lon1 == null || lat2 == null || lon2 == null) return null;
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

const REQUIREMENT_KEYWORDS: Record<string, string[]> = {
  meal: ['restaurant', 'cafe', 'café', 'bistro', 'coffee', 'roastery', 'lunch', 'dinner', 'breakfast', 'brunch', 'food', 'bakery', 'tasting'],
  quiet_focus: ['book', 'books', 'bookshop', 'bookstore', 'library', 'reading', 'read', 'study', 'quiet', 'workspace'],
  local_culture: ['culture', 'cultural', 'heritage', 'museum', 'art gallery', 'history', 'community'],
  museum: ['museum', 'museums'],
  historic_streets: ['historic', 'historical', 'heritage', 'bo-kaap', 'architecture', 'monument', 'old town', 'cobbled'],
  craft_food_market: ['market', 'craft market', 'food market', 'farmers market', 'food hall', 'bazaar'],
  local_market: ['market', 'bazaar', 'produce', 'stalls'],
  live_music: ['music', 'live jazz', 'jazz', 'concert', 'band'],
  scenic_views: ['view', 'views', 'panoramic', 'lookout', 'scenic', 'summit', 'cableway'],
  beach: ['beach', 'ocean', 'seaside', 'coastline', 'shore', 'promenade'],
  art: ['art', 'gallery', 'exhibition', 'sculpture'],
  shopping: ['shop', 'shopping', 'boutique', 'vintage', 'thrift', 'curio'],
  painting: ['paint', 'painting', 'sketch', 'plein air', 'scenic', 'garden', 'landscape'],
};

export function candidateMatchesRequirement(
  candidate: DecisionCandidateRead,
  reqSlug: string
): boolean {
  if (candidate.reasons) {
    const hasReason = candidate.reasons.some(
      (r) =>
        r.type === 'requirement' &&
        r.outcome === 'supported' &&
        r.message?.toLowerCase().includes(reqSlug.replace('_', ' '))
    );
    if (hasReason) return true;
  }

  const keywords = REQUIREMENT_KEYWORDS[reqSlug];
  if (!keywords) return false;

  const text = `${candidate.name} ${candidate.description || ''} ${candidate.category}`.toLowerCase();
  return keywords.some((kw) => text.includes(kw));
}

export function isExplicitSingleExperience(
  intentText: string,
  experienceRequirements: string[]
): boolean {
  const lowerIntent = intentText.toLowerCase();
  const hasNamedDestination = experienceRequirements.length === 0 &&
    /\b(?:take me to|go to|visit|head to)\s+(?:the\s+)?[a-z]/.test(lowerIntent);
  return (experienceRequirements.length === 1 || hasNamedDestination) &&
    !/\b(?:and|then|afterwards|followed by|plus)\b/.test(lowerIntent) &&
    !/\b(?:day out|something to do|an activity)\b/.test(lowerIntent);
}

function explicitDestinationFromIntent(intentText: string): string | null {
  const match = /\b(?:take me to|go to|visit|head to)\s+(?:the\s+)?(.+?)(?=\s+\b(?:by|in|under|after|before|at|with)\b|[.,!?]|$)/i.exec(intentText);
  return match?.[1]?.trim() || null;
}

export function explainUnmetRequirement(
  requirement: Pick<RequirementCoverageRead, 'slug' | 'label'>,
  candidates: DecisionCandidateRead[],
  removedStops: Array<{ name: string; reason: string }> = [],
  budgetMax: number | null = null,
  area: string | null = null
): string {
  const matches = candidates.filter((candidate) => candidateMatchesRequirement(candidate, requirement.slug));
  const removed = removedStops.find((stop) => matches.some((candidate) => candidate.name === stop.name));
  if (removed) {
    return `${requirement.label} was left out because ${removed.reason}.`;
  }

  const allHaveViolation = (type: DecisionCandidateRead['reasons'][number]['type']) =>
    matches.length > 0 && matches.every((candidate) =>
      candidate.reasons.some((reason) => reason.type === type && reason.outcome === 'violated')
    );

  if (allHaveViolation('budget') && budgetMax !== null) {
    return `The ${requirement.label.toLowerCase()} options found exceed your ${formatCurrency(budgetMax)} budget.`;
  }
  if (allHaveViolation('opening_hours') || allHaveViolation('time_window')) {
    return `The ${requirement.label.toLowerCase()} options found are not open during the requested time.`;
  }
  if (allHaveViolation('location')) {
    return `No ${requirement.label.toLowerCase()} option could be verified in ${area || 'the requested area'}.`;
  }
  if (allHaveViolation('group_size')) {
    return `The ${requirement.label.toLowerCase()} options found cannot accommodate your group.`;
  }
  if (matches.length === 0) {
    return `No verified option for ${requirement.label.toLowerCase()} was found${area ? ` in ${area}` : ''}.`;
  }

  return `An option for ${requirement.label.toLowerCase()} was found, but it is not included in this itinerary.`;
}

export function isDiningCandidate(candidate: DecisionCandidateRead): boolean {
  if (candidate.category === 'food') return true;
  const text = `${candidate.name} ${candidate.description || ''}`.toLowerCase();
  return (
    text.includes('restaurant') ||
    text.includes('cafe') ||
    text.includes('café') ||
    text.includes('bistro') ||
    text.includes('coffee') ||
    text.includes('roastery') ||
    text.includes('bakery') ||
    text.includes('brunch')
  );
}

export function isMorningCoffeeOrBreakfast(candidate: DecisionCandidateRead): boolean {
  const text = `${candidate.name} ${candidate.description || ''}`.toLowerCase();
  return (
    text.includes('coffee') ||
    text.includes('roastery') ||
    text.includes('espresso') ||
    text.includes('breakfast') ||
    text.includes('bakery') ||
    text.includes('cafe') ||
    text.includes('café')
  );
}

export function isDinnerOrEvening(candidate: DecisionCandidateRead): boolean {
  const text = `${candidate.name} ${candidate.description || ''}`.toLowerCase();
  return (
    text.includes('dinner') ||
    text.includes('wine bar') ||
    text.includes('tasting menu') ||
    text.includes('evening') ||
    text.includes('cocktails')
  );
}

export function orderStopsSensibly(
  stops: DecisionCandidateRead[],
  _understanding?: UnderstandingRead | null
): DecisionCandidateRead[] {
  if (stops.length < 2) return stops;
  const [a, b] = stops;

  // Rule 1: Closing hours pressure (earlier-closing venue must be visited before it closes)
  const aClose = parseClosingMinutes(a.opening_hours);
  const bClose = parseClosingMinutes(b.opening_hours);
  if (aClose !== null && bClose !== null && Math.abs(aClose - bClose) >= 120) {
    if (aClose < bClose) return [a, b];
    return [b, a];
  }

  // Rule 2: Morning coffee / breakfast comes first
  const aCoffee = isMorningCoffeeOrBreakfast(a);
  const bCoffee = isMorningCoffeeOrBreakfast(b);
  const aDinner = isDinnerOrEvening(a);
  const bDinner = isDinnerOrEvening(b);

  if (aCoffee && !bCoffee) return [a, b];
  if (bCoffee && !aCoffee) return [b, a];

  // Rule 3: Daytime activity precedes dinner/evening
  if (aDinner && !bDinner) return [b, a];
  if (bDinner && !aDinner) return [a, b];

  // Rule 4: Culture / Nature activity before general dining meal
  const aIsDining = isDiningCandidate(a);
  const bIsDining = isDiningCandidate(b);
  if (!aIsDining && bIsDining) return [a, b];
  if (aIsDining && !bIsDining) return [b, a];

  return [a, b];
}

/**
 * Assembles an intentionally composed proposed itinerary from ranked recommendation candidates.
 *
 * Evaluates:
 * 1. Requirement coverage: ensures multiple explicit user requirements are each satisfied.
 * 2. Semantic relevance: tests genuine evidence text, not broad categories.
 * 3. Variety: avoids redundant dining stops; pairs complementary experiences.
 * 4. Geographic coherence: minimizes transit distance and favors walkable/clustered pairs.
 * 5. Temporal coherence: fits verified opening hours and time windows.
 * 6. Budget coherence: strictly respects budget ceiling.
 * 7. Sensible sequencing: orders stops naturally across the day (morning coffee -> activity -> dining).
 */
export function buildProposedItinerary(
  candidates: DecisionCandidateRead[],
  budgetMax: number | null,
  intentText: string = '',
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
        return cost !== null && cost < 400 && !nameLower.includes('fine dining') && !nameLower.includes('luxury');
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

  // A single named experience is not a request for a generic second stop.
  // Keep variety pairing for prompts that explicitly connect multiple activities.
  const isExplicitSingleStop = isExplicitSingleExperience(
    intentText,
    understanding?.experience_requirements || []
  );

  const selectedCandidates: DecisionCandidateRead[] = [];
  const selectedOptionIds = new Set<string>();

  const canAfford = (c: DecisionCandidateRead, extraCost: number = 0): boolean => {
    if (budgetMax === null) return true;
    const cost = parseCandidateCost(c.cost);
    return cost !== null && extraCost + cost <= budgetMax;
  };

  const experienceReqs = understanding?.experience_requirements || [];

  // COMPOSITION STRATEGY 1: Multiple explicit experience requirements (e.g. coffee + bookshop, or lunch + art)
  if (experienceReqs.length >= 2 && !isExplicitSingleStop) {
    const reqA = experienceReqs[0];
    const reqB = experienceReqs[1];

    const candsA = eligible.filter((c) => candidateMatchesRequirement(c, reqA));
    const candsB = eligible.filter((c) => candidateMatchesRequirement(c, reqB));

    let bestPair: [DecisionCandidateRead, DecisionCandidateRead] | null = null;
    let bestScore = -Infinity;

    for (const a of candsA) {
      if (!canAfford(a)) continue;
      const costA = parseCandidateCost(a.cost);
      if (costA === null) continue;

      for (const b of candsB) {
        if (a.option_id === b.option_id) continue;
        if (!canAfford(b, costA)) continue;

        // Variety check: do not pair 2 dining spots unless both requirements explicitly asked for food
        const bothDining = isDiningCandidate(a) && isDiningCandidate(b);
        if (bothDining && (reqA !== 'meal' || reqB !== 'meal')) {
          continue;
        }

        // Geographic affinity
        let geoBonus = 0;
        const dist = calculateHaversineDistance(a.latitude, a.longitude, b.latitude, b.longitude);
        if (dist !== null) {
          if (dist <= 1.5) geoBonus = 60; // Walking distance!
          else if (dist <= 4.0) geoBonus = 30; // Short ride
          else if (dist > 10.0) geoBonus = -40; // Avoid excessive travel
        } else if (a.location && b.location && a.location.toLowerCase() === b.location.toLowerCase()) {
          geoBonus = 25;
        }

        const pairScore = a.score + b.score + geoBonus;
        if (pairScore > bestScore) {
          bestScore = pairScore;
          bestPair = [a, b];
        }
      }
    }

    if (bestPair) {
      const ordered = orderStopsSensibly(bestPair, understanding);
      selectedCandidates.push(...ordered);
      ordered.forEach((c) => selectedOptionIds.add(c.option_id));
    }
  }

  // COMPOSITION STRATEGY 2: Single-focus or standard 2-stop composition if strategy 1 did not produce a pair
  if (selectedCandidates.length === 0) {
    if (experienceReqs.length >= 2) {
      const topCand = eligible.find(
        (candidate) => experienceReqs.some((requirement) => candidateMatchesRequirement(candidate, requirement)) && canAfford(candidate)
      );
      if (topCand) {
        selectedCandidates.push(topCand);
        selectedOptionIds.add(topCand.option_id);
      }
    } else if (isExplicitSingleStop) {
      const explicitRequirement = experienceReqs[0];
      const explicitDestination = experienceReqs.length === 0
        ? explicitDestinationFromIntent(intentText)?.toLowerCase()
        : null;
      const topCand = eligible.find(
        (candidate) =>
          (explicitRequirement
            ? candidateMatchesRequirement(candidate, explicitRequirement)
            : Boolean(explicitDestination && `${candidate.name} ${candidate.location || ''} ${candidate.address || ''}`.toLowerCase().includes(explicitDestination))) &&
          canAfford(candidate)
      );
      if (topCand) {
        selectedCandidates.push(topCand);
        selectedOptionIds.add(topCand.option_id);
      }
    } else {
      // Pick Stop 1: top scoring candidate matching preferred categories or highest overall
      const preferredCats = understanding?.activity_types || [];
      let topCand = preferredCats.length > 0
        ? eligible.find((c) => preferredCats.includes(c.category) && canAfford(c))
        : null;
      if (!topCand) {
        topCand = eligible.find((c) => canAfford(c)) || null;
      }

      if (topCand) {
        selectedCandidates.push(topCand);
        selectedOptionIds.add(topCand.option_id);
        const cost1 = parseCandidateCost(topCand.cost) ?? 0;

        // Pick Stop 2: prioritize variety and geographic coherence
        const isStop1Dining = isDiningCandidate(topCand);
        let bestStop2: DecisionCandidateRead | null = null;
        let bestStop2Score = -Infinity;

        for (const cand of eligible) {
          if (selectedOptionIds.has(cand.option_id)) continue;
          if (!canAfford(cand, cost1)) continue;

          // Variety score: prefer complementary experience over duplicate category
          let varietyScore = 0;
          const isCandDining = isDiningCandidate(cand);
          if (isStop1Dining && isCandDining) {
            varietyScore = -50; // Strongly avoid 2 restaurants in a standard day out
          } else if (topCand.category !== cand.category) {
            varietyScore = 30; // Complementary variety
          }

          // Geographic affinity
          let geoScore = 0;
          const dist = calculateHaversineDistance(topCand.latitude, topCand.longitude, cand.latitude, cand.longitude);
          if (dist !== null) {
            if (dist <= 1.5) geoScore = 50;
            else if (dist <= 4.0) geoScore = 25;
            else if (dist > 10.0) geoScore = -35;
          } else if (topCand.location && cand.location && topCand.location.toLowerCase() === cand.location.toLowerCase()) {
            geoScore = 20;
          }

          const combined = cand.score + varietyScore + geoScore;
          if (combined > bestStop2Score) {
            bestStop2Score = combined;
            bestStop2 = cand;
          }
        }

        if (bestStop2) {
          selectedCandidates.push(bestStop2);
          selectedOptionIds.add(bestStop2.option_id);
          // Order the 2 stops logically
          const ordered = orderStopsSensibly(selectedCandidates, understanding);
          selectedCandidates.length = 0;
          selectedCandidates.push(...ordered);
        }
      }
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
  const currentCost = items.reduce((sum, it) => sum + (it.costNumber ?? 0), 0);
  const alternatives = eligible.filter((c) => !selectedOptionIds.has(c.option_id));
  const hasUnknownCosts = items.some((item) => item.costNumber === null);
  const remainingBudget = budgetMax !== null && !hasUnknownCosts ? budgetMax - currentCost : null;
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
  const currentCost = slottedItems.reduce((sum, item) => sum + (item.costNumber ?? 0), 0);
  const selectedIds = new Set(slottedItems.map((i) => i.candidate.option_id));
  const alternatives = allEligibleCandidates.filter((c) => !selectedIds.has(c.option_id));
  const hasUnknownCosts = slottedItems.some((item) => item.costNumber === null);
  const remainingBudget = budgetMax !== null && !hasUnknownCosts ? budgetMax - currentCost : null;
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
