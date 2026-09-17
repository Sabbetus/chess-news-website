import { defineCollection, z } from 'astro:content';

// Frontmatter is the source of truth for pipeline/review state, not git/PR
// state alone — this lets a future admin UI read/write the same data
// instead of needing a new data model.
const articles = defineCollection({
  type: 'content',
  schema: ({ image }) => z.object({
    title: z.string(),
    // "article" (the default) is every normal news/aggregate piece, sourced
    // from one external story or the tournament calendar. "recap" is the
    // weekly roundup, synthesized from that week's own published articles
    // rather than an external source -- it skips the daily grid entirely
    // and gets its own homepage section and archive instead (see
    // index.astro and recaps.astro).
    type: z.enum(['article', 'recap']).default('article'),
    publishDate: z.coerce.date(),
    // Set by hand when a published piece is substantively corrected, so
    // search engines see a real dateModified rather than assuming the
    // article has never been touched. Absent on anything unchanged since
    // publication, where dateModified correctly equals datePublished.
    updatedDate: z.coerce.date().optional(),
    // Absent on a recap -- it has no single external source, it's a
    // roundup of that week's own articles.
    sourceName: z.string().optional(),
    sourceUrl: z.string().url().optional(),
    // Set when selection.py recognized another outlet's coverage of this
    // same event and merged the two into one piece (see
    // merge_duplicate_stories in scripts/selection.py) rather than
    // publishing the same story twice. sourceName/sourceUrl above stay
    // the primary source; this lists every other outlet the piece also
    // draws on.
    additionalSources: z
      .array(
        z.object({
          sourceName: z.string(),
          sourceUrl: z.string().url(),
        })
      )
      .optional(),
    // The analytical angle the piece is written through -- shapes the
    // drafting prompt, shown as a secondary label (not the site's primary
    // category, that's `continent`). tournament-db is reserved for the
    // calendar aggregate pieces; the other four are picked by the AI per
    // news story, whichever fits best. Absent on a recap, which isn't
    // written through any one analytical lens.
    lens: z.enum(['tournament-db', 'drama', 'historical-parallel', 'money-angle', 'upsets']).optional(),
    // The site's primary browsing category. Calendar aggregates already
    // know their continent from ingestion; news stories get it inferred by
    // the AI at drafting time, falling back to "global" when no single
    // continent fits (e.g. a FIDE policy story with no regional angle).
    continent: z.enum(['europe', 'asia', 'north-america', 'south-america', 'africa', 'oceania', 'global']),
    selectionScore: z.number(),
    reviewStatus: z.enum(['draft', 'approved', 'published']),
    socialCopy: z.string().optional(),
    // A real photo/logo sourced from Wikimedia Commons and downloaded once
    // at draft time (see scripts/images.py), used only when a
    // license-clean, reasonably-relevant match was found -- absent
    // whenever it wasn't, in which case ArticleThumb falls back to its SVG
    // placeholder. `src` is a relative path to the locally-stored master
    // (./_images/<slug>.webp, a sibling of every article file) resolved by
    // Astro's image() helper into a real typed asset -- every on-site
    // display size and the social-card crop are generated from that one
    // file by Astro's own build-time pipeline, nothing is hotlinked.
    image: z
      .object({
        src: image(),
        credit: z.string(),
        sourceUrl: z.string().url(),
      })
      .optional(),
  }),
});

export const collections = { articles };
