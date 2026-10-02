export function transportPreferenceForMode(mode?: string | null): string {
  const normalized = mode?.trim().toLowerCase();
  if (!normalized) return '';
  if (['public_transport', 'public_transit', 'transit'].includes(normalized)) return 'public_transport';
  if (['walk', 'walking'].includes(normalized)) return 'walking';
  if (['bus', 'myciti'].includes(normalized)) return 'myciti';
  if (['train', 'rail', 'metrorail'].includes(normalized)) return 'metrorail';
  if (normalized === 'uber' || normalized === 'bolt') return normalized;
  return '';
}