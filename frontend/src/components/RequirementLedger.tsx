import React from 'react';
import type { IntentCoverageRead, UnderstandingRead } from '../types/planning';
import { explicitArea } from '../utils/planVoice';
import { IconInfo, IconAlertCircle } from './Icons';

/**
 * The requirement ledger.
 *
 * M17 works out, for every distinct thing the user asked for, whether the plan
 * actually contains something that proves it. This is that result, stated
 * plainly. The point of the panel is that a plan which misses something says so
 * in the same breath as it lists what it did find — "built around your
 * intention" is only honest if the misses are on the page.
 *
 * A covered requirement never appears without the stop that earned it.
 */

export type LedgerState = 'ok' | 'partial' | 'miss' | 'trade';

const MARKS: Record<LedgerState, string> = { ok: '✓', partial: '◐', miss: '×', trade: '!' };

function stateFor(item: { is_covered: boolean; status?: string }): LedgerState {
  if (item.is_covered) return 'ok';
  // The backend can report a partial match: something in the plan gestures at
  // the request without clearly satisfying it. That is not the same as missing.
  if (item.status && /partial/i.test(item.status)) return 'partial';
  return 'miss';
}

interface RequirementLedgerProps {
  coverage: IntentCoverageRead | null | undefined;
  understanding: UnderstandingRead | null | undefined;
  budgetMax: number | null;
  spent: number;
}

export const RequirementLedger: React.FC<RequirementLedgerProps> = ({
  coverage,
  understanding,
  budgetMax,
  spent,
}) => {
  const items = coverage?.items ?? [];
  const unmet = items.filter((item) => !item.is_covered);
  const area = explicitArea(understanding);

  // The constraints Dayform holds itself to. Each is shown only when it is
  // actually being met, so the list can never overstate the plan.
  const held: Array<{ glyph: string; label: string; detail: string; tone: LedgerState }> = [];
  if (area) {
    held.push({ glyph: '⌖', label: area, detail: 'Every stop is inside this area', tone: 'ok' });
  }
  if (budgetMax !== null) {
    const within = spent <= budgetMax;
    held.push({
      glyph: '⛁',
      label: `R${Math.round(budgetMax).toLocaleString('en-ZA')}`,
      detail: within
        ? `R${Math.round(spent).toLocaleString('en-ZA')} planned`
        : `R${Math.round(spent).toLocaleString('en-ZA')} planned — over`,
      tone: within ? 'ok' : 'miss',
    });
  }
  const groupSize = understanding?.people_count;
  if (groupSize && groupSize > 1) {
    held.push({ glyph: '⛉', label: `${groupSize} people`, detail: 'Sized for your group', tone: 'ok' });
  }
  const timeWindow = understanding?.time_window;
  if (timeWindow) {
    held.push({
      glyph: '⏱',
      label: timeWindow.charAt(0).toUpperCase() + timeWindow.slice(1),
      detail: 'Scheduled for this time window',
      tone: 'ok',
    });
  }
  const preferences = understanding?.preferences ?? [];
  if (preferences.length > 0) {
    held.push({
      glyph: '✦',
      label: preferences.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(', '),
      detail: 'Considered as soft preference',
      tone: 'ok',
    });
  }

  const headline =
    items.length === 0
      ? 'Checked against your constraints'
      : unmet.length === 0
        ? 'Everything you asked for is in here'
        : `${items.length - unmet.length} of ${items.length} of your asks are covered`;

  return (
    <section className="df-ledger" aria-labelledby="df-ledger-title">
      <header className="df-ledger-head">
        <h3 id="df-ledger-title" className="df-ledger-title">
          {headline}
        </h3>
        {unmet.length > 0 && (
          <p className="df-ledger-sub">
            I didn't quietly drop these. They're marked below with what I couldn't find.
          </p>
        )}
      </header>

      {items.length > 0 && (
        <ul className="df-ledger-list">
          {items.map((item) => {
            const state = stateFor(item);
            return (
              <li key={item.slug} className={`df-ledger-item is-${state}`}>
                <span className="df-ledger-mark" aria-hidden="true">{MARKS[state]}</span>
                <span className="df-ledger-name">{item.label}</span>
                {state === 'ok' && item.supported_by && item.supported_by.length > 0 && (
                  <span className="df-ledger-evidence">{item.supported_by[0]}</span>
                )}
                {state === 'miss' && (
                  <span className="df-ledger-evidence df-ledger-evidence--miss">
                    No verified option fits everything else you asked for
                  </span>
                )}
                {state === 'partial' && (
                  <span className="df-ledger-evidence df-ledger-evidence--partial">
                    Only loosely matched in this plan
                  </span>
                )}
                <span className="df-sr-only">
                  {state === 'ok' ? 'covered' : state === 'partial' ? 'partially covered' : 'not covered'}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {held.length > 0 && (
        <ul className="df-ledger-held">
          {held.map((row) => (
            <li key={row.label} className={`df-ledger-held-item is-${row.tone}`}>
              <span className="df-ledger-held-glyph" aria-hidden="true">{row.glyph}</span>
              <span className="df-ledger-held-label">{row.label}</span>
              <span className="df-ledger-held-detail">{row.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {unmet.length > 0 && (
        <p className="df-ledger-note">
          <IconAlertCircle size={13} />
          <span>
            These are real places, checked against real-world information. What is missing is real
            too: inside your area and budget, there was no{' '}
            {unmet.map((i) => i.label.toLowerCase()).join(' or ')} I could stand behind.
          </span>
        </p>
      )}

      {items.length === 0 && held.length === 0 && (
        <p className="df-ledger-note df-ledger-note--quiet">
          <IconInfo size={13} />
          <span>I'm still working out what you meant, so there is nothing to check yet.</span>
        </p>
      )}
    </section>
  );
};
