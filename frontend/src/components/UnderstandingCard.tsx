import React from 'react';
import type { PlanRead } from '../types/planning';
import { formatCurrency } from '../utils/itineraryBuilder';
import { explicitArea } from '../utils/planVoice';
import { IconInfo, IconCheck } from './Icons';
import { StageFrame } from './StageFrame';

interface UnderstandingCardProps {
  plan: PlanRead;
  budgetMax: number | null;
}

interface BlueprintRow {
  glyph: string;
  text: string;
  detail?: string;
}

/**
 * "I get it."
 *
 * The old version of this read as extracted database fields — four values in a
 * row with no sense of which one mattered. This is the same information
 * arranged the way a person would say it back: the things that must be true,
 * the things that would be nice, and the limits inside which all of it has to
 * happen. Nothing here is invented; every row comes from the understanding the
 * planner actually produced.
 */
export const UnderstandingCard: React.FC<UnderstandingCardProps> = ({ plan, budgetMax }) => {
  const u = plan.understanding;
  const groupSize = u?.people_count ?? plan.context?.group_size ?? 1;
  const area = explicitArea(u) ?? (u?.location_is_inferred ? null : u?.location ?? null);
  const budgetVal = u?.budget_amount ? Number(u.budget_amount) : budgetMax;

  /* ---- Must have: the experiences the user explicitly asked for ---- */
  const mustHave: BlueprintRow[] = [];
  const labels = u?.experience_requirement_labels ?? [];
  for (const label of labels) {
    mustHave.push({ glyph: '✦', text: label });
  }
  if (u?.time_window) {
    mustHave.push({ glyph: '◷', text: `${u.time_window[0].toUpperCase()}${u.time_window.slice(1)}` });
  }
  if (u?.date_spec) {
    mustHave.push({ glyph: '◷', text: u.date_spec });
  }
  if (u?.weather_context === 'raining' || u?.setting_preference === 'indoor') {
    mustHave.push({ glyph: '☂', text: 'Sheltered and indoors' });
  }
  if (u?.occasion) {
    const occasions: Record<string, string> = {
      date: 'A date',
      birthday: 'A birthday',
      celebration: 'A celebration',
      friends: 'With friends',
      casual_hangout: 'A casual catch-up',
      family: 'Family time',
      solo: 'On your own',
    };
    mustHave.push({ glyph: '✦', text: occasions[u.occasion] ?? u.occasion });
  }

  /* ---- Prefer: the qualities that would make it better ---- */
  const prefer: BlueprintRow[] = [];
  const preferenceWords: Record<string, string> = {
    casual: 'Relaxed and casual',
    nice: 'A lovely setting',
    romantic: 'Romantic',
    food_focused: 'Food worth the stop',
    aesthetic: 'Beautiful to look at',
    outdoors: 'Open air',
    cultural: 'Local culture',
  };
  for (const pref of u?.preferences ?? []) {
    prefer.push({ glyph: '◌', text: preferenceWords[pref] ?? pref.replace(/_/g, ' ') });
  }
  for (const descriptor of u?.semantic_descriptors ?? []) {
    prefer.push({ glyph: '◌', text: descriptor });
  }

  /* ---- Constraints: the walls the plan has to stay inside ---- */
  const constraints: BlueprintRow[] = [];
  if (groupSize > 1) constraints.push({ glyph: '⛉', text: `${groupSize} people` });
  if (area) constraints.push({ glyph: '⌖', text: `Stay in ${area}`, detail: 'Out-of-area venues are ruled out' });
  if (budgetVal !== null && budgetVal > 0) {
    constraints.push({
      glyph: '⛁',
      text: `${u?.budget_kind === 'approximate' ? 'Around' : 'At most'} ${formatCurrency(budgetVal)}`,
      detail: groupSize > 1 ? `about ${formatCurrency(Math.round(budgetVal / groupSize))} each` : undefined,
    });
  } else if (u?.budget_kind === 'preference') {
    constraints.push({ glyph: '⛁', text: 'Keep it affordable' });
  }
  if (u?.duration_limit_minutes) {
    constraints.push({ glyph: '◷', text: `About ${Math.round(u.duration_limit_minutes / 60)} hours` });
  }
  for (const excl of u?.exclusions ?? []) {
    const words: Record<string, string> = {
      no_alcohol: 'No alcohol',
      not_too_fancy: 'Nothing too formal',
      no_outdoors: 'Stay off the outdoors',
      no_clubs: 'No late nightlife',
      nothing_expensive: 'Nothing expensive',
    };
    constraints.push({ glyph: '⛔', text: words[excl] ?? `No ${excl.replace(/_/g, ' ')}` });
  }

  const sectionCount = [mustHave.length > 0, prefer.length > 0, constraints.length > 0].filter(Boolean).length;

  /* The emotional claim of this scene is that the sentence was understood, so
     the sentence and its resolution are in the same frame: the raw thought on
     top, the structure it became underneath. */
  return (
    <StageFrame
      stage={2}
      className="df-light df-light--soft df-understanding"
      kicker="I get it"
      title={
        <>
          Here’s what you <em>meant.</em>
        </>
      }
      lede="Your sentence, taken apart into the things that must be true, the things that would be nice, and the limits everything has to fit inside."
    >
      <blockquote className="df-transform-source">{plan.intention}</blockquote>

      <div className="df-transform-out df-stagger">
        {mustHave.length > 0 && (
          <div className="df-blueprint-group df-blueprint-group--must">
            <h3 className="df-blueprint-kicker">
              <span className="df-blueprint-rule" />
              Must have
            </h3>
            <ul className="df-blueprint-list">
              {mustHave.map((row, i) => (
                <li key={`${row.text}-${i}`} className="df-blueprint-row">
                  <span className="df-blueprint-glyph" aria-hidden="true">{row.glyph}</span>
                  <span className="df-blueprint-text">{row.text}</span>
                  {row.detail && <span className="df-blueprint-detail">{row.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {prefer.length > 0 && (
          <div className="df-blueprint-group df-blueprint-group--prefer">
            <h3 className="df-blueprint-kicker">
              <span className="df-blueprint-rule" />
              Prefer
            </h3>
            <ul className="df-blueprint-list">
              {prefer.map((row, i) => (
                <li key={`${row.text}-${i}`} className="df-blueprint-row">
                  <span className="df-blueprint-glyph" aria-hidden="true">{row.glyph}</span>
                  <span className="df-blueprint-text">{row.text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {constraints.length > 0 && (
          <div className="df-blueprint-group df-blueprint-group--constraint">
            <h3 className="df-blueprint-kicker">
              <span className="df-blueprint-rule" />
              Constraints
            </h3>
            <ul className="df-blueprint-list">
              {constraints.map((row, i) => (
                <li key={`${row.text}-${i}`} className="df-blueprint-row">
                  <span className="df-blueprint-glyph" aria-hidden="true">{row.glyph}</span>
                  <span className="df-blueprint-text">{row.text}</span>
                  {row.detail && <span className="df-blueprint-detail">{row.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <footer className="df-understanding-foot">
        <span className="df-understanding-foot-note">
          <IconCheck size={12} />
          {sectionCount === 1
            ? 'Everything here was checked against this.'
            : 'Everything here was checked against your constraints.'}
        </span>
        {u?.ambiguities && u.ambiguities.length > 0 && (
          <span className="df-understanding-foot-ambiguity">
            <IconInfo size={12} />
            {u.ambiguities.join(' · ')}
          </span>
        )}
      </footer>
    </StageFrame>
  );
};
