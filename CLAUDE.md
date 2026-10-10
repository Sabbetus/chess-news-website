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

- **Judge our own additions on whether they are sound, not on whether
  the source says them.** Analysis, chess explanation and background the
  drafter adds are meant to be there; flag them only when they are wrong
  or misleading (user's rule, 2026-10-09).

- **Every review includes looking at every article photo**, not just its
  file name: right person (or a neutral image where that's the rule),
  not the same photo as another article on the front page, not a tight
  "(cropped)" face crop. (Added 2026-10-02 after a repeated Turlov photo
  slipped through a review that only read file names.)

## Clean-review streak tracker

The user's long-term plan: once a full week of daily batches goes by with
no edits needed during review, they'll stop reviewing before publishing.
Only serious problems reset the streak (user's rule, 2026-10-02):

- **Resets:** a wrong fact a reader would be misled by (wrong result,
  score, ranking, person, attribution, date), a duplicate or stale story,
  an unrelated source or section, a wrong-person or front-page-duplicate
  photo, or any pipeline bug that produces these.
- **Minor (log it, no reset):** wording, tone, small imprecision that
  doesn't mislead, clarifications, lens choice, lines that talk about the
  source. Flag anything borderline in the review and let the user decide.

Update this after every batch review.

### Review-acceptance streak (separate, user's rule 2026-10-06)

Tracks whether the user accepted Claude's review as proposed (fix list,
verdicts, reset calls) without needing to correct or overrule it. Any
correction from the user (a missed problem, a wrong call, a fix they
reject) resets it to 0. Update after each batch review, once the user has
responded.

- **Current review-acceptance streak: 1.**
- 2026-10-10: PR #62 review accepted (0 -> 1). The missing U.S.
  Championship story was raised by the user before the review began;
  the review's fix list and reset call stood.
- 2026-10-09: PR #61 review overruled twice (1 -> 0): user called the
  calendar count error minor, not a reset; and two Adams lines I wanted
  cut as "not in the source" were sound additions (kept, one softened).
- 2026-10-08: PR #60 review's reset call on the Tokayev social copy
  stood (user first called it minor, then agreed it resets) (0 -> 1).
- 2026-10-07: PR #59 review missed that the calendar piece opened with
  "every event on this month's list was played at classical time
  controls" (social copy: "September in South America ran on classical
  chess"); the month had 514 rapid vs 123 classical events. User caught
  it after publishing (1 -> 0).
- 2026-10-07: PR #59 review accepted (0 -> 1); user noted the "longest
  event" flag wasn't explained (Tigre 9 days vs Rosario 10).
- 2026-10-06: PR #58 review missed a misplaced note in the Larsen piece
  (the remark made after 33...Kf7 sat after 38.Re1+ and the resignation);
  user caught it (1 -> 0). Fixed; drafting and fact-check prompts now keep
  move commentary at the move the source attaches it to.
- 2026-10-06: PR #58 review accepted as proposed (1).

- **Current streak: 0 consecutive clean batches.**
- 2026-10-10: PR #62 reset (streak 1 -> 0). Selection bug: ChessBase's
  Caruana / U.S. Championship piece (opening week of the event) scored 47
  and lost to a ChessBase product review (52, lifted by a +15 Nordic bonus
  from "Scandinavian Defence"); Dubov's bullet challenge got the +45
  major-event bonus from "former world rapid chess champion". Fixed: Nordic
  bonus removed (user's call), U.S./U.S. Women's Championships and other
  marquee events added to the major list, +40 for major-event previews,
  product and book reviews skipped as promotional, a player's title no
  longer counts as the event. Ris review dropped; Caruana piece written by
  hand from the ChessBase source. Dubov piece: "tiny" sweep odds corrected
  (about 1 in 8), group-photo caption clarified; kept (user's call).
- 2026-10-09: PR #61 clean (streak 0 -> 1, user's call: borderline, the
  pipeline did what it was told). Africa calendar piece gave two "Open"
  sections their events' summed counts (Jumuiya 190 vs 84, ABACUS 124 vs
  49) -- the 2026-10-07 section merge summed youth sections in under the
  Open's name; it now keeps the section's own count. A one-day "Swiss
  Manager Training Recap" was cut. Adams 3.Bc4 piece: "never challenges
  the centre" softened, "later rounds" dropped (the Olympiad is over).
  Fagernes round 7 and the anti-cheating explainer checked clean (the
  explainer's arbiters photo kept, user's call).
- 2026-10-08: PR #60 reset (streak stays at 0). Reset (user's call: "we
  can't make up arrogant quotes for country presidents"): the
  Tokayev-Turlov social copy had President Tokayev hold up Kazakh chess as
  a model for other federations -- Turlov's line -- and the headline
  stated it as fact ("Kazakhstan Becomes the Model"); both reworded as
  Turlov's pitch, and a line about the release cut. Minor: Svane piece
  gained his board-three gold and unbeaten 13W/7D Olympiad record.
  Chess960 explainer checked clean. Fixed at the source: drafting and
  fact-check prompts now keep every claim with its speaker and never state
  one person's claim as fact in a headline.
- 2026-10-07: PR #59 reset after publishing (streak 1 -> 0). The calendar
  piece presented our classical-weighted shortlist as the whole month
  ("ran on classical chess"); South America's September was 514 rapid, 123
  classical. Opening and social copy fixed live. Fixed at the source: the
  month's full format counts now go to the drafting model with a rule not
  to describe the month from the list's format mix.
- 2026-10-07: PR #59 first logged as clean (streak 0 -> 1). Minor only: Germany piece
  "same Olympiad board order" -> "same Olympiad team"; Titled Tuesday piece
  gained Artemiev's 9.5/11 tiebreak win (first since 2021, Nakamura 9th)
  and lost an unsourced "reputation for quick play" line; calendar piece
  called Tigre (9 days) the longest when Rosario ran 10. Pipeline: small
  fields (<10, known counts only) penalised, more youth words, sections of
  one event merged, event lengths precomputed for the drafting model.
- 2026-10-06: PR #58 reset (streak 1 -> 0). Reset: the Fagernes round-2
  piece said top seed Elham Amar "had Black against Krishnan Ritvik and
  lost"; the source caption gave the result as (0-1), i.e. Amar won. Body,
  social copy and meta rewritten; photo moved from Amar to leader Harika
  Dronavalli. Minor: the Larsen-Gheorghiu piece checked out move for move,
  but its photo was a craft board of a Botvinnik-Tal 1960 position (alt
  text named them); swapped to Bent Larsen in 1970. Fixed at the source:
  drafting and fact-check prompts now spell out 1-0 / 0-1 / draw and
  require checking the player's colour before saying who won.
- 2026-10-05: PR #57 clean (streak 0 -> 1). Every claim and link in all
  five pieces checked against the three ChessBase sources and the calendar
  data; no resets. Minor fixes only: Speelman piece invented "the name is
  borrowed from Bruegel" (cut to the column's own image caption) and got
  the Kovalenko-Mwadzura 15.Nb1! embed; Ucok piece now notes the author
  helps run the programme, and drops a "crossed 2700 at 14" the source
  itself contradicts; Sahel headline reworded ("Sousse 1967 Next" read as
  a date). Pipeline: the Olympiad game lookup only checked each bracket's
  last 3 rounds, so round-1/3 games were never found; it now checks the
  rest in a second pass.
- 2026-10-04: PR #55 reset (streak stays at 0). Reset: ChessBase's full
  Judit Polgar festival report was drafted three days after we had
  published the same festival's simul result from Chess.com (dropped).
  The Nakamura Bullet Brawl piece and the ratings explainer checked out.
  Fixed at the source: the coverage check now treats a fuller write-up of
  the same single event as already covered unless it reports something
  new. PR #56 (weekly recap) reviewed clean: all 19 links and every claim
  checked; three minor wording edits (runoff margin, a line about our own
  piece, ratings paragraph now leads with Sindarov). Also: the recap
  workflow "failed" on a GitHub API error while requesting review after
  the PR was created; the reviewer request is now a separate, retried,
  non-fatal step in both workflows.
- 2026-10-03: PR #54 reset (streak stays at 0). Resets: a stale
  Freestyle Friday preview ("returns October 2") drafted in the same batch
  as that event's result (dropped); and the Jon Speelman 70th-birthday
  profile showed Nigel Short, his rival in the story -- Speelman's own
  photo ("JonSpeelman24.jpg") was skipped because the name is run
  together. Minor (no reset): two lines talking about the source, and
  cut-off tournament names in the Asia calendar piece. Fixed at the
  source: People pieces only try their subject's photo; run-together
  names match and 3-letter first names count in strict photo matching;
  a same-batch check drops a preview when its result is also in;
  calendar names cut at 50 characters are trimmed to the last word.
- 2026-10-02: PR #53 reset (streak stays at 0). Resets: story merging
  attached Freestyle Friday and the Hanna Sayce stalking case to the U.S.
  Championship piece, and FIDE's schools report to ChessBase's rating
  piece -- which also left FIDE's own rating-list story to be drafted as
  a second, duplicate rating piece (dropped); and the FIDE Assembly piece
  reused the Turlov photo still on the front page. Minor (no reset): So
  "stays sixth" (fifth to sixth), "within 50 points" (70), "only player
  who qualified as champion", US Chess vs FIDE ratings not stated,
  Erdogmus's age line, two lines talking about the source. Fixed at the
  source: merges now need a model's yes on top of name overlap;
  "FIDE Ratings - <month>" counts toward the one-rating-list-a-day cap;
  the photo reuse window counts published articles only.
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
- Last reset: 2026-10-10 (PR #62, see above).
- Earlier resets: 2026-10-08 (PR #60); 2026-10-07 (PR #59); 2026-10-06 (PR #58); 2026-10-04 (PR #55); 2026-10-03 (PR #54); 2026-10-02 (PR #53); 2026-10-01 (PR #52); 2026-09-30 (PR #51); 2026-09-29 (PR #50); 2026-09-27 (PR #47 -- a year range like "2024-2026" next to
  an "Olympiad" mention was misread as a match score, wrongly attaching a
  round-10 team-standings table to the FIDE Excellence Awards ceremony
  piece, an article with zero actual round results. Fixed the underlying
  scoreline regex -- see scripts/selection.py, _SCORELINE_RE -- rather than
  just editing the article. No article-content errors found this batch;
  both pieces checked out fact-for-fact against their real sources.)
