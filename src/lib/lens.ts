export type Lens = 'tournament-db' | 'nordic-angle' | 'organizer-pov';

export const LENS_META: Record<Lens, { label: string; className: string }> = {
  'tournament-db': { label: 'Tournament DB', className: 'tournament' },
  'nordic-angle': { label: 'Nordic Angle', className: 'nordic' },
  'organizer-pov': { label: "Organizer's Desk", className: 'organizer' },
};

// One piece glyph per lens so thumbnails aren't visually identical across a
// page full of cards -- purely decorative, not meaningful per-article.
const LENS_PIECES: Record<Lens, string[]> = {
  'tournament-db': ['♟', '♙'],
  'organizer-pov': ['♔', '♘', '♖'],
  'nordic-angle': ['♛', '♕'],
};

export function pieceForLens(lens: Lens, seed: number): string {
  const pieces = LENS_PIECES[lens];
  return pieces[seed % pieces.length];
}
