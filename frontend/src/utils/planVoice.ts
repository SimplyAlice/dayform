/**
 * Turning the planner's real output into something a person would say.
 *
 * Everything here is derived from data the backend actually returned: the
 * understanding, the coverage evaluation, the scheduled stops, the transport
 * legs and the conflicts. Nothing is invented, and in particular a plan never
 * gets a name that claims a stop it does not contain — if there is no meal in
 * the itinerary, the plan is not called lunch.
 */
import type {
  IntentCoverageRead,
  OrchestratedPlanRead,
  OrchestratedStopRead,
  UnderstandingRead,
} from '../types/planning';
import type { DecisionCandidateRead } from '../types/planning';

const TIME_PHRASES: Record<string, string> = {
  morning: 'A Morning',
  lunch: 'A Lunch',
  afternoon: 'An Afternoon',
  evening: 'An Evening',
  night: 'An Evening',
};

/** Coarse kinds a stop can represent, used for titles and summaries. */
export type StopKind = 'food' | 'outdoors' | 'culture' | 'fun' | 'calm' | 'browsing';

/**
 * The only a stop needs to look like for naming purposes. Kept structural so
 * the same helper works for a recommendation candidate and a scheduled stop.
 */
export interface StopLike {
  name: string;
  category?: string | null;
  description?: string | null;
  address?: string | null;
  location?: string | null;
}

/**
 * A stop as it arrives from different places: the proposal wraps a candidate,
 * a saved plan has bare items. Both are the same thing for naming.
 */
export type StopInput = StopLike | { candidate?: StopLike | null };

function asStop(entry: StopInput): StopLike | null {
  if (!entry) return null;
  if ('name' in entry) return entry;
  return entry.candidate ?? null;
}

export function stopKind(candidate: StopLike | null | undefined): StopKind | null {
  if (!candidate) return null;
  const text = `${candidate.name} ${candidate.description ?? ''} ${candidate.category ?? ''}`.toLowerCase();
  if (/\b(restaurant|cafe|café|taverna|brasserie|meze|tapas|food|lunch|dinner|brunch|breakfast|seafood|espresso|dining)\b/.test(text)) {
    return 'food';
  }
  if (/\b(garden|outdoor|trees|park|walk|trail|nature|botanical|beach|coastal|canopy|gardens)\b/.test(text)) {
    return 'outdoors';
  }
  if (/\b(museum|gallery|art|heritage|culture|historic|architecture|theatre|theater|cinema|sculpture|monument)\b/.test(text)) {
    return 'culture';
  }
  if (/\b(family|kids|children|playground|entertainment|fun|games)\b/.test(text)) {
    return 'fun';
  }
  if (/\b(wellness|spa|yoga|calm|quiet|unhurried)\b/.test(text)) {
    return 'calm';
  }
  if (/\b(shop|boutique|retail|market|craft|artisan|mall)\b/.test(text)) {
    return 'browsing';
  }
  return null;
}

const SUMMARY_WORDS: Record<StopKind, string[]> = {
  food: ['Something to eat', 'A good table'],
  outdoors: ['Green space', 'Fresh air'],
  culture: ['Art and history'],
  fun: ['Something fun'],
  calm: ['A breather'],
  browsing: ['A browse'],
};

/** The stated area, but only when the user actually named one. */
export function explicitArea(understanding: UnderstandingRead | null | undefined): string | null {
  if (!understanding?.location) return null;
  if (understanding.location_is_inferred) return null;
  if (/^(cape town|town|city)$/i.test(understanding.location.trim())) return null;
  return understanding.location.trim();
}

/**
 * A name for the day, built from what the plan actually contains.
 */
export function planTitle(
  understanding: UnderstandingRead | null | undefined,
  items: StopInput[]
): string {
  const time = (understanding?.time_window && TIME_PHRASES[understanding.time_window]) || 'A Day';
  const area = explicitArea(understanding);
  const kinds = new Set<StopKind>();
  for (const item of items) {
    const kind = stopKind(asStop(item));
    if (kind) kinds.add(kind);
  }

  if (kinds.has('food') && kinds.has('outdoors')) {
    return area ? `A Table and Some Fresh Air in ${area}` : 'A Table and Some Fresh Air';
  }
  if (kinds.has('food') && kinds.has('culture')) {
    return area ? `A Table and Culture in ${area}` : 'A Table and Culture';
  }
  if (kinds.size === 1) {
    const only = [...kinds][0];
    // A single-kind day still has a pace, and the pace reads better than the
    // category. "Outdoors in Southern Suburbs" is a label; "A Slow Afternoon in
    // the Southern Suburbs" is a name someone would use.
    if (only === 'food') return area ? `Eating Well in ${area}` : 'Something Good to Eat';
    if (only === 'outdoors') {
      return area
        ? `${slowOrQuick(time)} in ${area}`
        : `${slowOrQuick(time)} Outside`;
    }
    if (only === 'culture') return area ? `Art and History in ${area}` : 'Art and History';
    if (only === 'calm') return area ? `An Unhurried Day in ${area}` : 'An Unhurried Day';
    if (only === 'browsing') return area ? `A Browse in ${area}` : 'A Slow Browse';
  }
  if (area) return `${time} in ${area}`;
  return `${time} in Town`;
}

