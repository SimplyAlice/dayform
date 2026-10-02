import React from 'react';
import { STAGES, stageNumber, type StageNumber } from '../utils/stages';

/**
 * The running folio.
 *
 * Six scenes, always in the same order, and the user should be able to see
 * where they are without being told. This is deliberately not a checkout
 * stepper: no filled bars, no numbered circles, no "step 3 of 6". It is a
 * margin note in a book — a tick for what is behind you, a coral mark for
 * where you are, and nothing at all for what is still ahead.
 *
 * On a wide screen it lives in the left margin. When there is no margin to
 * live in, it becomes a single quiet line beneath the nav rather than
 * disappearing, because knowing where you are is not decoration.
 */
interface StageRailProps {
  current: StageNumber;
  /** The furthest scene the user has reached. Everything before it is behind. */
  reached?: StageNumber;
}

export const StageRail: React.FC<StageRailProps> = ({ current, reached = current }) => {
  return (
    <nav className="df-rail" aria-label="Your day, stage by stage">
      {STAGES.map((stage) => {
        const num = stageNumber(stage.number);
        const isCurrent = stage.number === current;
        const isDone = stage.number < reached;
        const state = isCurrent ? 'is-current' : isDone ? 'is-done' : 'is-ahead';

        return (
          <span
            key={num}
            className={`df-rail-item ${state}`}
            // The visible label is short, so the full scene name is carried for
            // anything reading this as text rather than seeing it.
            aria-label={`${num} ${stage.name}${isCurrent ? ', current stage' : ''}`}
            {...(isCurrent ? { 'aria-current': 'step' as const } : {})}
          >
            <span className="df-rail-tick" aria-hidden="true" />
            <span className="df-rail-num">{num}</span>
            <span className="df-rail-name">{stage.name}</span>
          </span>
        );
      })}
    </nav>
  );
};

export default StageRail;
