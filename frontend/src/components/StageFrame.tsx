import React from 'react';
import { STAGES, stageNumber, type StageNumber } from '../utils/stages';

/**
 * A scene.
 *
 * Dayform is six scenes long, and a scene is not a container — it is a beat.
 * It carries a number, a name, one large statement, and then whatever is the
 * single most important thing in that moment. Everything else on the page is
 * held at a smaller scale so the eye moves in editorial steps instead of
 * scanning a column of peers.
 *
 * The number is deliberately enormous and almost invisible, sitting behind the
 * kicker like a folio in a magazine. It says where you are without competing
 * for attention with what the scene is saying.
 */
interface StageFrameProps {
  stage: StageNumber;
  /** The one large statement. This is what the scene is for. */
  title: React.ReactNode;
  /** Optional supporting sentence under the statement. */
  lede?: React.ReactNode;
  /** Optional quiet footer, for colophons and provenance. */
  foot?: React.ReactNode;
  /** An optional eyebrow that overrides the stage name. */
  kicker?: string;
  /** Whether to hide the stage number watermark and kicker */
  hideStageMeta?: boolean;
  /** Extra class for scene-specific layout. */
  className?: string;
  as?: 'h1' | 'h2' | 'h3';
  children?: React.ReactNode;
}

export const StageFrame: React.FC<StageFrameProps> = ({
  stage,
  title,
  lede,
  foot,
  kicker,
  hideStageMeta = false,
  className = '',
  as: Heading = 'h2',
  children,
}) => {
  const meta = STAGES.find((s) => s.number === stage);

  return (
    <section
      className={`df-scene ${className}`.trim()}
      data-stage={stageNumber(stage)}
      aria-label={meta?.name}
    >
      <header className="df-scene-head">
        {!hideStageMeta && (
          <p className="df-scene-num" aria-hidden="true">
            {stageNumber(stage)}
          </p>
        )}
        {!hideStageMeta && <p className="df-scene-kicker">{kicker ?? meta?.name}</p>}
        <Heading className="df-scene-title">{title}</Heading>
        {lede && <p className="df-scene-lede">{lede}</p>}
      </header>

      {children}

      {foot && <div className="df-scene-foot">{foot}</div>}
    </section>
  );
};

export default StageFrame;