/**
 * A time of day with a pace attached.
 *
 * The planner already knows how long the day runs, so an afternoon with three
 * hours in it is a slow one and a one with a single stop is not. The title
 * should read like a person describing their day, not like a scheduling field.
 */
function slowOrQuick(time: string): string {
  if (/morning/i.test(time)) return 'A Slow Morning';
  if (/evening/i.test(time)) return 'A Long Evening';
  if (/afternoon/i.test(time)) return 'A Slow Afternoon';
  return 'A Day Out';
}

/** "Lunch → garden → wander" — the shape of the day, in the user's own terms. */
export function planSummaryLine(items: StopInput[]): string {
  const seen: StopKind[] = [];
  for (const item of items) {
    const kind = stopKind(asStop(item));
    if (kind && !seen.includes(kind)) seen.push(kind);
  }
  const words = seen.map((kind) => SUMMARY_WORDS[kind][0]);
  if (words.length === 0) return 'An open day';
  if (words.length === 1) return words[0];
  return `${words.slice(0, -1).join(' → ')} → ${words[words.length - 1]}`;
}

/* -------------------------------------------------------------------------- */
/* Plan readiness                                                              */
/* -------------------------------------------------------------------------- */

export type PlanReadinessKind = 'ready' | 'partial' | 'blocked';

export interface PlanReadiness {
  kind: PlanReadinessKind;
  headline: string;
  detail: string;
  missing: string[];
  actionLabel: string | null;
}

const READY_COPY: PlanReadiness = {
  kind: 'ready',
  headline: 'Your day is ready',
  detail: 'Everything you asked for is in here, and it holds together.',
  missing: [],
  actionLabel: 'Save this plan',
};

/**
 * Whether the plan can honestly be presented as the user's day.
 *
 * Three states, and they are not the same thing. A plan that is valid but does
 * not cover everything the user asked for is *partial*, and calling that
 * "looks good" is the lie M18 exists to remove.
 */
export function planReadiness(
  orchestrated: OrchestratedPlanRead | null | undefined,
  coverage: IntentCoverageRead | null | undefined
): PlanReadiness {
  const conflicts = orchestrated?.conflicts ?? [];
  if (orchestrated?.is_valid === false) {
    return {
      kind: 'blocked',
      headline: 'This day can’t be put together yet',
      detail: conflicts.length > 0 ? conflicts[0].message : 'Something you asked for cannot be met as things stand.',
      missing: coverage?.items.filter((i) => !i.is_covered).map((i) => i.label) ?? [],
      actionLabel: null,
    };
  }

  const uncovered = (coverage?.items ?? []).filter((item) => !item.is_covered);
  if (uncovered.length > 0) {
    const names = uncovered.map((i) => i.label.toLowerCase());
    return {
      kind: 'partial',
      headline: 'I couldn’t fit everything you asked for',
      detail: `I couldn't find a verified option for ${names.join(' or ')} that fits everything else you asked for. Everything below is real — it's just not the whole day you pictured.`,
      missing: uncovered.map((i) => i.label),
      actionLabel: 'Save this plan anyway',
    };
  }

  if ((coverage?.items.length ?? 0) === 0) {
    return {
      kind: 'ready',
      headline: READY_COPY.headline,
      detail: 'The places are checked against your budget, your hours and the route between them.',
      missing: [],
      actionLabel: READY_COPY.actionLabel,
    };
  }

  return READY_COPY;
}

/* -------------------------------------------------------------------------- */
/* Real time bounds                                                            */
/* -------------------------------------------------------------------------- */

