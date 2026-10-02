import assert from 'node:assert/strict';
import test from 'node:test';
import { transportPreferenceForMode } from './transportPreferences.ts';

test('explicit public transport selects the public transport control', () => {
  assert.equal(transportPreferenceForMode('public_transport'), 'public_transport');
  assert.equal(transportPreferenceForMode('PUBLIC_TRANSIT'), 'public_transport');
  assert.equal(transportPreferenceForMode('walk'), 'walking');
  assert.equal(transportPreferenceForMode(null), '');
});