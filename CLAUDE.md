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
- 2026-10-01: PR #52 needed fixes in all four drafts (streak stays at 0).
  Turlov interview: an unrelated FIDE schools-tournament report was merged
  in (matched on sentence-start words "What", "They") and got its own
  section; the American Chess Magazine interview was credited to ChessBase,
  which only republished it. Kasparov: headline said "Named" where the
  source says prosecutors haven't named him, plus our own dot-connecting
  on the alleged plot. Polgar: a guess stated as fact. Calendar piece:
  wrong entry/format counts, invented event descriptors, "no city is given
  in the data", and a portrait of an unrelated arbiter as its photo.
  Fixed at the source: the fact-check pass now covers headline, social
  copy and meta, and calendar pieces (against their data, with counts
  precomputed); guesses stated as fact get flagged or removed, while
  flagged speculation and reasonable readings stay (user's call); no
  speculation on allegations; extra sources about a different story are
  ignored; sentence-start words no longer count as names when merging;
  calendar photos only match tournament names, else a neutral image.
- 2026-09-30: PR #51 needed fixes (streak stays at 0). Two of four
  drafts dropped: a ChessBase round-10 Olympiad report that went stale
  once the event ended (we'd already published the gold result), and the
  Uzbekistan winners' interview, published the day before from the same
  URL under a headline the title-based duplicate check couldn't match.
  The Wesley So Titled Tuesday piece carried an unrelated merged source
  (London Classic) and credited So's own tweet to Chess.com; fixed. The
  Bodhana Sivanandan piece checked out in full. Fixed at the source:
  coverage.py now drops any candidate whose URL is already a source of a
  published article, before the model check. Still open: no rule yet for
  stale round reports of an event we've already closed out.
- 2026-09-29: PR #50 needed fixes (streak reset). Chess.com's RSS
  teaser is cut to 250 characters, and the drafts were written from it:
  a Bullet Brawl piece shipped a cut-off name ("GM Oleksa...") plus
  reader-facing talk about "the excerpt we had", and a Total Chess piece
  duplicated FIDE's article from four days earlier while wrongly claiming
  the format was unknown. First batch on Sonnet 5.5. Fixed at the
  source: ingest.py now fetches full text for truncated teasers, and
  coverage.py drops stories already covered in the last week. Dropped
  the duplicate, rewrote the Bullet Brawl piece from the full article.
  (Adding the 68-career-wins figure, and keeping the premove line as
  original color, were not counted against the streak.)
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
- Last reset: 2026-10-01 (PR #52, see above).
- Earlier resets: 2026-09-30 (PR #51); 2026-09-29 (PR #50); 2026-09-27 (PR #47 -- a year range like "2024-2026" next to
  an "Olympiad" mention was misread as a match score, wrongly attaching a
  round-10 team-standings table to the FIDE Excellence Awards ceremony
  piece, an article with zero actual round results. Fixed the underlying
  scoreline regex -- see scripts/selection.py, _SCORELINE_RE -- rather than
  just editing the article. No article-content errors found this batch;
  both pieces checked out fact-for-fact against their real sources.)
