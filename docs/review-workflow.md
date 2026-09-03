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
sourceName: string       # e.g. "Chess.com", "FIDE", "Chess Tournament Calendar"
sourceUrl: string         # always linked prominently in the article
lens: tournament-db | drama | historical-parallel | money-angle | community-pulse
continent: europe | asia | north-america | south-america | africa | oceania | global
selectionScore: number    # from scripts/selection.py -- why this story was picked
reviewStatus: draft | approved | published
socialCopy: string        # suggested post text for Phase 2 social automation

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
