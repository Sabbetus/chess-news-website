export type Lens = 'tournament-db' | 'drama' | 'historical-parallel' | 'money-angle' | 'results';

export const LENS_META: Record<Lens, { label: string; className: string; description: string }> = {
  'tournament-db': {
    label: 'OTB Tournaments',
    className: 'tournament',
    description: 'Over the board (OTB) classical and rapid tournaments from around the world: the highlights from the past, and what’s coming up next. Sourced from Chess Tournament Calendar.',
  },
  drama: {
    label: 'Controversy',
    className: 'drama',
    description: 'Cheating accusations, disputes, messy politics and the fights that go public.',
  },
  'historical-parallel': {
    label: 'History',
    className: 'historical',
    description: 'Today’s story set against a genuine parallel from chess history.',
  },
  'money-angle': {
    label: 'Money',
    className: 'money',
    description: 'Prize money, sponsors, and the deals behind them.',
  },
  results: {
    label: 'Results',
    className: 'results',
    description: 'The scores that mattered, from shocks and comebacks to who’s on top.',
  },
};

// Nav/listing order.
export const LENS_ORDER: Lens[] = ['results', 'historical-parallel', 'money-angle', 'drama', 'tournament-db'];

// URL slugs, kept separate from the Lens type itself -- the type value is
// also the content-schema key stored in every article's frontmatter, which
// isn't worth touching just to get a cleaner URL. Slugs match the current
// display labels (money-angle -> money, historical-parallel -> history,
// drama -> controversy) rather than leaking the internal key into URLs.
export const LENS_SLUGS: Record<Lens, string> = {
  drama: 'controversy',
  'historical-parallel': 'history',
  'money-angle': 'money',
  results: 'results',
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
  results: ['♖', '♜'],
};

export function pieceForLens(lens: Lens, seed: number): string {
  const pieces = LENS_PIECES[lens];
  return pieces[seed % pieces.length];
}
