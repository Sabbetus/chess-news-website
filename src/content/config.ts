import { defineCollection, z } from 'astro:content';

// Frontmatter is the source of truth for pipeline/review state, not git/PR
// state alone — this lets a future admin UI read/write the same data
// instead of needing a new data model.
const articles = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    publishDate: z.coerce.date(),
    sourceName: z.string(),
    sourceUrl: z.string().url(),
    // The analytical angle the piece is written through -- shapes the
    // drafting prompt, shown as a secondary label (not the site's primary
    // category, that's `continent`). tournament-db is reserved for the
    // calendar aggregate pieces; the other four are picked by the AI per
    // news story, whichever fits best.
    lens: z.enum(['tournament-db', 'drama', 'historical-parallel', 'money-angle', 'community-pulse']),
    // The site's primary browsing category. Calendar aggregates already
    // know their continent from ingestion; news stories get it inferred by
    // the AI at drafting time, falling back to "global" when no single
    // continent fits (e.g. a FIDE policy story with no regional angle).
    continent: z.enum(['europe', 'asia', 'north-america', 'south-america', 'africa', 'oceania', 'global']),
    selectionScore: z.number(),
    reviewStatus: z.enum(['draft', 'approved', 'published']),
    socialCopy: z.string().optional(),
    // A real photo/logo sourced from Wikimedia Commons (see scripts/images.py),
    // used only when a license-clean, reasonably-relevant match was found --
    // absent whenever it wasn't, in which case ArticleThumb falls back to its
    // SVG placeholder.
    image: z
      .object({
        url: z.string().url(),
        credit: z.string(),
        sourceUrl: z.string().url(),
      })
      .optional(),
  }),
});

export const collections = { articles };
