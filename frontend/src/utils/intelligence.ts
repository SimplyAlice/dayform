/**
 * Making the engine's real work legible.
 *
 * The brief for this scene was "show that something intelligent happened"
 * without putting on a fake one. That rules out typing animations, a spinner
 * and a progress bar that means nothing.
 *
 * So this reads only what the engine actually returned and counts it:
 *
 *   - every candidate carries `reasons`, each a constraint it was checked
 *     against with a real `outcome` and a real human message;
 *   - the orchestrated plan carries feasibility flags, coverage, the stops it
 *     had to remove, and the transport legs it priced.
 *
 * Every number below is a count of one of those. If the engine did not
 * evaluate something, the row is absent rather than faked — an empty
 * intelligence scene is more honest than a decorative one.
 */
import type {
  DecisionCandidateRead,
  OrchestratedPlanRead,
  ReasonType,
  UnderstandingRead,
} from '../types/planning';
import { explicitArea } from './planVoice';

export interface TraceConstraint {
  key: string;
  /** The constraint, in the order the engine actually applies them. */
  glyph: string;
  name: string;
  /** A sentence built from real counts. */
  verdict: string;
  passed: number;
  failed: number;
  /** How many venues carried this check at all. */
  considered: number;
  /** Real engine messages, kept for expansion. */
  evidence: string[];
}

/** How many candidates carried a check of this type, and how it went. */
function tally(candidates: DecisionCandidateRead[], type: ReasonType) {
  let passed = 0;
  let failed = 0;
  const evidence: string[] = [];
  for (const candidate of candidates) {
    for (const reason of candidate.reasons ?? []) {
      if (reason.type !== type) continue;
      if (reason.outcome === 'supported') passed += 1;
      else if (reason.outcome === 'violated') failed += 1;
      if (reason.message) evidence.push(`${candidate.name} — ${reason.message}`);
    }
  }
  return { passed, failed, considered: passed + failed, evidence };
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The constraint ladder, in the order a planner actually works through it:
 * find places, keep them in the area, keep them open, keep them affordable,
 * then make them reachable in sequence.
 *
 * Rows are only emitted when there is something real to say, so the scene can
 * be short on a simple request and long on a difficult one.
 */
export function buildConstraintTrace(
  candidates: DecisionCandidateRead[],
  orchestrated: OrchestratedPlanRead | null | undefined,
  understanding: UnderstandingRead | null | undefined,
  budgetMax: number | null,
): TraceConstraint[] {
  const rows: TraceConstraint[] = [];
  const total = candidates.length;

  /* 01 — PLACES. What the search actually returned. */
  if (total > 0) {
    const eligible = candidates.filter((c) => c.is_eligible).length;
    rows.push({
      key: 'places',
      glyph: '◎',
      name: 'Places',
      verdict:
        eligible === total
          ? `Found ${plural(total, 'venue', 'venues')} worth checking against your day.`
          : `Found ${plural(total, 'venue', 'venues')}; ${plural(total - eligible, 'was', 'were')} ruled out early.`,
      passed: eligible,
      failed: total - eligible,
      considered: total,
      evidence: [],
    });
  }

  /* 02 — AREA. The geographic constraint, counted from real location reasons. */
  const area = explicitArea(understanding);
  const loc = tally(candidates, 'location');
  if (area && loc.considered > 0) {
    rows.push({
      key: 'area',
      glyph: '⌖',
      name: 'Area',
      verdict:
        loc.failed === 0
          ? `Every venue checked is inside ${area}.`
          : `${plural(loc.failed, 'venue', 'venues')} fell outside ${area} and were ruled out.`,
      passed: loc.passed,
      failed: loc.failed,
      considered: loc.considered,
      evidence: loc.evidence,
    });
  }

  /* 03 — HOURS. Checked against each venue's own operating times. */
  const hours = tally(candidates, 'opening_hours');
  if (hours.considered > 0) {
    rows.push({
      key: 'hours',
      glyph: '◷',
      name: 'Hours',
      verdict:
        hours.failed === 0
          ? `${plural(hours.passed, 'venue is', 'venues are')} open when you'd arrive.`
          : `${plural(hours.failed, 'venue is', 'venues are')} shut when you'd arrive.`,
      passed: hours.passed,
      failed: hours.failed,
      considered: hours.considered,
      evidence: hours.evidence,
    });
  }

  /* 04 — BUDGET. Counted from real cost reasons, with the real cap. */
  const budget = tally(candidates, 'budget');
  if (budgetMax !== null && budget.considered > 0) {
    const cap = `R${Math.round(budgetMax).toLocaleString('en-ZA')}`;
    rows.push({
      key: 'budget',
      glyph: '⛁',
      name: 'Budget',
      verdict:
        budget.failed === 0
          ? `All checked venues fit inside ${cap}.`
          : `${plural(budget.failed, 'venue costs', 'venues cost')} more than ${cap} on their own.`,
      passed: budget.passed,
      failed: budget.failed,
      considered: budget.considered,
      evidence: budget.evidence,
    });
  }

  /* 05 — SEQUENCE. Whether the chosen stops can actually be reached in order. */
  if (orchestrated && orchestrated.stops.length > 0) {
    const f = orchestrated.feasibility;
    const legs = orchestrated.legs ?? [];
    const travel = f?.total_transition_duration_minutes ?? 0;
    const problems: string[] = [];
    if (f && !f.budget_respected) problems.push('the total runs over your budget');
    if (f && !f.deadline_respected) problems.push('it would finish after your limit');
    if (f && !f.transitions_feasible) problems.push('one of the legs will not work');

    const removed = orchestrated.removed_stops ?? [];
    const sequencing =
      problems.length > 0
        ? `Sequence held, but ${problems.join(', and ')}.`
        : removed.length > 0
          ? `Ordered into a workable day; ${plural(removed.length, 'stop did', 'stops did')} not fit.`
          : `Ordered into a workable day, ${plural(legs.length, 'leg', 'legs')} and about ${travel} min of travel.`;

    rows.push({
      key: 'sequence',
      glyph: '⇄',
      name: 'Sequence',
      verdict: sequencing,
      passed: problems.length === 0 ? 1 : 0,
      failed: problems.length === 0 ? 0 : 1,
      considered: 1,
      evidence: removed.map((r) => `${r.name} — ${r.reason}`),
    });
  }

  return rows;
}

/**
 * One line for the scene's lede: the honest summary of what the search cost
 * and what it returned. Not a boast, not a placeholder.
 */
export function traceLede(
  candidates: DecisionCandidateRead[],
  orchestrated: OrchestratedPlanRead | null | undefined,
): string {
  const total = candidates.length;
  if (total === 0) {
    return 'Nothing nearby matched every constraint you set, so there is nothing to show you yet.';
  }
  const kept = orchestrated?.stops.length ?? 0;
  const dropped = total - kept;
  if (dropped <= 0) {
    return `Dayform checked ${plural(total, 'venue', 'venues')} and kept the ${plural(kept, 'one', 'ones')} that hold up together.`;
  }
  return `Dayform checked ${plural(total, 'venue', 'venues')}, kept ${plural(kept, 'one', 'one')}, and set ${plural(dropped, 'one', 'the rest')} aside for the reasons below.`;
}
