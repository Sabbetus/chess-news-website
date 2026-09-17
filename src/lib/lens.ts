export type Lens = 'tournament-db' | 'drama' | 'historical-parallel' | 'money-angle' | 'upsets';

export const LENS_META: Record<Lens, { label: string; className: string; description: string }> = {
  'tournament-db': {
    label: 'OTB Tournaments',
    className: 'tournament',
    description: 'Original reporting drawn from Chess Tournament Calendar’s tournament database.',
  },
  drama: {
    label: 'Controversy',
    className: 'drama',
    description: 'Scandal, conflict, and the fallout when chess politics gets messy.',
  },
  'historical-parallel': {
    label: 'History',
    className: 'historical',
    description: 'Today’s story set against a genuine parallel from chess history.',
  },
  'money-angle': {
    label: 'Money',
    className: 'money',
    description: 'Prize funds, sponsorship, and where the money in chess is actually moving.',
  },
  upsets: {
    label: 'Upsets',
    className: 'upsets',
    description: 'Shock results and blunders: how surprising they really were, and what they change going forward.',
  },
};

// Nav/listing order.
export const LENS_ORDER: Lens[] = ['money-angle', 'historical-parallel', 'drama', 'upsets', 'tournament-db'];

// URL slugs, kept separate from the Lens type itself -- the type value is
// also the content-schema key stored in every article's frontmatter, which
// isn't worth touching just to get a cleaner URL. Slugs match the current
// display labels (money-angle -> money, historical-parallel -> history,
// drama -> controversy) rather than leaking the internal key into URLs.
export const LENS_SLUGS: Record<Lens, string> = {
  drama: 'controversy',
  'historical-parallel': 'history',
  'money-angle': 'money',
  upsets: 'upsets',
  'tournament-db': 'otb-tournaments',
};

export const SLUG_TO_LENS: Record<string, Lens> = Object.fromEntries(
  (Object.entries(LENS_SLUGS) as [Lens, string][]).map(([lens, slug]) => [slug, lens])
);

// One piece glyph per lens so thumbnails aren't visually identical across a
// page full of cards -- purely decorative, not meaningful per-article.
const LENS_PIECES: Record<Lens, string[]> = {
  'tournament-db': ['♟', '♙'],
  drama: ['♛', '♕'],
  'historical-parallel': ['♔', '♚'],
  'money-angle': ['♘', '♞'],
  upsets: ['♖', '♜'],
};

export function pieceForLens(lens: Lens, seed: number): string {
  const pieces = LENS_PIECES[lens];
  return pieces[seed % pieces.length];
}
