import { useEffect, useState } from 'react';
import type { StageNumber } from '../utils/stages';

/**
 * Which of the six scenes the reader is actually standing in.
 *
 * The plan tells us how far the *product* has got, which is not the same thing
 * as where the *person* is: they can scroll back up to the understanding after
 * the itinerary is built. A progress indicator that only moves forward is not
 * telling you where you are, so this watches the scenes themselves and reports
 * the one under the reading line.
 *
 * The reading line sits above the middle rather than at it. A scene that is
 * merely entering from the bottom of the screen has not been read yet, and
 * waiting for its top to cross the centre makes the folio feel late.
 */
const READING_LINE = 0.38;

function stageFromScenes(scenes: HTMLElement[]): StageNumber | null {
  if (scenes.length === 0) return null;

  const line = window.innerHeight * READING_LINE;
  let current: StageNumber | null = null;

  for (const scene of scenes) {
    if (scene.getBoundingClientRect().top <= line) {
      const stage = Number(scene.getAttribute('data-stage'));
      if (Number.isFinite(stage)) current = stage as StageNumber;
    } else {
      break;
    }
  }

  // Above the first scene, the reader is in the scene we are about to enter.
  return current ?? (Number(scenes[0].getAttribute('data-stage')) as StageNumber);
}

export function useActiveStage(fallback: StageNumber): StageNumber {
  // Seeded with the fallback so the folio is honest before the first measure.
  // After that the scenes are the only thing that moves the marker, which
  // includes whenever the story itself changes shape — a new plan or a save
  // both add and remove scenes, and the observer below notices.
  const [active, setActive] = useState<StageNumber>(fallback);

  useEffect(() => {
    let frame = 0;

    const measure = () => {
      frame = 0;
      const scenes = Array.from(
        document.querySelectorAll<HTMLElement>('.df-scene[data-stage]'),
      );
      const stage = stageFromScenes(scenes);
      if (stage !== null) setActive(stage);
    };

    const schedule = () => {
      if (frame === 0) frame = window.requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });

    // Scenes appear and disappear as the plan is built, so the set being
    // measured changes without the page scrolling. Observe those changes.
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      observer.disconnect();
    };
  }, []);

  return active;
}
