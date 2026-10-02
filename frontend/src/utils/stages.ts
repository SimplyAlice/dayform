/**
 * The six scenes, in the order the user meets them.
 *
 * Kept apart from the component that renders them so that both the scene frame
 * and the running folio read from one list — there is no second place where a
 * stage could be defined slightly differently and quietly disagree.
 */

export type StageNumber = 1 | 2 | 3 | 4 | 5 | 6;

export interface StageMeta {
  number: StageNumber;
  name: string;
}

export const STAGES: readonly StageMeta[] = [
  { number: 1, name: 'The intention' },
  { number: 2, name: 'The understanding' },
  { number: 3, name: 'The intelligence' },
  { number: 4, name: 'The itinerary' },
  { number: 5, name: 'The adaptation' },
  { number: 6, name: 'The execution' },
] as const;

export function stageNumber(value: StageNumber): string {
  return String(value).padStart(2, '0');
}
