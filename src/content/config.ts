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
    // calendar aggregate pieces; the other five are picked by the AI per
    // news story, whichever fits best. Absent on a recap, which isn't
    // written through any one analytical lens.
    lens: z.enum(['tournament-db', 'drama', 'historical-parallel', 'money-angle', 'results', 'people']).optional(),
    // The site's primary browsing category. Calendar aggregates already
    // know their continent from ingestion; news stories get it inferred by
    // the AI at drafting time, falling back to "global" when no single
    // continent fits (e.g. a FIDE policy story with no regional angle).
    continent: z.enum(['europe', 'asia', 'north-america', 'south-america', 'africa', 'oceania', 'global']),
    selectionScore: z.number(),
    reviewStatus: z.enum(['draft', 'approved', 'published']),
    socialCopy: z.string().optional(),
    // Search-result summary (<=155 chars). Optional: older articles fall
    // back to an excerpt of the body.
    metaDescription: z.string().max(170).optional(),
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
    // A real, embeddable Lichess board for the one specific game a piece
    // centers on (see @@GAME_LOOKUP@@ in scripts/draft.py's prompt and
    // scripts/lichess_game.py) -- absent on every article that isn't
    // built around one specific game (the vast majority), and absent even
    // on ones that are when no confident match was found on Lichess.
    gameEmbed: z
      .object({
        url: z.string().url(),
      })
      .optional(),
    // Posts on X that the story's own source page embedded, stored as
    // plain text at draft time (see scripts/tweets.py) and rendered as
    // static quotes by TweetQuotes.astro -- the site never loads anything
    // from X, so a reader's browser only contacts it if they click through.
    // Reviewers delete an entry in the PR to drop a quote.
    tweetEmbeds: z
      .array(
        z.object({
          url: z.string().url(),
          author: z.string(),
          handle: z.string(),
          text: z.string(),
          date: z.string().optional(),
        })
      )
      .optional(),
  }).refine((data) => data.reviewStatus !== 'published' || data.image, {
    // Every article has a photo. The drafting pipeline guarantees one (a
    // committed fallback pool, see scripts/images.py), so this only trips on
    // a hand-written or hand-edited article -- caught here, at build time,
    // rather than shipping the SVG placeholder.
    message: 'A published article must have an image (see scripts/images.py fallback_image)',
    path: ['image'],
  }),
});

// Reference pages (players, events) are hand-curated and human-reviewed like
// articles, but they're evergreen: no source article, no lens. Facts in the
// frontmatter come from structured sources (FIDE, Wikipedia infoboxes, the
// organiser's own site); the body is the reviewed prose intro.
const players = defineCollection({
  type: 'content',
  schema: ({ image }) =>
    z.object({
      name: z.string(),
      // The permanent key: joins this page to the monthly FIDE top 100 table.
      fideId: z.string().regex(/^\d+$/),
      born: z.coerce.date().optional(),
      birthplace: z.string().optional(),
      federation: z.string(),
      title: z.string(),
      titleYear: z.number().optional(),
      peakRating: z.object({ rating: z.number(), month: z.string() }).optional(),
      // Full names (and common spellings) that mark an article as being about
      // this player. Full names only: surnames alone collide (Javokhir vs
      // Komil Sindarov).
      aliases: z.array(z.string()).default([]),
      highlights: z.array(z.string()).default([]),
      links: z.array(z.object({ label: z.string(), url: z.string().url() })).default([]),
      image: z.object({ src: image(), credit: z.string(), sourceUrl: z.string().url() }).optional(),
      reviewStatus: z.enum(['draft', 'published']),
      updatedDate: z.coerce.date(),
    }),
});

const events = defineCollection({
  type: 'content',
  schema: ({ image }) =>
    z.object({
      name: z.string(),
      summary: z.string(),
      category: z.enum(['world-title', 'elite', 'open', 'team', 'online']),
      frequency: z.string(),
      founded: z.number(),
      location: z.string(),
      format: z.string(),
      organizer: z.string().optional(),
      officialUrl: z.string().url().optional(),
      nextEdition: z
        .object({
          label: z.string(),
          start: z.coerce.date().optional(),
          end: z.coerce.date().optional(),
          location: z.string().optional(),
          // Every date shown needs a source and a last-checked day: dates get
          // announced late and moved.
          sourceUrl: z.string().url(),
          checked: z.coerce.date(),
        })
        .optional(),
      winners: z
        .array(z.object({ year: z.number(), names: z.array(z.string()), note: z.string().optional() }))
        .default([]),
      winnersSource: z.object({ label: z.string(), url: z.string().url() }).optional(),
      aliases: z.array(z.string()).default([]),
      image: z.object({ src: image(), credit: z.string(), sourceUrl: z.string().url() }).optional(),
      reviewStatus: z.enum(['draft', 'published']),
      updatedDate: z.coerce.date(),
    }),
});

export const collections = { articles, players, events };
