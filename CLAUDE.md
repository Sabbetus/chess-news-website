# Standing rules for this repo

- **"Merge [the article/PR] to main" means publish it.** An article PR
  merging to main does NOT make it go live by itself -- the site only
  renders `reviewStatus: "published"` articles (see
  `docs/review-workflow.md`). Before merging an article PR (as opposed to
  a pure pipeline/infra-code PR with no article files), flip every article
  file's `reviewStatus` from `draft` to `published` first, as part of the
  same merge action -- don't wait for a separate explicit "publish" ask.
  (Caught live 2026-09-20: PR #29's weekly recap was merged without this
  step and silently never went live.)

- **Article review means checking every claim/link in the piece, not a
  sample of them.** Spot-checking one or two paragraphs and generalizing
  ("looks fine") is not a review -- verify every fact, every date, and
  every internal `/articles/<slug>/` link against its real source
  individually, for the whole piece, every time. (Caught live 2026-09-20:
  reviewing the weekly recap, a stale linked article was found and
  removed, but the paragraph right after it -- with the exact same
  problem -- was missed because the rest of the piece wasn't actually
  checked, just assumed fine after fixing the first spot.)

## Clean-review streak tracker

The user's long-term plan: once a full week of daily batches goes by with
no edits needed during review, they'll stop reviewing before publishing.
Any batch that needs even one fix (a broken link, a factual correction,
anything) resets the streak to zero -- it doesn't matter how minor.
Update this after every batch review.

- **Current streak: 0 consecutive clean batches.**
- Last reset: 2026-09-24 (PR #33 -- a broken internal link, title-guessed
  instead of using the real given slug, plus 4 over-length paragraphs the
  automated fixup didn't fully clear; see commit history around that date
  for the pipeline fix -- check_article_links() -- that was also made).
