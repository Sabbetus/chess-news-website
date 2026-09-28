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

- **Current streak: 2 consecutive clean batches.**
- 2026-09-28: PR #49, the Olympiad gold/closing-ceremony batch, reviewed
  clean -- every medal, performance rating, trophy, and category prize
  checked against FIDE's and Chess.com's real coverage, including one
  name flagged for extra scrutiny (Ihor Samunenkov, board-four gold)
  confirmed genuine straight from FIDE's own article. All 5 internal
  links resolved. No fixes needed.
- 2026-09-27: PR #48, the weekly recap, reviewed clean -- all 15 internal
  links resolved to real published articles and every claim checked out
  sentence-by-sentence against its linked article's own body. No fixes
  needed.
- Last reset: 2026-09-27 (PR #47 -- a year range like "2024-2026" next to
  an "Olympiad" mention was misread as a match score, wrongly attaching a
  round-10 team-standings table to the FIDE Excellence Awards ceremony
  piece, an article with zero actual round results. Fixed the underlying
  scoreline regex -- see scripts/selection.py, _SCORELINE_RE -- rather than
  just editing the article. No article-content errors found this batch;
  both pieces checked out fact-for-fact against their real sources.)
- Previous reset: 2026-09-26 (PR #46 -- the drafting model conflated three
  separate Chess.com "3+0 Thursday" brackets into a single event and
  misattributed a mouse slip from an unrelated round-10 game as deciding
  the Carlsen-Nakamura tiebreak; that article also had an Olympiad
  team-standings table wrongly attached to it, unrelated to the event it
  covered. Also fixed a wrong player first name (Mukhiddin Madaminov,
  not Nodirbek) in a separate article, plus one over-length paragraph
  the automated fixup didn't clear.)
