export type Lens = 'tournament-db' | 'drama' | 'historical-parallel' | 'money-angle' | 'community-pulse';

export const LENS_META: Record<Lens, { label: string; className: string; description: string }> = {
  'tournament-db': {
    label: 'OTB Tournaments',
    className: 'tournament',
    description: 'Original reporting drawn from Chess Tournament Calendar’s own tournament database.',
  },
  drama: {
    label: 'Controversy',
    className: 'drama',
    description: 'Scandal, conflict, and the fallout when chess politics gets messy.',
  },
  'historical-parallel': {
    label: 'Historical Parallel',
    className: 'historical',
    description: 'Today’s story set against a genuine parallel from chess history.',
  },
  'money-angle': {
    label: 'Money',
    className: 'money',
    description: 'Prize funds, sponsorship, and where the money in chess is actually moving.',
  },
  'community-pulse': {
    label: 'Community Pulse',
    className: 'community',
    description: 'How players, streamers, and fans are actually reacting, grounded in real search.',
  },
};

// Nav/listing order -- roughly how often each lens gets used.
export const LENS_ORDER: Lens[] = ['drama', 'historical-parallel', 'money-angle', 'community-pulse', 'tournament-db'];

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
