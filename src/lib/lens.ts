export type Lens = 'tournament-db' | 'drama' | 'historical-parallel' | 'money-angle' | 'community-pulse';

export const LENS_META: Record<Lens, { label: string; className: string }> = {
  'tournament-db': { label: 'OTB Tournaments', className: 'tournament' },
  drama: { label: 'Drama Angle', className: 'drama' },
  'historical-parallel': { label: 'Historical Parallel', className: 'historical' },
  'money-angle': { label: 'Money Angle', className: 'money' },
  'community-pulse': { label: 'Community Pulse', className: 'community' },
};

// One piece glyph per lens so thumbnails aren't visually identical across a
// page full of cards -- purely decorative, not meaningful per-article.
const LENS_PIECES: Record<Lens, string[]> = {
  'tournament-db': ['♟', '♙'],
  drama: ['♛', '♕'],
  'historical-parallel': ['♔', '♚'],
  'money-angle': ['♘', '♞'],
  'community-pulse': ['♖', '♜'],
};

export function pieceForLens(lens: Lens, seed: number): string {
  const pieces = LENS_PIECES[lens];
  return pieces[seed % pieces.length];
}
