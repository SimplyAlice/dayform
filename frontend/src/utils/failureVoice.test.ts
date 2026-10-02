import assert from 'node:assert/strict';
import test from 'node:test';
import { deriveFailureDetails } from './failureVoice.ts';
import type { DecisionCandidateRead, PlanRead } from '../types/planning';

test('failure copy names the requested dinner and offers a time recovery', () => {
  const plan = {
    intention: 'Dinner in Woodstock after 22:00 under R100',
    understanding: {
      experience_requirements: ['meal'],
      activity_types: ['food'],
      location: 'Woodstock',
      location_is_inferred: false,
      provenance: { start_time: 'explicit' },
    },
  } as unknown as PlanRead;
  const candidate = {
    option_id: 'dinner',
    option_type: 'place',
    name: 'Woodstock Bistro',
    is_eligible: false,
    score: 0,
    reasons: [{ type: 'budget', outcome: 'violated', message: 'R380 is over R100' }],
    category: 'food',
    cost: 380,
    duration_minutes: 90,
    location: 'Woodstock',
    source: 'test',
  } as DecisionCandidateRead;
  const details = deriveFailureDetails(plan, [candidate], 100, async () => {}, () => {});

  assert.equal(details.headline, "I couldn't make that dinner work.");
  assert.match(details.explanation, /dinner.*after 22:00.*R100 budget/i);
  assert.ok(details.recoveryActions.some((action) => action.label === 'Change the time'));
  assert.ok(!details.headline.toLowerCase().includes('lunch'));
});