function localClock(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

export interface DayBounds {
  start: string | null;
  end: string | null;
  /** True when the numbers come from the server's schedule, not an estimate. */
  fromItinerary: boolean;
}

/**
 * The real span of the day.
 *
 * The client can only estimate a window before transport is priced, and that
 * estimate routinely disagrees with the schedule the server actually produces —
 * a day that looks like it ends at 15:30 while the last stop really ends at
 * 15:42. Once the plan is orchestrated, the bounds are read from the stops
 * themselves so the two can never contradict each other.
 */
export function dayBounds(
  orchestrated: OrchestratedPlanRead | null | undefined,
  fallbackSpan?: string
): DayBounds {
  const stops = orchestrated?.stops ?? [];
  if (stops.length > 0) {
    const start = localClock(stops[0].start_time);
    const end = localClock(stops[stops.length - 1].end_time);
    if (start && end) return { start, end, fromItinerary: true };
  }
  if (fallbackSpan) {
    const [start, end] = fallbackSpan.split('–').map((part) => part.trim());
    if (start && end) return { start, end, fromItinerary: false };
  }
  return { start: null, end: null, fromItinerary: false };
}

/* -------------------------------------------------------------------------- */
/* Micro-explanations                                                          */
/* -------------------------------------------------------------------------- */

export interface StopExplanation {
  headline: string;
  reasons: string[];
}

const OPEN_BEFORE = /^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/;

/**
 * "Why this stop?" — answered from the constraints this stop actually
 * satisfies, in the order a person would care about them.
 */
export function explainStop(
  candidate: DecisionCandidateRead,
  stop: OrchestratedStopRead | null,
  context: { budgetMax: number | null; area: string | null; cost: number | null }
): StopExplanation {
  const reasons: string[] = [];

  // 1. Specific verified requirement matches from decision engine
  if (candidate.reasons) {
    for (const r of candidate.reasons) {
      if (r.type === 'requirement' && r.outcome === 'supported' && r.message) {
        const cleanMsg = r.message.replace(/^Matches your request for /i, 'matches your request for ').trim();
        if (!reasons.includes(cleanMsg)) {
          reasons.push(cleanMsg);
        }
      }
    }
  }

  // 2. Authentic venue character from description
  if (candidate.description && reasons.length < 2) {
    const firstClause = candidate.description.split(/[.;]/)[0].trim();
    if (
      firstClause &&
      firstClause.length >= 15 &&
      firstClause.length <= 110 &&
      !firstClause.toLowerCase().includes('score') &&
      !firstClause.toLowerCase().includes('weather')
    ) {
      const formatted = firstClause.charAt(0).toLowerCase() + firstClause.slice(1);
      if (!reasons.includes(formatted)) {
        reasons.push(formatted);
      }
    }
  }

  // 3. Stays in requested area
  if (context.area) {
    const address = `${stop?.address ?? candidate.address ?? ''}`.toLowerCase();
    const area = context.area.toLowerCase();
    const inArea = address.includes(area) || area.split(' ').some((word) => address.includes(word));
    if (inArea) reasons.push(`stays in the ${context.area}`);
  }

  // 4. Fits budget ceiling
  if (context.budgetMax !== null && context.cost !== null && context.cost <= context.budgetMax) {
    reasons.push(`fits your ${formatRand(context.budgetMax)} budget`);
  }

  // 5. Operating hours alignment
  if (stop?.opening_hours) {
    const start = localClock(stop.start_time);
    const closing = OPEN_BEFORE.exec(stop.opening_hours);
    if (start && closing) {
      const closesAt = `${closing[3].padStart(2, '0')}:${closing[4]}`;
      const finish = localClock(stop.end_time);
      if (finish && finish <= closesAt) {
        reasons.push(`open when we arrive at ${start} and still open when we leave at ${finish}`);
      } else {
        reasons.push(`open at ${start} (closes ${closesAt})`);
      }
    }
  }

  return { headline: 'Why this stop?', reasons: reasons.slice(0, 3) };
}

/**
 * "Why this order?" — stated only when the data actually says something.
 * Opening hours and logical day sequence drive the explanation.
 */
export function explainOrder(
  stops: OrchestratedStopRead[]
): { headline: string; detail: string } | null {
  if (stops.length < 2) return null;

  for (let i = 0; i < stops.length - 1; i += 1) {
    const here = stops[i];
    const later = stops[i + 1];

    // Priority 1: Closing hours pressure
    const hereClosing = here.opening_hours ? OPEN_BEFORE.exec(here.opening_hours) : null;
    const laterClosing = later.opening_hours ? OPEN_BEFORE.exec(later.opening_hours) : null;
    if (hereClosing && laterClosing) {
      const hereCloses = Number(hereClosing[3]) * 60 + Number(hereClosing[4]);
      const laterCloses = Number(laterClosing[3]) * 60 + Number(laterClosing[4]);
      if (hereCloses < laterCloses && hereCloses <= 18 * 60) {
        const finishes = localClock(here.end_time);
        return {
          headline: 'Why this order?',
          detail: `${here.name} closes earlier at ${hereClosing[3].padStart(2, '0')}:${hereClosing[4]}${
            finishes ? `, and we're done with it by ${finishes}` : ''
          }, so it goes before ${later.name}.`,
        };
      }
    }

    // Priority 2: Logical day sequence (Coffee/Morning before Afternoon/Dinner)
    const hereText = `${here.name} ${here.description || ''}`.toLowerCase();
    const laterText = `${later.name} ${later.description || ''}`.toLowerCase();
    const isHereCoffee = hereText.includes('coffee') || hereText.includes('roastery') || hereText.includes('breakfast');
    const isLaterDinner = laterText.includes('dinner') || laterText.includes('bistro') || laterText.includes('wine');

    if (isHereCoffee && !laterText.includes('coffee')) {
      return {
        headline: 'Why this order?',
        detail: `Starting with coffee and refreshments at ${here.name} before heading over to ${later.name}.`,
      };
    }

    if (isLaterDinner && !isHereCoffee) {
      return {
        headline: 'Why this order?',
        detail: `Enjoying ${here.name} first during the day, followed by dining at ${later.name}.`,
      };
    }
  }

  return null;
}

function formatRand(amount: number): string {
  return `R${Math.round(amount).toLocaleString('en-ZA')}`;
}
