# Chess News

A curated chess news aggregator: original/companion pieces on select
stories, each linked to its source, drafted with AI assistance and
reviewed by a human before publishing. See
`/root/.claude/plans/summary-chess-news-aggregator-sparkling-rossum.md`
(or ask for the plan) for the full concept and phasing.

## Stack

- [Astro](https://astro.build) static site, content collections for
  articles (`src/content/articles/`, schema in `src/content/config.ts`).
- Python pipeline scripts (`scripts/`) for ingestion, selection, and AI
  drafting, run on a schedule via GitHub Actions
  (`.github/workflows/pipeline.yml`).
- Deploys to GitHub Pages on merge to `main`
  (`.github/workflows/deploy.yml`).

## Local development

```bash
npm install
npm run dev       # http://localhost:4321
npm run build     # -> dist/
npm run preview   # serve the built dist/
```

## Pipeline scripts

```bash
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt

.venv/bin/python scripts/ingest.py   # -> data/candidates.json
.venv/bin/python scripts/select.py   # -> data/selected.json
ANTHROPIC_API_KEY=... .venv/bin/python scripts/draft.py  # -> src/content/articles/*.md
```

`draft.py` requires an `ANTHROPIC_API_KEY`. In CI this is read from the
`ANTHROPIC_API_KEY` repository secret (add it under Settings → Secrets and
variables → Actions before enabling the scheduled pipeline).

## Review workflow

See `docs/review-workflow.md`. Short version: the pipeline opens a PR per
run; nothing goes live until an article's `reviewStatus` frontmatter is
`published` **and** the PR is merged.

## Phasing

Phase 1 (current): scaffold, ingestion, selection, AI drafting, PR review,
deploy. Phase 2 (later, once the site has a name/domain): Google
Analytics, the Nordic Chess Festival banner (currently a plain footer
link), and social auto-posting (X, Facebook).
