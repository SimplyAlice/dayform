/**
 * The ambient world around the plan.
 *
 * A small number of glyphs chosen from what the user actually asked for, so the
 * page around a beach plan is different from the page around a food plan. They
 * are atmosphere, not content: they are `aria-hidden`, they take no pointer
 * events, and they are switched off entirely under reduced motion and on
 * small screens. The count is deliberately low — a handful, drifting slowly at
 * varied depth — because the effect that reads as "a world" is the one that
 * doesn't decorate.
 */
interface AmbientLayerProps {
  /** The user's intention, used to pick the atmosphere. */
  intention?: string | null;
}

export function AmbientLayer({ intention: _intention }: AmbientLayerProps) {
  // Decorative floating background emojis disabled per Dayform visual polish pass
  return null;
}
