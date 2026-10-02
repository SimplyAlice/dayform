import React, { useState } from 'react';
import type { DecisionCandidateRead, OrchestratedPlanRead, UnderstandingRead } from '../types/planning';
import { buildConstraintTrace, type TraceConstraint } from '../utils/intelligence';

/**
 * Scene 03 — the intelligence, made visible.
 *
 * The temptation with a scene like this is to animate something thinking. That
 * would be theatre: a user would watch a bar move and learn nothing about
 * whether the product is any good.
 *
 * So this shows the actual constraint ladder instead — the checks the engine
 * really ran, in the order it really runs them, each with the count of venues
 * that passed and the count that did not, and the engine's own sentences
 * available underneath. A day that fails three of the five constraints looks
 * like a day that failed three of the five constraints, because it was one.
 */
interface IntelligenceTraceProps {
  candidates: DecisionCandidateRead[];
  orchestrated: OrchestratedPlanRead | null | undefined;
  understanding: UnderstandingRead | null | undefined;
  budgetMax: number | null;
}

function TraceRow({ row }: { row: TraceConstraint }) {
  const [open, setOpen] = useState(false);
  const total = row.passed + row.failed;
  const passPct = total > 0 ? (row.passed / total) * 100 : 0;
  const failPct = total > 0 ? (row.failed / total) * 100 : 0;

  return (
    <div className="df-trace-row">
      <p className="df-trace-constraint">
        <span className="df-trace-glyph" aria-hidden="true">
          {row.glyph}
        </span>
        {row.name}
      </p>

      <p className="df-trace-verdict">{row.verdict}</p>

      <p className="df-trace-counts">
        {row.passed > 0 && (
          <span className="df-trace-count is-pass">
            ✓ {row.passed}
          </span>
        )}
        {row.failed > 0 && (
          <span className="df-trace-count is-fail">
            × {row.failed}
          </span>
        )}
      </p>

      {total > 1 && (
        <div
          className="df-trace-bar"
          role="img"
          aria-label={`${row.passed} passed, ${row.failed} did not`}
        >
          <span className="df-trace-bar-pass" style={{ width: `${passPct}%` }} />
          <span className="df-trace-bar-fail" style={{ width: `${failPct}%` }} />
        </div>
      )}

      {row.evidence.length > 0 && (
        <div className="df-trace-evidence">
          <button
            type="button"
            className="df-trace-more"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            {open ? 'Hide the detail' : `Why — ${row.evidence.length} checks`}
          </button>
          {open && (
            <ul className="df-trace-evidence-list">
              {row.evidence.map((line, i) => (
                <li key={`${line}-${i}`}>{line}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export const IntelligenceTrace: React.FC<IntelligenceTraceProps> = ({
  candidates,
  orchestrated,
  understanding,
  budgetMax,
}) => {
  const rows = buildConstraintTrace(candidates, orchestrated, understanding, budgetMax);

  if (rows.length === 0) return null;

  return (
    <div className="df-trace">
      {rows.map((row) => (
        <TraceRow key={row.key} row={row} />
      ))}
      <p className="df-trace-foot df-support">
        Every line above is a check the engine actually ran. Where a count is zero, that is a
        constraint it could not satisfy — not one it skipped.
      </p>
    </div>
  );
};

export default IntelligenceTrace;
