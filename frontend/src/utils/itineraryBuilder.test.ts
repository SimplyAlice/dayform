import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildProposedItinerary,
  explainUnmetRequirement,
  isExplicitSingleExperience,
  parseCandidateCost,
  summarizeItineraryCosts,
} from './itineraryBuilder.ts';
import type { DecisionCandidateRead, UnderstandingRead } from '../types/planning';

function candidate(
  name: string,
  reasonType?: DecisionCandidateRead['reasons'][number]['type']
): DecisionCandidateRead {
  return {
    option_id: name,
    option_type: 'place',
    name,
    is_eligible: false,
    score: 0,
    reasons: reasonType
      ? [{ type: reasonType, outcome: 'violated', message: 'A verified constraint failed.' }]
      : [],
    category: 'culture',
    cost: null,
    duration_minutes: null,
    location: null,
    source: 'test',
  };
}

test('one named experience does not imply a second stop', () => {
  assert.equal(isExplicitSingleExperience('Coffee in Observatory', ['meal']), true);
  assert.equal(isExplicitSingleExperience('Coffee and a bookshop', ['meal', 'quiet_focus']), false);
  assert.equal(isExplicitSingleExperience('Lunch then museum', ['meal', 'local_culture']), false);
  assert.equal(isExplicitSingleExperience('Lunch and something to do', ['meal']), false);
});

test('an unavailable museum is not silently replaced by a gallery', () => {
  const cafe = {
    ...candidate('Observatory Cafe'),
    is_eligible: true,
    category: 'food' as const,
    cost: 80,
    score: 90,
    description: 'Coffee and lunch served in Observatory.',
  };
  const gallery = {
    ...candidate('Goodman Gallery Cape Town'),
    is_eligible: true,
    category: 'culture' as const,
    cost: 0,
    score: 100,
    description: 'Contemporary art gallery in Woodstock.',
  };
  const understanding = {
    experience_requirements: ['meal', 'museum'],
    activity_types: ['food', 'culture'],
    people_count: 1,
  } as unknown as UnderstandingRead;

  const proposal = buildProposedItinerary(
    [cafe, gallery],
    null,
    'Lunch then museum in Woodstock',
    1,
    understanding
  );

  assert.deepEqual(proposal.items.map((item) => item.candidate.name), ['Observatory Cafe']);
});

test('a named destination request does not acquire a generic second stop', () => {
  const boomslang = {
    ...candidate('Kirstenbosch Boomslang Canopy Walk'),
    is_eligible: true,
    category: 'nature' as const,
    score: 90,
    location: 'Kirstenbosch, Cape Town',
  };
  const dam = {
    ...candidate('Kirstenbosch Dam'),
    is_eligible: true,
    category: 'food' as const,
    score: 80,
    location: 'Kirstenbosch, Cape Town',
  };
  const understanding = {
    experience_requirements: [],
    activity_types: ['nature', 'food'],
    people_count: 1,
  } as unknown as UnderstandingRead;

  const proposal = buildProposedItinerary(
    [boomslang, dam],
    null,
    'Take me to Kirstenbosch by public transport',
    1,
    understanding
  );

  assert.deepEqual(proposal.items.map((item) => item.candidate.name), ['Kirstenbosch Boomslang Canopy Walk']);
});

test('budget totals use selected stop and transport costs', () => {
  assert.equal(parseCandidateCost(null), null);
  assert.equal(parseCandidateCost(''), null);
  assert.deepEqual(summarizeItineraryCosts([380], 0, false, 500), {
    knownTotal: 380,
    hasUnknownCosts: false,
    totalLabel: 'R380',
    remainingBudget: 120,
    isOverBudget: false,
  });
  assert.equal(summarizeItineraryCosts([null], 0, false, 500).totalLabel, 'Price unavailable');
  assert.equal(summarizeItineraryCosts([null], 0, false, 500).remainingBudget, null);
  const withTransitFare = summarizeItineraryCosts([380], 10.5, false, 500);
  assert.equal(withTransitFare.totalLabel, 'R390.50');
  assert.equal(withTransitFare.remainingBudget, 109.5);
  assert.equal(summarizeItineraryCosts([380], 0, true, 500).totalLabel, 'At least R380');
});

test('unmet requirements report evidence-backed causes', () => {
  const museum = { slug: 'local_culture', label: 'A museum' };
  assert.equal(
    explainUnmetRequirement(museum, [], [], null, 'Woodstock'),
    'No verified option for a museum was found in Woodstock.'
  );

  const gallery = candidate('Woodstock Art Gallery', 'opening_hours');
  assert.equal(
    explainUnmetRequirement(
      { slug: 'art', label: 'Art' },
      [gallery],
      [{ name: gallery.name, reason: 'it is closed at 20:00 (hours: Tue-Fri 09:30-17:30)' }]
    ),
    'Art was left out because it is closed at 20:00 (hours: Tue-Fri 09:30-17:30).'
  );

  const meal = candidate('Woodstock Bistro', 'budget');
  assert.equal(
    explainUnmetRequirement({ slug: 'meal', label: 'Something to eat' }, [meal], [], 100),
    'The something to eat options found exceed your R100 budget.'
  );
});