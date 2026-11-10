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

- **Avoiding generic photos outranks everything else in photo choice**
  (user's rule, 2026-11-04, after I swapped a named player's photo for a
  neutral pool photo). A real photo of a person in the story -- even a
  side figure -- beats a generic/neutral image every time; the headline
  is changed to name them rather than the photo dropped. Never replace a
  person photo with a generic one, and never add pipeline logic that
  does, unless the photo itself is wrong (wrong person, front-page
  duplicate, too old under the 8-year rule, a cropped face). The 8-year
  rule only applies while a recent photo of someone in the story exists;
  otherwise an older person photo is used, captioned with its year ("Pia
  Cramling in 2016"; user's call, 2026-11-06). A neutral photo is only for
  stories where no usable person photo exists at all.

- **Never publish an article, player page or event page without a photo**
  (2026-11-05, after the Bavarian Championship event page went out bare
  while two photos of its champion sat in our own image store). Check
  src/content/articles/_images first (and how other pages of the same
  kind are illustrated -- event pages show a recent champion), then
  Commons. Only if both fail, say so plainly; a Commons rate limit is not
  a reason to skip the local store. (Georg Meier's player page is the one
  known gap: his only usable photo is blocked by Wikimedia rate limits.)

- **Results pieces get a board even when the source quotes no game**
  (user's rule, 2026-11-07: the World Junior Rapid report had none). When
  no source PGN or named game is found, draft.py searches the event's
  Lichess broadcast for a game by a player the piece names (main subject
  first; their latest decisive game, else latest game) and adds it with a
  "Round N: White - Black, result" caption. Reviews check it is from the
  right event and section.

- **A game named in the headline is the board** (user's call,
  2026-11-08: the Bullet Grandpa piece showed one of Dubov's 99 wins, not
  game 28, Smith's only win, which Chess.com's report gave only as a video
  clip). For a Chess.com story whose headline names "Game N", draft.py
  takes game N of the match from the Chess.com game archive of an @handle
  the source names (the opponent it played most that day, in finishing
  order), captioned "Game N: White - Black, result". Reviews check it.

- **Quality floor: nothing below a score of 50 is published** (user's
  rule, 2026-11-07, after an Esports World Cup 2027 announcement scoring
  46 went out; it was removed). Calendar pieces are the only exception.
  selection.py drops anything else under MIN_PUBLISH_SCORE before
  drafting; a review drops any draft below it.

- **Headlines and social copies don't reuse set phrases from the last two
  weeks** (user's rule, 2026-11-07: "Half a Point Back" twice). Regular
  readers remember them. draft.py rewrites a headline or social copy
  sharing a run of 4+ ordinary words (not names or scores) with any
  headline / social copy of the last 14 days; reviews check the same.

- **Every review includes looking at every article photo**, not just its
  file name: right person (or a neutral image where that's the rule),
  not the same photo as another article on the front page, not a tight
  "(cropped)" face crop. (Added 2026-10-02 after a repeated Turlov photo
  slipped through a review that only read file names.)

- **Russia: skip only what represents Russia** (user's rule, clarified
  2026-10-19). Leave out content where a player, team, tournament or
  anything else clearly represents Russia (Russian national teams, Russian
  events, players presented as Russia's). Russian-born players competing
  under the FIDE flag or for foreign clubs are ordinary subjects (e.g.
  Murzin playing for Bayegan Pendik at the Club Cup).

- **Bold claims the source reasonably supports are fine** (user's call,
  2026-10-24). Don't flag or soften strong wording of what the source
  says ("the increment was his call" when the source has him designing
  the format and explaining the increment). Flag only claims that go
  beyond the source or contradict it.

- **Hedged, plausible speculation is welcome** (user's call, 2026-10-19):
  "likely Madaminov" for a second the source calls "almost certainly" is
  the kind of reasonable reading wanted -- flag only guesses stated as
  fact, not well-hedged ones.

- **Event pages follow our own final results** (user's rule, 2026-10-22).
  When we publish the final result of an edition of an event that has an
  event page, the page's winners list gets that winner in the same PR. The
  pipeline does it (`eventResult` in the article, `scripts/event_results.py`
  edits the page, the PR report lists it); every review checks the page edit
  along with the article, and adds it by hand for a hand-written piece. A
  test fails if a published `eventResult` and its page disagree. The
  winner's player page, if we have one, gets its highlights/summary edited
  in the same PR (check the edit in review); its Titles list is built from
  the event pages, so it needs no edit.

- **Morning batch: fix and publish** (user's rule, 2026-11-03). The
  morning check no longer waits for approval. Review the draft PR as
  always, apply the fixes judged appropriate, drop what existing rules
  say to drop, publish the rest and push -- this is standing permission
  for the morning batch only; any other push still needs the user's
  go-ahead. Hold back (leave as draft) only an article that needs a
  judgment call no rule covers (a new reason to drop or keep, allegations
  or legal-sensitive claims, an unclear Russia-rule case). Pipeline fixes
  for the problems found: small to medium work is done right away, only
  very large work is left for the user. Tests and the site build must
  pass before the push. The recap opens with a "please double-check" list
  (anything not fully certain, with the exact sentence or photo and why),
  then the usual fixes/drops/held/pipeline/streak summary and the social
  copies with URLs. The review-acceptance streak now means the user had
  nothing significant to correct after publishing.
  The quarterly evergreen review works the same way (user's rule,
  2026-11-03): it fixes, publishes and pushes, and never removes a profile
  (players who drop off the lists keep their pages).
  Missing player pages are created MONTHLY, after each new FIDE list
  (user's rule, 2026-11-04; scheduled task "Monthly missing player pages",
  the 2nd of each month): every player in the open top 100 or the women's
  top list without a page gets one, fact-checked, with a photo, published
  and pushed. Checking and updating the existing pages stays quarterly.

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
verdicts, reset calls) without needing to correct or overrule it. A
significant correction from the user (a missed problem, a wrong reset
call, a fix they reject) resets it to 0; minor corrections (dropping a
small flag, rewording a fix) don't count (user's rule, 2026-10-24).
Update after each batch review, once the user has responded. A
disagreement only over whether something was a reset is minor when the
user approves the fixes themselves (user's rule, 2026-11-09).

- **Current review-acceptance streak: 5.**
- 2026-11-09: PR #97 accepted (4 -> 5). User approved every fix; my two
  reset calls (Senior Worlds headline, Daakshin figures) were ruled minor,
  and disagreeing over a reset call is itself minor when the fixes stand
  (user's rule, 2026-11-09). The calendar prompt now bars describing the
  continent's month or calendar as a whole in title and social copy.
- 2026-11-08: PR #95 accepted ("everything seems solid", 3 -> 4); minor
  miss: I didn't review the weekly recap, which the morning check covers
  too (reviewed and published after the user pointed it out).
- 2026-11-07: PR #94 accepted ("mostly ok", 2 -> 3). Follow-ups were new
  rules, not corrections of my calls: headline wording variety ("Half a
  Point Back" was on two front-page headlines; the new one now "Half a
  Point Behind", and draft.py rewrites a headline sharing a 4+-word set
  phrase with a recent one), and event-weighted scoring (live
  over-the-board events +30, weekly online series -15 with no follow-up
  or elite bonus, "Esports World Cup" no longer matches "world cup", a
  later year's announcement gets no follow-up bonus, event-page aliases
  count for follow-ups). Today's pieces rescored: Al Ain 160, Bavarian
  125, Freestyle Friday 55, EWC 46. Then (user's call) the EWC piece was
  removed and a 50-point quality floor added, and the headline check
  looks back 14 days, not 3.
- 2026-11-06: PR #93 accepted (1 -> 2; "pretty good"). The photo change
  was a new rule on the 8-year limit, not a correction of a call I made.
- 2026-11-05: PR #92 accepted ("everything seems solid", 0 -> 1). User's
  follow-ups were new requests, not corrections: a Bavarian Championship
  event page, and scoring changes (an event-page bonus, a smaller
  anniversary feature bonus).
- 2026-11-04: PR #91 (first fix-and-publish morning) corrected after
  publishing (11 -> 0): I replaced the Al Ain Roebers photo with a neutral
  one and changed the pipeline to do the same for side figures, undoing
  the user's own rule (a photo of a named player, with a headline naming
  them, beats a generic photo). Both reversed.
- 2026-11-03: PR #90 review accepted in full (10 -> 11).
- 2026-11-02: PR #89 review accepted (9 -> 10). User improved one proposed
  fix: rather than a minimum-length check on Chess.com text, read the body
  to its real end (the extractor stopped at the first nested </div>).
- 2026-11-01: PR #87/#88 review accepted (8 -> 9, user's call: minor
  corrections). I called the recap's stale KazChess line a reset; user: the
  round-6 news wasn't out at draft time, so not a reset. User also pointed
  at the real photo bug (the cooldown, not only the photo date).
- 2026-10-31: PR #86 review accepted (7 -> 8). User ruled the Fischer
  photo fine (he's in the headline) and the unrelated board minor.
- 2026-10-30: PR #85 review accepted (6 -> 7). User ruled my two borderline
  flags: the Slav attribution minor, the Carlsen "Defends Both" headline the
  more serious of the two (left to the user as borderline, so not counted).
- 2026-10-29: PR #84 review accepted in full (5 -> 6).
- 2026-10-28: PR #83 review accepted in full (4 -> 5).
- 2026-10-27: PR #82 review accepted in full (3 -> 4).
- 2026-10-26: PR #81 review accepted (2 -> 3, minor correction): user kept
  the 2025 Clutch game board I proposed dropping, with a caption instead.
- 2026-10-25: PR #79/#80 review accepted in full (1 -> 2).
- 2026-10-24: PR #78 review accepted (0 -> 1, minor corrections only):
  user dropped my Carlsen "increment was his call" flag (a bold claim the
  source supports) and questioned the 2400 and "sweet turn" calls (both
  stood, reworded).
- 2026-10-23: PR #77 review overruled (stays 0): my reset call on the
  Club Cup "at most one can finish on 13" line; user ruled it minor.
- 2026-10-22: PR #76 review (stays 0): accepted, with the calendar "October's"
  link ruled minor rather than borderline. 2026-10-21 also counted a miss:
  the So photo swap put a photo from the previous day's piece back on the
  front page, then a badly framed one; user caught both.
- 2026-10-21: PR #75 review overruled (1 -> 0): I called So's "can lose
  his lead only if he loses the last round and a rival wins" a reset (a
  loss plus a rival's draw ties); user: the sentence is true, the text need
  not cover every scenario -- very minor at most, left as written. User
  also ruled Chess.com's "Abdusattorov lost in round two" (it was round
  four) minor.
- 2026-10-20: PR #74 review accepted (0 -> 1). The no-semicolon title rule
  was a new style rule, not a correction.
- 2026-10-19: PR #73 review overruled (1 -> 0): user called So's "fifth
  win" and the Murzin "rescues" headline borderline, not resets (a team
  result can shift match dynamics); and "likely Madaminov" is the hedged
  speculation wanted, not a problem. Russia rule clarified (see top).
- 2026-10-18: PR #71/#72 review accepted (0 -> 1). User challenged the So
  "four wins" call; rechecked round by round, it stood (3W 4D). The
  Finnish clubs sub-section was a new request, not a correction. User
  stopped the Fischer 1960 photo download, so the piece uses a neutral
  pool photo.
- 2026-10-17: PR #70 review overruled (2 -> 0): I proposed "Five Perfect
  Scores Lead the Youth Worlds"; user pointed out age-group sections are
  separate tournaments, so no sentence may count or group leaders across
  them. Rewritten section by section.
- 2026-10-16: PR #69 review accepted in full (1 -> 2).
- 2026-10-15: PR #68 review accepted in full (0 -> 1).
- 2026-10-14: PR #67 review called the missing round 4 board a fix, not a
  reset; user ruled it a reset and asked for the pipeline fix (stays 0).
- 2026-10-13: PR #66 review proposed keeping the accreditation notice and
  reframing the Council piece; user removed both (stays 0).
- 2026-10-12: PR #65 review's Munich headline fix ("The Unofficial
  Olympiad Hungary Won Every Match") was ungrammatical; user caught it
  (3 -> 0). Now "Munich 1936: The Chess Olympiad FIDE Never Recognised".
- 2026-10-12: PR #65 review accepted as proposed (2 -> 3).
- 2026-10-11: PR #63/#64 review accepted (1 -> 2); user asked for the
  selection scores, which exposed one more bug (fixed with the rest).
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
- 2026-11-10: PR #98 reset (streak 1 -> 0). Reset: the Tal 90th-birthday
  piece showed a wooden craft board of the 1960 Botvinnik-Tal match
  captioned "Mikhail Tal" (now the 1960 Leipzig photo of Tal against
  Fischer, from our store), and said the 1960 win made him "the youngest
  world champion in history" (up to that time). Fixed: Anuj headline had
  been retitled around the Anand photo ("Anand, India's First GM, Reacts as
  Anuj Becomes 100th"; now "Anuj Shrivatri Becomes India's 100th GM, 38
  Years After Anand"); Total Chess headline "Keymer Joins 24 Players" (now
  "Keymer Among 24 as Total Chess Starts Its Budapest Pilot"), its social
  copy repeated "24 players, three time controls" from September. Russia
  rule (my call, flagged): Russia taken out of the Anuj piece's federation
  GM comparison. Anuj rescored 110 -> 70 (a false +40 rating-list bonus).
  Fixed at the source: craft objects (handicraft, chessboard, stamps,
  coins, figurines) are never person photos; the rating-list bonus needs
  "rating list" in the headline or opening, not anywhere in the text.
- 2026-11-09: PR #97 clean (streak 0 -> 1, user's call). My two reset
  calls were overruled as minor: the Senior Worlds headline "Strutinskaya
  Leads Senior Worlds" was fair (the sections are of equal standing, so a
  section leader leads the event; the new headline "Strutinskaya Perfect
  on 5/5 at Senior Worlds, Cramling Unbeaten in Women 50+" is still
  better), and Daakshin's "2589 performance and +22.6" (not in the source,
  cut). Fixed: Russia
  rule -- "Russia's Kleymenova", Iudina "of Russia", Vorobiov "(Russia)"
  cut (FIDE's labels); calendar headline "Africa's Classical Calendar
  Fills Up" described the month from the list (now "Medea Open Draws 201
  to Top Africa's October List"), social copy "three week-long festivals"
  (two festivals, three sections) and a repeated "the biggest field in our
  October" phrase. Minor: "Girls'" -> "Girls", ambiguous "let him plant a
  knight" (Daakshin). Event page: 2026 row noted "29th edition, 7½/9, on
  tiebreak", the stale "29th edition, under way" next-edition line
  replaced. Boards checked: Gschnitzer-Sasikiran (round 9), Xiao-Yu
  Armageddon (mate on 48), Pranav-Khripachenko, Gaprindashvili-Lauterbach.
  Fixed at the source: "(Russia)", "Russia's <Name>" and "of Russia"
  labels are stripped from drafted bodies and social copy.
- 2026-11-08: PR #95 reset (streak stays at 0). Resets: a FIDE press
  release (Gukesh preview, "Press release by FIDE" as an italic line at the
  top of ChessBase's story) was drafted -- dropped under the no-exceptions
  press-release rule; the Bullet Grandpa piece said "one draw or loss for
  Smith" ended the $20,000 bonus (a draw or win). Fixed: Tegernsee piece
  claimed the leaders "faced stronger opposition than anyone else" (Raja's
  2430 is higher), "penultimate round is on Saturday" (already played),
  headline "...Svane Draws Back" (now "Sasikiran Catches Gopal on 6/7 at
  Tegernsee, Svane Among 21 on 5½"). Minor: Crazyhouse social copy named
  "Chesscom" (no Chess.com in social copy), "Bxd4" invented for "grabbed
  the bishop on d4"; Bullet Grandpa "A 800-point", "the game after game
  six", Dubov's 3225 is a bullet rating. Fixed at the source: a "Press
  release by/from" credit line in the story counts as a press release; the
  game board plays Crazyhouse drops (the final's board would have been
  blank).
  Weekly recap (PR #96), missed in my first pass and caught by the user:
  all 20 links and every claim checked against the linked pieces, clean;
  opening reworded, today's Tegernsee round 7 and Bullet Grandpa lines
  added.
- 2026-11-07: PR #94 reset (streak stays at 0). Resets: the Bavarian
  round 6 piece showed the Facebook logo -- the photo search's "<event>
  logo" query matched on the word "logo" alone (now Kacper Piorun, 2021,
  the 2015 winner, a co-leader on the top board; headline "Gopal Beats
  Besou to Lead Bavarian Open, Piorun Among 12 Half a Point Back"); the
  Freestyle Friday piece said Nesterov "held" Yakubboev in round five (he
  beat him) and had Yakubboev beat Kamsky "with Black" (Kamsky had Black).
  Minor: "perfect at 6/6 after round five" (won his last six), Besou "in
  the group a half point behind the next tier" (a point behind Gopal), Al
  Ain repeated tiebreak sentence, calendar "Buenos Aires" (venue city not
  in the data) and "the one to watch" for a finished event. Carlsen/EWC
  and Al Ain checked clean against Chess.com and FIDE. Fixed at the
  source: "logo" alone never counts as a filename match.
- 2026-11-06: PR #93 reset (streak stays at 0). Reset: the Senior Worlds
  piece showed the entrance of the Nona Gaprindashvili Chess Palace
  captioned "Nona Gaprindashvili", and its headline was rewritten around
  her -- the photo was a building named after her. First kept with an
  honest caption; then (user's call) replaced by a real 2016 photo of her
  at the board, captioned "Nona Gaprindashvili (right) in 2016, with Elena
  Fatalibekova". Headline "Senior Worlds: Gaprindashvili Half a Point Back
  in the Women 65+". Fixed at the source (user's call): when no recent
  photo of anyone in the story exists, the 8-year limit gives way and the
  newest older person photo is used, captioned "<Name> in <year>". Fixed: the commentators piece showed Svidler from behind shaking
  hands with Topalov (not in the story), captioned "Peter Svidler" (now
  Leko's 2025 photo, from our store); Russia rule -- Svidler's eight
  Russian titles, Suleymenov's Russian open win and the Aeroflot Open name
  cut. Minor: an unconfirmed "WGM" for Strutinskaia, board caption added.
  Fixed at the source: places and memorials named after a person (palace,
  entrance, museum, monument, statue, grave...) are never captioned or
  matched as that person.
- 2026-11-05: PR #92 reset (streak stays at 0). Reset: the Eugenio Torre
  birthday piece said he "turns 75 today" on the 5th (his birthday is
  4 November). Fixed: the Bavarian Championship headline had been retitled
  around the Svane photo ("Top Seed Svane Draws Rithvik Raja...") and lost
  the story -- photo kept, headline now names both ("Besou, 15, Joins the
  Tegernsee Leaders, Top Seed Svane Half a Point Back"); the Chinese
  Rapid board was a drawn rapid game, not the blitz tiebreak that knocked
  Ding out. Minor: Titled Tuesday "split $400 apiece" ($400 each),
  calendar "in San Jose" (San Pedro) and a "Mexico and Texas" heading over
  a New Jersey event, Torre photo and game captions. Fixed at the source:
  a photo retitle must keep the old headline's lead name (one retry); a
  knockout or arena pair's board takes the quoted game, else the last
  decisive one, on source PGNs too; Lichess name matching drops tags like
  "(QD)".
- 2026-11-04: PR #91 reset (streak stays at 0; first fix-and-publish
  morning). Reset: the Speed Chess Championship XI piece gave Nakamura the
  2025 semi-final win over Lazavik and the 2024/2025 final wins over
  Firouzja -- Chess.com's "the world number-one, who beat..." meant Carlsen.
  Fixed: the Al Ain opening-day report's forward-looking lines ("round four
  is the next test") had passed by publication (FIDE's report came a day
  after the opening day). Minor: Dubov "from Moscow" cut (Russia rule),
  Lazavik "two classical titles", Turlov piece's "carry weight in Turlov's
  circle" guess and a line about FIDE's report. Lazavik's new player page
  got the KazChess win and his Esports World Cup final. Fixed at the
  source: the fact check resolves descriptions used in place of a name
  before assigning their facts. My swap of the Al Ain photo (Eline
  Roebers) for a neutral one, and the pipeline change behind it, were
  reversed (user's call): a named player's photo with a headline naming
  them is the requested behaviour, to avoid generic photos.
- 2026-11-03: PR #90 reset (streak stays at 0). Reset: Chess.com's
  "Challenge the Grand Chess Auto Bots" (a bot set with rewards, a site
  promotion) was drafted with the Chess.com logo (dropped). Borderline
  (not ruled), fixed: Speelman's "the column is due for the 6th" read as
  "his sixth" column (6 December). Minor: "a match twice as long" (20 vs
  14 games), no caption on the "Javoxir" photo, calendar headline case and
  a cut "Zone" name. Speelman board (Nakamura-Sindarov, 17.2) and all 20
  calendar entries checked clean. Fixed at the source: "Challenge the/our"
  headlines and headlines naming bots are skipped as promotions.
- 2026-11-02: PR #89 reset (streak stays at 0). Resets: the Panov profile
  gave the Panov Attack as "3.cxd5" (3.exd5) and had Keres flee to Finland
  when the Red Army took Estonia "in 1945" (1944, by sea) -- both
  ChessBase's slips. Borderline (not ruled): the Bullet Brawl piece was
  drafted from 544 characters -- Chess.com's body was cut at the
  standings table, missing Carlsen, Nakamura's misqueue and Firouzja's
  13.5/15 finish (rewritten from the full report). Minor: "1.e4" in the
  Panov line linked to a Ruy Lopez board, no game caption, Keres relief
  caption. Fixed at the source: Chess.com text is read to the body's own
  closing tag (tables kept as rows); a written line is linked only if
  every move is the game's; lines from move 1 are replayed with
  python-chess and illegal ones listed in the PR report.
- 2026-11-01: PR #87 reset (streak stays at 0). Reset: the KazChess round 6
  piece showed the crowded 2015 Berlin hall photo of Dubov again (Commons'
  recorded date 2019) -- his player-page photo was blocked by the photo
  cooldown, which counted a piece the batch's four drafts were about to push
  off the front page. Borderline, fixed: calendar headline "Europe's
  Classical Season Runs Long" (October was 694 rapid to 285 classical),
  Humpy's Club Cup tweet with no matching line in the ratings piece,
  "The Russian grandmaster" (Russia rule). Minor: "a event", ratings and the
  record 22-place gap added, Carlsen "will meet in a field of 24". Weekly
  recap (PR #88): the KazChess line was overtaken by round 6 (not a reset,
  user's call), "side" -> "team". Fixed at the source: the cooldown counts
  only the front-page slots this run's drafts leave; a file-name year
  earlier than the recorded date wins.
- 2026-10-31: PR #86 reset (user's call: the Chess960 board that broke the
  site build is a reset; first logged as clean, 0 -> 1 -> 0). Minor, fixed: the
  Myagmarsuren obituary's board was Papapostolou-Myagmarsuren 1960, a game
  the piece never mentions (now Fischer-Myagmarsuren, Sousse 1967) -- only
  the first game file on a ChessBase page was read, and a lone game was used
  without checking its players are named; Freestyle Friday "the source's
  Meat Loaf reference" line and a missing Carlsen line. The Fischer photo
  on "... Who Met Fischer, Dies at 88" stood (user: he's in the headline).
  Fixed at the source: every game file on a ChessBase page is read; a game
  needs both players named in the text, even when it's the only one; the
  next-person photo fallback tries people named in the headline first.
  Also caught while fixing: the Freestyle Friday draft's Chess960 board
  broke the site build ("Invalid move in PGN: O-O" -- the cleaner dropped
  the start FEN, and our board library can't play 960 anyway). Chess960
  games got no board, and the board renders nothing on an unreadable
  game instead of failing the build. Then (user's call) Chess960 boards
  work: the cleaner keeps Variant/SetUp/FEN and the board replays with
  chessops (Lichess's library) instead of chess.js; the Movahed-Yakubboev
  960 game is back on the Freestyle Friday piece.
  Follow-up (user's call): a photo of someone the headline doesn't name
  needs a headline that does. Freestyle Friday retitled "Movahed Beats
  Leader Yakubboev to Win Freestyle Friday"; after the photo pick, draft.py
  asks for a headline naming the photographed person from the body's own
  facts (kept only if it names them and fits 30-80 characters).
  Noted: Commons has a small (351px) photo of Myagmarsuren under
  "Lkhamsuren", missed on spelling and size.
- 2026-10-30: PR #85 reset (streak stays at 0). Reset: the Clutch final's
  board was the game-18 Sindarov-Nakamura draw, not the game-17 King's
  Indian win the piece links -- no moves quoted, so the pair lookup took the
  last game. Borderline (user: closer to a reset than the Slav one): the
  Istanbul headline "Carlsen Defends Both" when the sources only call him
  the defending champion. Minor: Pragg's Slav given to Caruana, no caption on
  the "Javoxir" photo, a pointed "worth keeping in mind" aside on Turlov and
  the sponsor, "a recent run of events at this time of year". Fixed at the
  source: the pair lookup takes the last decisive game; the fact check
  needs a source for any claim that a title holder will play.
- 2026-10-29: PR #84 reset (streak stays at 0). Resets: Chris Ward's
  Monthly Dragon video column (no games or players named, text all shop
  links) was drafted with a "Chris Ward Autos in Tangier Road" car-dealer
  photo (dropped); my 2026-10-28 change crashed every Lichess board lookup
  (body_markdown passed before it existed); Chess.com's Clutch Chess day-two
  report scored 40 and was never drafted (written by hand -- Chess.com's
  "1.5-point lead" was its own slip, the Lichess results give Pragg 11 to
  8.5). Borderline, fixed: KazChess "Dubov (Russia)" (Russia rule), a 2015
  crowded Berlin hall photo of Dubov (no recorded date; now neutral). Minor:
  "youngest on the leaderboard (Smirnov...)". Fixed at the source: +25 for
  a later round/day of an event named in our last 7 days' openings;
  ChessBase product columns ("Monthly Dragon", "in our ChessBase shop",
  "FritzTrainers in the shop") skipped; shop, firm and street file names
  ("Autos", "Road", "Ltd", geograph) are never person photos; a year in the
  file name counts when the photo has no recorded date.
  User follow-ups the same day: KazChess (a regular masters) outscored the
  Clutch Chess elite field, and its generic photo was a failed search.
  Fixed: "Event Name: ..." headlines aren't profiles (KazChess and Clutch
  day 1 had both taken the +40 feature bonus); +20/+40 for two/three of
  the FIDE top 20 named in the opening; the photo search tries our own
  player pages (main subject first, other subjects after Commons). KazChess
  now shows Dubov (2019, from his player page).
- 2026-10-28: PR #83 reset (streak stays at 0). Resets: ChessBase's and
  Chess.com's Clutch Chess day-one reports were both drafted (merged by hand
  into the ChessBase piece, Chess.com as second source) -- Clutch Chess isn't
  on the major list and name overlap missed, so the pair never reached the
  merge check; and the ChessBase piece linked 58...hxg5 (game 1) to the
  embedded game 2. The Chess.com draft also opened with a model's editing
  note ("unchanged below, with one link added"). Borderline: "winning queen
  endgame" (rooks; ChessBase's slip). Minor: "the one he will replay",
  "zugzwang-style control", "a 1.5-point gap"; Shogdzhiev "eight months to
  the birthday deadline" (eight to Mishra's mark, three to the birthday).
  Fixed at the source: any event name shared by two openings sends the pair
  to the merge check; a "#game-embed" link must be a move of the embedded
  game (else it moves to one that is); paragraphs that talk about the
  editing are stripped.
  Later (user's call): when a Lichess round holds several games between
  one pair, the lookup takes the one with the most of the article's quoted
  moves; the last game (the decider) only when the moves don't tell them
  apart.
  2026-10-29, after publishing (reader's comment): the Shogdzhiev piece said
  "Before Serbia, he scored 4½/7 ... at the European Club Cup" -- the Club
  Cup came after (Serbian round 4 was 26 September; ChessBase: "a second
  consecutive strong showing"). The drafter inferred the order from the
  source's sentence order. Fixed live; the fact check now lists every
  before/after claim and needs the source or dates to give that order.
- 2026-10-27: PR #82 reset (streak 2 -> 0). Resets: KCF Academy's own
  season recap and 2027 sign-up pitch ("by Kasparov Chess Foundation") was
  drafted (dropped); the Hamburg amateur-team piece showed the SK Gaming
  esports logo -- "SK Weisse Dame Hamburg" was read as an organisation with
  the acronym "SK" (now a neutral photo). Borderline, fixed: "landed on 23
  October" (the source's slip; round 3 was 19 October), Finnish section
  repeating the final's (cut to the Etela-Vantaan result). Minor: "ranked
  99th" (finished; seeded 91st). Fixed at the source: organisation bylines
  (Foundation, Academy, Federation...) count as press releases; sign-up
  pitches in the body are skipped as notices; club prefixes (SK, SC, SV...)
  don't make a logo search; the Finnish section needs a round/result
  headline.
- 2026-10-26: PR #81 clean (streak 1 -> 2). Capablanca 1939 piece:
  borderline "one reading ... the sat-out game ... gave Capablanca a symbolic
  win" (the source's symbolic win is the gold) fixed; simul group photo
  captioned as such. Clutch Chess preview: its 2025 Caruana-Nakamura board
  had no explanation -- user wants boards kept when relevant, with a caption.
  Fixed at the source: a gameCaption field shown in the game box; draft.py
  writes "From the <event>" when a current story's game is from an earlier
  year.
- 2026-10-25: PR #79/#80 clean (streak 0 -> 1; the borderline "Wednesday"
  was fixed without a reset ruling). Recap: "a reversal of Wednesday's loss
  for the Uzbek" (round 4 was Tuesday, and Abdusattorov lost to Suleymanli,
  not Giri), "Murzin's swindle rescued" (headline was softened), a line about
  our own piece, a clumsy opening; Woodward photo -> So. All 20 links and
  claims checked. Nakamura Bullet Brawl piece: generic Chess_clock pool photo
  while an unused 2026 Nakamura photo existed (swapped); "even 218 strong ...
  for seven editions" reworded. Fixed at the source (after the user asked
  why it wasn't): Commons' top 8 hits for Nakamura were all 2008-2016, all
  dropped by the 8-year recency rule; a current story's search now retries
  the newest uploads for the same query before giving up.
- 2026-10-24: PR #78 reset (streak 1 -> 0). Reset: the Bodhana Sivanandan
  IM-record piece carried a "Finnish clubs in Budva" section (unrelated,
  and a repeat of the Club Cup final's) -- the Finnish sub-section fired on
  "club cup" anywhere in the opening; now headline only. Minor: Bodhana's
  2400 tied to the WGM title (IM's), "Bodhana's record" (Polgar's), her
  run after round 1 (five wins and a draw, not "two wins"); Club Cup final
  "sweet turn for both men" (Giri and Erdogmus); the event page's new 2026
  row lacked its "Budva" note. First event-page update committed by the
  pipeline itself (Bayegan Pendik). Carlsen MOVE Cup and Oceania calendar
  clean (my "increment was his call" flag dropped, user's call).
- 2026-10-23: PR #77 clean (streak 0 -> 1, user's call). Minor, fixed: Club
  Cup round 6 "at most one of the leading trio can finish on 13" (two:
  Novy Bor play Elektroprivreda; I called it a reset, user ruled minor);
  So's title "four years after the last" (five; Chess.com's slip);
  Yakubboev "teammate" (Uzbekistan teammate, rival clubs); a line about the
  standings table; two So quotes split across paragraphs. Pipeline bug: the
  first event-page/player-page update (So, 2026 U.S. Champion) was made on
  the runner but never committed (git add only covered articles) -- applied
  by hand, the event page now leads with So. Fixed at the source: the
  workflows commit all of src/content/, and the paragraph splitter keeps a
  paragraph whole rather than break inside a quote.
- 2026-10-22: PR #76 reset (streak stays at 0). Reset: the U.S.
  Championship final-round piece called So "the defending champion" --
  Chess.com's unnamed "The American number-one and defending champion went
  over his full game" meant Caruana. Also fixed: a 2008 photo of So aged
  15 (all three recent So photos were in the front-page cooldown; now a
  2025 Caruana photo), "October's" Cairo rapid (September's; minor, user's
  call), "very likely sealed" (would have), "nearly the whole event" (the
  second half), "Thursday" playoff (today), "Russia's Zemlyanskii" (Russia
  rule), "West Rand Closed 2026all". Club Cup round 5 (merged
  ChessBase/Chess.com) and Atyrau final checked clean. Fixed at the
  source: the fact check lists every description attached to a person
  (title, role, age, nationality, rating) and checks the source gives it to
  the same person; it also gets our records of each event's latest winner
  (event pages + EXTRA_TITLE_HOLDERS) to test "defending champion" claims;
  current stories never use a dated photo older than 8 years.
- 2026-10-21: PR #75 reset (streak stays at 0). Reset (user: "unacceptable"):
  FIDE's World Championship side-events notice ("Join side activities...",
  sign-ups at tickets.fide.com) was drafted as an article, with FIDE's
  rhetorical "where else can you play against Anand" read as a programme
  item (dropped). Minor: U.S. Championship round 10 piece repeated
  Chess.com's "Abdusattorov lost in round two" (round four), put So's
  remark about Niemann's goal as our own comment, and used the So photo
  still on the front page (now Tata 2023); Club Cup round 4 piece "two
  defeats on the top boards" (board order unknown) and "1/2" scores. Fixed
  at the source: side-event/"join activities" headlines and bodies pointing
  to tickets.fide.com or "secure your place" are skipped as notices.
- 2026-10-20: PR #74 reset (streak 1 -> 0). Resets: two European Club
  Cup round 3 reports drafted (Chess.com's, headlined "Erdogmus Climbs To
  World No. 15", and ChessBase's) -- Erdogmus piece dropped, its live-list
  line folded into the ChessBase piece; and that piece called a tiebreak
  column "game points" (44/42; really 17 and 16½). Minor: So-Caruana piece
  credited our Caruana preview with a point about So it never made, "a few
  games" (two), fact-checker's clumsy "penultimate round and one more";
  Neiksans piece assumed he left "in their teens" and ran an advert-like
  courses section (cut to one line); calendar "later in the week". Fixed
  at the source: two items naming the same major event always reach the
  merge check, and the check treats same-round reports as one story.
- 2026-10-19: PR #73 clean (streak 0 -> 1, user's call). Borderline,
  fixed: round 8 gave So a "fifth win" (his fourth; ChessBase's slip
  again) and a 2008 photo of him aged 15 (now 2023); Club Cup round 2
  headline "Murzin's Swindle Rescues..." softened to "Keeps ... Clear".
  Minor: a first-person line. Total Chess and Sindarov seconds checked
  clean ("Likely Madaminov" in the headline). Bug of mine: the Finnish
  clubs section was missing -- the fact-check pass never saw the
  chess-results data and cut it; added by hand (Etela-Vantaa 4-2,
  Aatos 6-0, Gambiitti 2-4). Fixed at the source: the fact-checker gets
  the Finnish data, the run logs whether it was found, and win counts are
  checked against the score.
- 2026-10-18: PR #71 reset (streak stays at 0). Resets: the round 7
  piece gave So "four wins" (3W 4D on 5/7; ChessBase's own slip, checked
  round by round); and a ChessBase European Club Cup preview (67) was
  drafted over Chess.com's round 1 report (54), the event having started
  (replaced by the round 1 report, with a Finnish clubs sub-section).
  Borderline, fixed: Fischer headline "and Chess Missed It" (the magazine
  missed it), his gravestone captioned "Bobby Fischer" (now a neutral
  photo), "seventy years ago today" a day late. Minor: round 8 and Krush
  lines, calendar wording. World Cup spots piece clean. PR #72 (weekly
  recap) clean: all 16 links and claims checked; two lines about our own
  headline/source reworded, round 7 and Club Cup lines added. Fixed at the
  source: European Club Cup on the major-event list; a "kicks off" or
  "preview" headline gets only the preview bonus; any round report makes
  a preview stale; Club Cup pieces get a Finnish clubs sub-section from
  chess-results (teams by federation flag, results per round).
- 2026-10-17: PR #70 reset (streak stays at 0). Resets: the youth worlds
  piece ("Three Perfect Scores Lead the Youth Worlds") grouped leaders of
  separate age-group sections, and left out Under 17 again (rewritten
  section by section, headline on Sameh-Kuandykuly in the U13 Open);
  the Dortmund 2027 piece said the announcement gave no dates when the
  lede says 8-15 August, and showed an unrelated named player
  (Kim Steven Yap, Dubai 2013). No round 7 U.S. Championship report:
  Chess.com had not published it. Fixed at the source: ChessBase's lede
  is kept on top of the ingested full text; the loose "{continent} chess"
  and "chess tournament" photo tiers are gone (neutral pool instead);
  drafting and fact-check prompts keep each standing in its own section.
  After publishing, user unpublished the Dortmund piece: it was a ChessBase
  "Press release" and read as an advertisement. Press releases are now
  skipped with no exceptions ("by Press release" byline, or "press
  release" in the headline).
- 2026-10-16: PR #69 reset (streak stays at 0). Resets: the U.S.
  Championship round 6 piece repeated Chess.com's "would be the first to
  win five U.S. Championships in a row" right before linking our own piece
  saying a fifth would equal Reshevsky's five (now "equal"); and its
  Caruana photo was a frame from the same 2024 Candidates shoot as Titled
  Tuesday's, still on the front page (now Awonder Liang). Minor: Atyrau
  piece had both seeds on "a zero in the first two rounds" (each lost one
  game); Vaganian's Euwe simul is dated 1965 (13, not "15"), Dortmund was
  last year; calendar euros; Xiong and So-Woodward line added. Fixed at
  the source: the photo cooldown orders same-day articles by score like
  the front page, and "_02"/"_03" frame numbers count as one shoot.
- 2026-10-15: PR #68 reset (streak stays at 0). Resets: the U.S.
  Championship round 5 report said "four rounds left" after round 5 of an
  11-round event (six); and FIDE's World Championship ticket-sale notice
  was drafted (dropped), padded with unsourced pricing guesses. Minor:
  Woodward photo had no caption (run-together file name), Shogdzhiev piece
  gained his one loss and the record deadline, youth worlds piece gained
  the Under 17 sections. ChessBase's feed timed out this run. Fixed at the
  source: ticket and pass sale headlines skipped as notices; run-together
  names caption; drafting and fact-check prompts check rounds left.
- 2026-10-14: PR #67 reset (user's call; streak stays at 0). The U.S.
  Championship round 4 report had no game board: ChessBase (primary) has
  no PGN and the merged Chess.com source with all four games was never
  tried, and a board also needed a quoted move. Also: Lee's ending was
  rook vs bishop, not opposite-coloured bishops as ChessBase said (game
  moves checked); calendar piece presented senior events (Usedom, Cap
  Negret 65+/50+) as ordinary opens; Titled Tuesday ending read the win
  as form when it came from time-scramble wins. Fixed at the source: the
  board is looked up on every merged source and attached without quoted
  moves.
- 2026-10-13: PR #66 reset (streak 1 -> 0). Dropped (user's call): a
  media-accreditation notice ("ridiculous" to publish) and a FIDE Council
  decision list from 21 September framed as if the Samarkand Assembly were
  still to come, with an unrelated Magnus Carlsen photo. Fixes: R3 photo
  (So aged 15 -> Shankland), "Alice Lee, 16" and a passed round-4 date cut,
  Xiong-Shankland board added (Chess.com's novelty "N" had shifted move
  links); Shenzhen board moved from a drawn rapid game to the Armageddon,
  "ten games" -> seven. Added by hand: the Fagernes final (Jumabayev wins,
  Gloeckler's second GM norm), which had scored 51 and was left out.
  Fixed at the source: administrative notices skipped like promotional
  items; organisation photo searches use the logo only; the decider is
  taken when one round holds several games between a pair; novelty markers
  stripped; +25 for the final result of an event we've followed.
- 2026-10-12: PR #65 clean (streak 0 -> 1). Munich 1936 and Bundesliga
  round 1-3 pieces checked claim by claim against ChessBase; Navara-MVL
  embed and both photos fine. Minor: "Solingen's" Navara, "most
  hard-fought" (all three Baden-Baden wins were 4½-3½), "former FIDE world
  champion", Munich headline "Won 20-0" -> "Won Every Match". No U.S.
  Championship piece: Chess.com had not yet published round 3.
- 2026-10-11: PR #63 reset (streak stays at 0). Resets: the U.S.
  Championship round 2 piece showed a footballer ("Wesley moraes ferreira
  da silva") -- the photo match ignored two-letter surnames, so "Wesley So"
  matched on "Wesley"; and the round 1 report was drafted in the same batch
  as round 2 (dropped; its "round 2 is on Saturday" had passed). Also:
  Freestyle Friday (115) and an Olympiad travel diary (100) outscored both
  U.S. Championship round reports on passing "Olympiad" mentions. Minor:
  So/Titled Tuesday link and "five-time-title chaser" (R2), a line about
  qualifying places (Freestyle), unrelated Uzbek-team photo (travel piece,
  now neutral), Oceania "was classical" -> "mostly classical". Fixed at the
  source: two-letter surnames must match, the major-event bonus needs the
  event in the headline or opening 200 characters, event headlines with a
  colon aren't profiles, and an earlier round's report is dropped when a
  later round of the same event is in the batch. PR #64 (weekly recap)
  clean: all 21 links and every claim checked.
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
- Last reset: 2026-11-10 (PR #98, see above).
- Earlier resets: 2026-11-08 (PR #95); 2026-11-07 (PR #94); 2026-11-06 (PR #93); 2026-11-05 (PR #92); 2026-11-04 (PR #91); 2026-11-03 (PR #90); 2026-11-02 (PR #89); 2026-11-01 (PR #87); 2026-10-31 (PR #86); 2026-10-30 (PR #85); 2026-10-29 (PR #84); 2026-10-28 (PR #83); 2026-10-27 (PR #82); 2026-10-24 (PR #78); 2026-10-22 (PR #76); 2026-10-21 (PR #75); 2026-10-20 (PR #74); 2026-10-18 (PR #71); 2026-10-17 (PR #70); 2026-10-16 (PR #69); 2026-10-15 (PR #68); 2026-10-14 (PR #67); 2026-10-13 (PR #66); 2026-10-11 (PR #63); 2026-10-10 (PR #62); 2026-10-08 (PR #60); 2026-10-07 (PR #59); 2026-10-06 (PR #58); 2026-10-04 (PR #55); 2026-10-03 (PR #54); 2026-10-02 (PR #53); 2026-10-01 (PR #52); 2026-09-30 (PR #51); 2026-09-29 (PR #50); 2026-09-27 (PR #47 -- a year range like "2024-2026" next to
  an "Olympiad" mention was misread as a match score, wrongly attaching a
  round-10 team-standings table to the FIDE Excellence Awards ceremony
  piece, an article with zero actual round results. Fixed the underlying
  scoreline regex -- see scripts/selection.py, _SCORELINE_RE -- rather than
  just editing the article. No article-content errors found this batch;
  both pieces checked out fact-for-fact against their real sources.)
