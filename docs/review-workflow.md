# Review workflow

Every article starts life as an AI-drafted Markdown file in
`src/content/articles/`, written by the daily pipeline
(`.github/workflows/pipeline.yml` → `scripts/ingest.py` →
`scripts/selection.py` → `scripts/draft.py`). Nothing the pipeline writes
appears on the live site immediately: the site only lists/renders articles
where frontmatter `reviewStatus: "published"` (see
`src/pages/index.astro` and `src/pages/articles/[...slug].astro`).

## Frontmatter fields (the source of truth)

```yaml
title: string
publishDate: date
sourceName: string       # e.g. "Chess.com", "FIDE", "ChessBase", "Chess Tournament Calendar"
sourceUrl: string         # always linked prominently in the article
additionalSources:        # only present when scripts/selection.py detected another
  - sourceName: string    # outlet covering the same event and merged it into one
    sourceUrl: string      # piece instead of publishing the story twice -- both get
                            # credited in the byline
lens: tournament-db | drama | historical-parallel | money-angle | results
continent: europe | asia | north-america | south-america | africa | oceania | global
selectionScore: number    # from scripts/selection.py -- why this story was picked
reviewStatus: draft | approved | published
socialCopy: string        # suggested post text for Phase 2 social automation
gameEmbed:                 # only present when the piece centers on one specific
  url: string              # game AND scripts/lichess_game.py found a confident
                            # match on Lichess -- absent on most articles
tweetEmbeds:               # only present when the source page(s) embedded posts
  - url, author, handle,   # on X from a person (not an institution) -- stored as
    text, date             # plain text and rendered as static quotes under the
                            # story; the site never loads anything from X.
                            # Delete an entry in the PR to drop a quote.

# Calendar aggregate articles (see below) also carry, for reviewer context
# only -- stripped from the built site's data, visible only in the raw file:
aggregateKind: calendar-biggest | calendar-comingup
continentName: string
monthLabel: string
totalTracked: number
```

`continent` is the site's primary browsing category (nav links, `/continent/<slug>/`
pages). `lens` is a secondary "analytical angle" label shown on the article
itself -- it shapes the drafting prompt but isn't a nav category. Calendar
aggregates are always `lens: tournament-db` with a known `continent` from
ingestion; news articles get both inferred by the model at drafting time
(see `scripts/draft.py`).

**Photos.** Every article has one, and the build fails a published article that
doesn't (a content-schema check in `src/content/config.ts`). The drafting
pipeline searches Wikimedia Commons from the most specific subject down; if
that finds nothing it falls back to `scripts/fallback_photos.json`, a small
committed pool of object-only chess photos (boards and pieces, no
identifiable people), so there is always a license-clean photo. A story about
a person (the People lens) whose subject has no photo goes straight to that
pool rather than showing some other player's face, and an outlet's logo is
used as a photo only when the outlet is the subject of the story. Reviewers
can swap any photo by editing the article's `image` block.

**ChessBase and the People lens.** ChessBase (`en.chessbase.com/feed`) is the
third news source, added for interviews, profiles and columns the other two
rarely run. Its feed only carries a lede paragraph, so ingestion fetches each
article's full text (`scripts/article_text.py`); a page with under 800
characters of text (typically a video-only interview, which is just a YouTube
embed) is skipped, and ChessBase's own product marketing, puzzle columns and
"-- Live!" stubs are vetoed in selection. Interviews and profiles are drafted
through the `people` lens. Selection orders three story types on purpose:
major tournament results (score at or above 90), then those features (80-89),
then governance elections (79 or below), each clamped into its band
(`scoreBreakdown.bandAdjustment` shows the clamp). Features and election
stories never merge with a different kind of story.

**Reviewing `tweetEmbeds`.** These are picked automatically (scripts/tweets.py):
every post the story's own source page embedded, minus institutional accounts
(federations, events, outlets), at most three. Check that each quote is
actually about this story and is a person you're comfortable quoting; delete
anything else. The text is reproduced verbatim from X's public oEmbed, so a
reader can click through to verify it.

**Fan buzz.** `scoreBreakdown.fanBuzz` in `data/selected.json` (0, 5 or 10) is
a small scoring nudge for candidates whose headline names someone that
r/chess's top posts of the day are also about (scripts/trends.py). It only
nudges ranking -- nothing from Reddit is published -- and is 0 whenever the
Reddit fetch failed or `data/trends.json` is older than 36 hours.

`reviewStatus` is deliberately kept as article-level data, not something
implied only by "which PR is open" -- this is what lets an admin UI be
added later without a rework: it would just read/write this same field
instead of needing a new data model.

## Reviewing a batch

1. The pipeline opens one PR per run (see `pipeline.yml`), containing new
   draft `.md` files plus the updated `data/*.json` pipeline state
   (candidates considered, what was selected and why).
2. Open the PR's "Files changed" tab. For each article, check:
   - The source link is correct and the piece doesn't misrepresent it.
   - No fabricated facts, quotes, or statistics (the drafting prompt tells
     Claude to omit anything it isn't sure of, but verify).
   - The lens is actually applied (real analysis, not a reworded summary).
3. To edit a draft: either edit the file directly in the PR (GitHub's web
   editor) or check out the branch locally and edit, then push.
4. To approve and publish: change that article's `reviewStatus` from
   `draft` to `published` (via `approved` first if you want a distinct
   "reviewed, not yet live" state), then merge the PR. Merging triggers
   `deploy.yml`, which builds and deploys the site -- so only the articles
   whose frontmatter says `published` actually go live.
5. To reject a draft: delete its file from the PR (or leave it out of the
   merge by editing the branch) rather than merging it with `draft` status
   left in place -- a `draft` article sitting in `main` is harmless (it
   won't render), but keeping the repo clean makes future batches easier
   to review.

## Not yet wired up (Phase 2)

- Social auto-posting from `socialCopy` (fires on deploy, not on draft, so
  nothing posts before you've approved it).
- Google Analytics.
- Nordic Chess Festival banner (currently just a footer text link).
