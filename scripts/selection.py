"""
Selection: scores every candidate in data/candidates.json with a simple,
explainable heuristic and picks the day's articles.

Daily volume, per user decision:
  - At most 1 calendar-sourced (chesstournamentcalendar.com aggregate) article.
    Ingestion (see CALENDAR_SCHEDULE in ingest.py) already guarantees at most
    one such candidate exists on any given day, so this is really just "take
    it if it's there" -- but the cap is enforced here too, defensively.
  - 2 external (Chess.com / FIDE) articles guaranteed, up to 4 if enough of
    them clear the quality bar (SCORE_THRESHOLD_FOR_EXTRA).

This is a v1 heuristic, expected to need tuning once real data is flowing;
keep the scoring criteria named and separable so that's easy.

Output: data/selected.json -- ranked list of chosen candidates, each with
its score and score breakdown for auditability (shows up in the draft's
frontmatter downstream, so a reviewer can see *why* something got picked).
"""

import json
import os
import sys
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from coverage import drop_already_covered, drop_superseded_previews

DATA_DIR = Path(__file__).parent.parent / "data"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
SELECTED_PATH = DATA_DIR / "selected.json"
TRENDS_PATH = DATA_DIR / "trends.json"

MIN_EXTERNAL_ARTICLES = 2
MAX_EXTERNAL_ARTICLES = 4
MAX_CALENDAR_ARTICLES_PER_DAY = 1
SCORE_THRESHOLD_FOR_EXTRA = 60  # out of 100 -- above this, external articles 3-4 are allowed through

CALENDAR_KINDS = {"calendar-biggest", "calendar-comingup"}

# Higher-traffic / more clearly newsworthy outlets get a base bump.
SOURCE_TIER_SCORE = {
    "drama": 25,    # Chess.com -- high engagement potential
    "serious": 20,  # FIDE -- official/authoritative
    "features": 22, # ChessBase -- interviews, portraits, columns; the source we
                    # add for people-centered stories the other two rarely run
    "own-data": 15, # calendar aggregates -- always relevant to us, but not breaking news
}

# Keyword weight groups: title/summary matches add points per hit (capped).
KEYWORD_WEIGHTS = {
    # High-interest storylines readers actually click on.
    "scandal": 20, "cheat": 20, "cheating": 20, "controversy": 15, "banned": 15,
    "world champion": 15, "world championship": 15,
    "record": 10, "youngest": 10, "grandmaster": 8, "gm title": 8,
    "prize": 6, "upset": 8, "protest": 10, "investigation": 12,
    "rating list": 18, "fide rating": 14,
    # People-centered stories (ChessBase's interviews and portraits, and
    # the occasional one from the other two sources). Small weights: a round
    # report mentions a "post-game interview" in passing.
    "interview": 8, "opens up": 10, "childhood": 6, "grew up": 6, "in his own words": 8,
    "in her own words": 8, "his story": 6, "her story": 6, "retire": 6,
}
MAX_KEYWORD_SCORE = 30

# The monthly FIDE rating list release (and chess.com/FIDE pieces built
# around it, e.g. "Praggnanandhaa Indian No. 1 On September FIDE Rating
# List") is a recurring, evergreen-interest story that the plain keyword
# score can lose to that day's scandal/drama pieces -- but unlike those,
# it only exists once a month, so losing the slot means it's just gone.
# Guarantee it a spot the same way calendar items get one.
# "FIDE Ratings - October 2026" (ChessBase's monthly headline) has no
# "rating list" in it -- caught live 2026-10-02 when it and FIDE's own
# list story were both drafted.
RATING_LIST_PATTERN = re.compile(
    r"\brating list\b|\bFIDE ratings?\b.{0,12}\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)
MAX_RATING_LIST_ARTICLES_PER_DAY = 1


def is_rating_list_story(item: dict) -> bool:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    return bool(RATING_LIST_PATTERN.search(text))

# Chess.com's RSS feed mixes real news with site-feature/product promotion
# posts ("Play In The Special Edition Of The Gambit Cup", "Get Coached By
# The Almighty Mittens"). These read as calls-to-action addressed straight
# at the reader, not declarative news headlines ("X Wins Y", "X Signs With
# Y") -- a title starting with an imperative verb aimed at the reader is a
# reliable tell. Hard veto rather than a score penalty: no legitimate news
# story is worth publishing as a companion piece to an ad.
PROMO_TITLE_PATTERNS = [
    r"^play in\b", r"^get coached\b", r"^sign up\b", r"^register (for|now)\b",
    r"^enter the\b", r"^join (the|us)\b", r"^watch (the|as)\b", r"^try (the|our)\b",
    # Not anchored to the start -- this is a site-feature-update framing
    # ("Daily Puzzles Just Got More Exciting"), not something a real news
    # headline about a player/event/tournament result would ever say.
    r"just got (more|better|easier|faster)\b",
]


# ChessBase is also a software company: a large share of its feed is its own
# product marketing ("ChessBase\u00b426 -- Tips for Beginners, part 32"), DVD and
# book announcements ("Evans & Friends Vol.1 & 2"), puzzle columns, and
# "-- Live!" stubs that are just a link to a live board. None of that is news,
# and unlike Chess.com's promos it isn't phrased as an imperative, so it gets
# its own list, applied to ChessBase items only.
CHESSBASE_PROMO_TITLE_PATTERNS = [
    r"chessbase.{0,3}\d{2}\b", r"^chessbase\b", r"tips for beginners", r"players? guide",
    r"problem challenge", r"endgame challenge", r"upcoming tournaments", r"help us build",
    r"cloud power", r"\bvol\.?\s*\d", r"\blive!?\s*$", r"\d+ years ago",
    r"\bfritz\b", r"\bmega database\b", r"\bplaychess\b",
]


def is_promotional(item: dict) -> bool:
    title = (item.get("title") or "").strip().lower()
    if any(re.search(pattern, title) for pattern in PROMO_TITLE_PATTERNS):
        return True
    return item.get("sourceName") == "ChessBase" and any(
        re.search(pattern, title) for pattern in CHESSBASE_PROMO_TITLE_PATTERNS
    )


# A governance story (an election, a congress, a council decision), by its
# headline. Used to keep such stories out of the results bonus below and out
# of merges with results reports.
GOVERNANCE_TITLE_RE = re.compile(
    r"\belect(?:ed|s|ion|ions)\b|\bfide congress\b|\bpresidential\b|\bvice[- ]president\b"
    r"|\bgeneral assembly\b|\bcouncil\b",
    re.IGNORECASE,
)


# People-centered stories (an interview, a portrait, a personal column) --
# ChessBase's specialty -- are ranked by score like everything else, in a
# deliberate order of priority: major tournament results, then these, then
# governance elections (see the three bonuses below). Not a guaranteed slot:
# a slot would let an interview displace a major-results report on exactly
# the days results should come first. Instead a feature gets FEATURE_BONUS,
# sized to land between the two, and none of the results/governance bonuses
# (an interview about the Olympiad mentions its results and would otherwise
# earn the results bonus, outscoring the actual round reports -- caught in
# testing: the Olympic winners' interview scored 127 against round reports'
# 112-121).
FEATURE_BONUS = 40
# Keyword hits in a feature's full text (thousands of characters, so nearly
# every generic keyword lands) are capped lower so they can't lift it into
# the results band.
FEATURE_MAX_KEYWORD_SCORE = 15
FEATURE_KEYWORD_RE = re.compile(
    r"\binterview\b|\bportrait\b|\bin conversation\b|\bopens? up\b|\bremembering\b|\bstory\b",
    re.IGNORECASE,
)
# "Firstname Lastname: ..." -- ChessBase's profile headline shape. Case-
# sensitive on purpose (it's detecting capitalized names), and a weaker
# signal than the keywords above: it also fits a plain news item about a
# person ("Bodhana Sivanandan: Youngest-Ever WGM at 11"), so a keyword match
# outranks it for the slot.
FEATURE_PROFILE_RE = re.compile(r"^[A-Z][\w'\u2019.\-]+(?: [A-Z][\w'\u2019.\-]+){1,2}: ")
FEATURE_EXCLUDE_TITLE_RE = re.compile(r"\bR\d{1,2}\b|\bround \d+|\bday \d+", re.IGNORECASE)


def is_feature_story(item: dict) -> bool:
    if item.get("sourceName") != "ChessBase":
        return False
    title = item.get("title") or ""
    if FEATURE_EXCLUDE_TITLE_RE.search(title):
        return False
    return bool(FEATURE_KEYWORD_RE.search(title) or FEATURE_PROFILE_RE.search(title))


# Nordic/regional relevance -- boosts stories that matter for the site's
# Nordic Chess Festival backlink strategy, independent of which lens ends up
# writing the piece.
NORDIC_KEYWORDS = ["norway", "sweden", "denmark", "finland", "iceland", "nordic", "scandinavia"]
NORDIC_BONUS = 15

# The major recurring/marquee tournaments -- not just the Olympiad -- are
# the biggest events on the calendar while they're running, and their
# daily round coverage should reliably outscore other same-day stories,
# even ones that happen to rack up more of the generic high-value
# keywords below through unrelated phrase matches. "Olympiad" used to
# just be one entry in KEYWORD_WEIGHTS worth 12 points, diluted by the
# same 30-point cap every other story competes for -- pulled out into its
# own uncapped bonus instead, the same pattern as the Nordic bonus above
# (caught live: a Total Chess Tour field announcement scored 80 purely
# from two different "world championship" phrasings, "youngest" and
# "grandmaster" -- all just describing players in its own roster, nothing
# about that story's actual newsworthiness -- plus the unrelated Nordic
# bonus, while the real Olympiad Round 7 recap scored only 52 with
# "olympiad" contributing a mere 12 of that).
MAJOR_TOURNAMENT_KEYWORDS = [
    "olympiad", "candidates tournament", "world championship match",
    "grand chess tour", "sinquefield cup", "cairns cup", "tata steel",
    "norway chess", "fide world cup", "world team championship",
    "european team championship", "world rapid", "world blitz",
]
MAJOR_TOURNAMENT_BONUS = 45

# A new FIDE president is a once-every-few-years governance story, not a
# routine federation announcement -- worth guaranteeing a slot the way the
# major-tournament and rating-list stories already are, but it should
# still lose to that day's actual tournament-results coverage when both
# land the same day (caught live: 2026-09-26's Turlov-elected-president
# story scored 45 and 33 under the plain keyword/specificity scoring,
# both well under SCORE_THRESHOLD_FOR_EXTRA -- so it never ran at all,
# even though it's arguably the single biggest governance story of the
# whole Olympiad). GOVERNANCE_ELECTION_BONUS is deliberately smaller than
# MAJOR_TOURNAMENT_BONUS so an Olympiad round recap (or similar) always
# outscores it when both are candidates the same day, but large enough to
# clear SCORE_THRESHOLD_FOR_EXTRA on its own.
#
# Narrow and proximity-based on purpose, same reasoning as
# tournament_has_round_context below: "fide" and "president" both
# appearing somewhere in a long piece (an awards gala thanking dignitaries
# who happen to hold the word "president" in an unrelated title, say)
# isn't the same as the piece actually being about a FIDE presidential
# election -- require one of a small set of phrases that only a genuine
# election story would use.
GOVERNANCE_ELECTION_RE = re.compile(
    r"elected\s+(?:as\s+)?(?:the\s+)?(?:new\s+)?president\s+of\s+fide"
    r"|elected\s+(?:new\s+)?fide\s+president"
    r"|new\s+fide\s+president"
    r"|fide\s+presidential\s+election",
    re.IGNORECASE,
)
GOVERNANCE_ELECTION_BONUS = 35


def score_governance_election(text: str) -> int:
    return GOVERNANCE_ELECTION_BONUS if GOVERNANCE_ELECTION_RE.search(text) else 0

# A tournament name alone isn't enough -- a story can mention "the
# Olympiad" purely as a dateline or backdrop ("signed on the sidelines of
# the 46th Chess Olympiad") without being about its competition at all
# (caught live: a Commonwealth-Chessveda partnership announcement and a
# FIDE Women's Commission meeting recap both mentioned "Olympiad" -- the
# former four times, more than the genuine round recap's one -- purely as
# location/context, and both would have wrongly earned the same bonus as
# actual round coverage on a raw keyword-presence check). Require it to
# co-occur with an actual result/standings signal: a scoreline, explicit
# round/day labeling, or a result verb -- the same kind of language any
# genuine round recap uses and a dateline mention never does.
# \d{1,2}, not \d+ -- an unbounded digit count also matches a year range like
# "2024-2026" (caught live: an awards-ceremony article said "the 2024-2026
# Olympiad cycle," an en-dash year range sitting right next to the word
# "Olympiad," and the unbounded version read it as a match score, wrongly
# attaching a round-results standings table to a piece with zero actual
# round-by-round results). No real chess team-match score reaches 3 digits.
_SCORELINE_RE = re.compile(r"\b\d{1,2}(?:\.5)?\s*[-–]\s*\d{1,2}(?:\.5)?\b")
# Digit form ("Round 9", "Day 8") AND spelled-out form ("round two", "round
# nine", "after six rounds") -- Chess.com's own round recaps consistently
# spell round numbers out in prose (caught live: real stored summaries for
# rounds 2, 6, and 9 read "round two", "after six rounds", "round nine" --
# every one of them would have silently failed a digit-only check, which
# would have broken tournament_has_round_context's same-sentence proximity
# test for genuine Olympiad recaps, not just excluded false positives).
_NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
)
_ROUND_LABEL_RE = re.compile(
    rf"\b(?:round|day)\s+(?:\d+|{_NUMBER_WORDS})\b|\b(?:{_NUMBER_WORDS})\s+rounds?\b",
    re.IGNORECASE,
)
# Deliberately narrow to words that are near-exclusively used for an
# actual competitive result in chess-news prose -- broader verbs like
# "wins"/"leads"/"drew" look precise but aren't: they're common enough in
# ordinary English (a commission "leading" outreach efforts, someone who
# "drew on her experience") that a policy or business story clears them
# almost by accident (caught live, both from the same Women's Commission
# meeting recap and a Total Chess Tour announcement that also happened to
# name "Norway Chess" as the format's inventor rather than as a place
# where a game was actually played).
RESULT_SIGNAL_WORDS = ["beat", "beats", "defeat", "defeated", "match point", "standings", "qualifie", "eliminat"]
# Word-boundary, not substring: a plain `w in text_lower` check matches "beat"
# inside a name like "Beatriz" -- and a leading-\b-only fix doesn't actually
# close that gap, since "beat" also starts at a genuine word boundary in
# "Beatriz" (caught live: WGM Beatriz Irene Franco Valencia, named in a
# ChessMom Project human-interest piece with zero actual results content,
# wrongly satisfied this gate and pulled in an unrelated Olympiad standings
# table). Every complete word in the list gets both boundaries; only
# "qualifie"/"eliminat" are deliberate truncated stems (qualifie[d/r],
# eliminat[ed/ion]) and keep a trailing-open match.
_RESULT_SIGNAL_RE = re.compile(
    r"\bbeats?\b|\bdefeat(?:ed)?\b|\bmatch point\b|\bstandings\b|\bqualifie|\beliminat",
    re.IGNORECASE,
)


def _has_result_signal(text_lower: str) -> bool:
    if _SCORELINE_RE.search(text_lower) or _ROUND_LABEL_RE.search(text_lower):
        return True
    return bool(_RESULT_SIGNAL_RE.search(text_lower))


_TOURNAMENT_PROXIMITY_WINDOW = 60


def tournament_has_round_context(text_lower: str, tournament_key: str) -> bool:
    """True only if `tournament_key` sits within `_TOURNAMENT_PROXIMITY_WINDOW`
    characters of an actual round/day label or scoreline -- not just
    somewhere in the same article.

    A raw "tournament name anywhere + result signal anywhere" check (what
    attach_standings_table used to do) is too coarse: a story can mention a
    tournament purely as a backdrop/contrast ("They aren't playing in the
    Olympiad...") while having its own, unrelated result language elsewhere
    in the piece (caught live: a Chess.com bullet-event recap said "They
    aren't playing in the Olympiad, but... joined a tie atop the
    standings" -- "olympiad" and "standings" both genuinely present, neither
    a substring collision, yet the story has nothing to do with the
    Olympiad's own results).

    A same-SENTENCE check (an earlier version of this function) is the
    obvious next idea, but chess journalism is full of periods that aren't
    sentence-ends -- "U.S." above all, but also "GM.", "IM." -- and a naive
    splitter treats every one as a hard break (caught live: the real stored
    summary for Round 9, "...regained sole lead of the 46th Chess Olympiad
    2026 after beating top seed U.S. in round nine," got its own tournament
    name and round label split into two different "sentences" by the
    U.S./round-nine period, which would have wrongly excluded a genuine
    round recap). A character-distance window sidesteps sentence-boundary
    detection entirely. The window size is calibrated against every
    genuine round recap's actual archived source text (data/selected.json
    history) checked so far: the tournament name and its round/day label or
    scoreline never sit more than 37 characters apart in any of them, while
    both known false positives (the "3+0 Thursday" bullet recap and a
    Disability Olympiad recap) have no round-label/scoreline match in the
    entire text at all, at any distance -- so this isn't a close call tuned
    to one example, there's a wide margin on both sides.
    """
    tournament_spans = [m.span() for m in re.finditer(re.escape(tournament_key), text_lower)]
    if not tournament_spans:
        return False
    label_spans = [m.span() for m in _ROUND_LABEL_RE.finditer(text_lower)]
    label_spans += [m.span() for m in _SCORELINE_RE.finditer(text_lower)]
    for t_start, t_end in tournament_spans:
        for l_start, l_end in label_spans:
            gap = max(l_start - t_end, t_start - l_end, 0)
            if gap <= _TOURNAMENT_PROXIMITY_WINDOW:
                return True
    return False


def score_keywords(text: str) -> int:
    text_lower = text.lower()
    score = 0
    for kw, weight in KEYWORD_WEIGHTS.items():
        if kw in text_lower:
            score += weight
    return min(score, MAX_KEYWORD_SCORE)


def score_nordic(text: str) -> int:
    text_lower = text.lower()
    return NORDIC_BONUS if any(kw in text_lower for kw in NORDIC_KEYWORDS) else 0


def score_major_tournament(text: str) -> int:
    text_lower = text.lower()
    if not any(kw in text_lower for kw in MAJOR_TOURNAMENT_KEYWORDS):
        return 0
    return MAJOR_TOURNAMENT_BONUS if _has_result_signal(text_lower) else 0


def score_specificity(item: dict) -> int:
    """Longer, more detailed summaries tend to indicate a substantive story."""
    summary = item.get("summary") or ""
    words = len(re.findall(r"\w+", summary))
    if words >= 40:
        return 15
    if words >= 20:
        return 8
    return 0


# --- Fan buzz (r/chess) ---
#
# trends.py saves the titles of r/chess's top posts of the day. A candidate
# whose headline names someone those posts are also about gets a small
# capped bump: a story the community is already talking about is more likely
# to land with readers than an equally scored quiet one. Deliberately a
# nudge, not a driver -- capped well below the source-tier and keyword scores
# -- and only the candidate's own headline is matched (its summary names too
# many people to be a fair test).
#
# Precision matters more than recall for a nudge, so a match needs the word
# to look like a proper noun on BOTH sides: capitalized in the headline and
# capitalized in the Reddit title. That drops lowercase chatter ("pragg",
# "total meltdown") on purpose. Caught live while testing: matching on any
# capitalized headline word let "Total Chess Pilot" collect a bump from an
# unrelated post about a "total meltdown", because Chess.com headlines are
# Title Case and every word in them counts as capitalized -- hence the
# stoplist of ordinary headline vocabulary below. Not selection's
# _single_names, which skips names inside roster lists on purpose (right for
# telling two stories apart, wrong here: the players in a roster
# announcement are exactly who fans are talking about).
FAN_BUZZ_PER_POST = 5
FAN_BUZZ_MAX = 10
TRENDS_MAX_AGE_HOURS = 36

HEADLINE_COMMON_WORDS = {
    "complete", "completes", "completed", "player", "players", "field", "fields", "total",
    "pilot", "wins", "winner", "winners", "beats", "beat", "defeats", "defeat", "takes",
    "take", "leads", "lead", "leader", "leaders", "clinch", "clinches", "claims", "claim",
    "secures", "secure", "sole", "first", "second", "third", "final", "finals", "round",
    "rounds", "match", "matches", "game", "games", "title", "titles", "champion", "champions",
    "championship", "championships", "tournament", "event", "events", "news", "update",
    "updates", "announced", "announces", "announce", "named", "after", "again", "still",
    "more", "most", "best", "top", "record", "says", "said", "gets", "gives", "hits", "drops",
    "falls", "rises", "returns", "return", "continues", "extends", "seals", "sweeps", "stuns",
    "upsets", "upset", "favorites", "favourites", "favorite", "favourite", "women", "womens",
    "open", "team", "teams", "play", "plays", "playing", "week", "today", "tonight", "live",
    "report", "reports", "review", "interview", "preview", "recap", "grandmaster", "master",
    "president", "federation", "council", "committee", "election", "elected", "world", "cup",
    "league", "series", "rapid", "blitz", "bullet", "classical", "online", "chess", "with",
    "from", "into", "over", "under", "this", "that", "their", "while", "amid", "about",
    "against", "before", "between", "during", "through", "without", "will", "have", "been",
}


def _headline_names(title: str) -> set[str]:
    """Capitalized words in a headline that could be people or places."""
    names = set()
    for word in re.findall(r"[A-Z][a-z']+", title):
        lowered = word.lower().rstrip("'s")
        if len(lowered) >= 4 and lowered not in GENERIC_NAME_WORDS and lowered not in HEADLINE_COMMON_WORDS:
            names.add(lowered)
    return names


def load_trend_titles(now: datetime | None = None) -> list[str]:
    """Titles from trends.json, or [] when it's missing, unreadable, or too
    old to mean "today" (a stale file must not keep boosting yesterday's
    stories)."""
    try:
        data = json.loads(TRENDS_PATH.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(data["fetchedAt"])
        if (now or datetime.now(timezone.utc)) - fetched > timedelta(hours=TRENDS_MAX_AGE_HOURS):
            return []
        return [t for t in data["titles"] if isinstance(t, str)]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def score_fan_buzz(item: dict, trend_titles: list[str] | None) -> int:
    if not trend_titles or item.get("kind") in CALENDAR_KINDS:
        return 0
    names = _headline_names(item.get("title", ""))
    if not names:
        return 0
    matching_posts = sum(1 for title in trend_titles if names & _headline_names(title))
    return min(FAN_BUZZ_MAX, FAN_BUZZ_PER_POST * matching_posts)


# Priority bands for the three story types whose relative order is a policy,
# not an accident of keyword counts: major tournament results first, then
# people-centered features, then governance elections. Summing bonuses alone
# left the ranges overlapping (results down to 85, features up to 107,
# elections up to 86), so each type is clamped into its own band -- results
# at or above the floor, features inside theirs, elections at or below the
# ceiling -- and the clamp shows up as scoreBreakdown.bandAdjustment. Every
# other kind of story is untouched and competes by score as before.
RESULTS_SCORE_FLOOR = 90
FEATURE_SCORE_FLOOR = 80
FEATURE_SCORE_CEILING = 89
ELECTION_SCORE_CEILING = 79
# Raw feature scores (tier + capped keywords + specificity + FEATURE_BONUS) run
# about 65-105; that range maps onto the feature band.
FEATURE_RAW_LOW = 65
FEATURE_RAW_HIGH = 105


def _apply_priority_band(total: int, breakdown: dict, governance: bool) -> int:
    if breakdown.get("feature"):
        # Spread over the band by raw score rather than clamping, so a
        # stronger feature still outranks a weaker one.
        spread = FEATURE_SCORE_CEILING - FEATURE_SCORE_FLOOR
        return FEATURE_SCORE_FLOOR + min(spread, max(0, (total - FEATURE_RAW_LOW) * spread // (FEATURE_RAW_HIGH - FEATURE_RAW_LOW)))
    if breakdown.get("majorTournament"):
        return max(total, RESULTS_SCORE_FLOOR)
    if governance:
        return min(total, ELECTION_SCORE_CEILING)
    return total


def score_item(item: dict, trend_titles: list[str] | None = None) -> tuple[int, dict]:
    breakdown = {}
    breakdown["sourceTier"] = SOURCE_TIER_SCORE.get(item.get("sourceTier"), 0)

    text = f"{item.get('title', '')} {item.get('summary', '')}"
    feature = is_feature_story(item)
    # An election tally ("110-85") reads like a scoreline and a congress is
    # held during the Olympiad, so a governance story matches the results
    # bonus's own test -- caught in testing: the Turlov election piece scored
    # 150 against the round report's 153. Not a result; no bonus.
    governance = not feature and bool(GOVERNANCE_TITLE_RE.search(item.get("title") or ""))
    breakdown["keywords"] = min(score_keywords(text), FEATURE_MAX_KEYWORD_SCORE) if feature else score_keywords(text)
    breakdown["nordic"] = score_nordic(text)
    breakdown["majorTournament"] = 0 if (feature or governance) else score_major_tournament(text)
    breakdown["governanceElection"] = 0 if feature else score_governance_election(text)
    breakdown["feature"] = FEATURE_BONUS if feature else 0
    breakdown["specificity"] = score_specificity(item)
    breakdown["fanBuzz"] = score_fan_buzz(item, trend_titles)

    raw_total = sum(breakdown.values())
    total = _apply_priority_band(raw_total, breakdown, governance)
    if total != raw_total:
        breakdown["bandAdjustment"] = total - raw_total
    return total, breakdown


def dedupe_by_topic(scored: list[dict]) -> list[dict]:
    """Very light dedup: avoid picking near-identical titles on the same day."""
    seen_titles: list[str] = []
    result = []
    for item in scored:
        title_key = re.sub(r"\W+", " ", item["title"].lower()).strip()
        if any(title_key[:30] == seen[:30] for seen in seen_titles):
            continue
        seen_titles.append(title_key)
        result.append(item)
    return result


# --- Same-story merging ---
#
# Two different outlets often cover the exact same event under totally
# different headlines ("Samarkand Olympiad Day 1: Favourites, fireworks
# and a shock" vs "Thai IM Upsets Indian Number-2 As Favorites Prevail"),
# which dedupe_by_topic's title-prefix check never catches -- it only
# matches near-identical wording, not near-identical events. Detect this
# instead by shared distinctive names (players, specific people) between
# title+summary, and merge every match into one candidate rather than
# publishing the same story twice.
#
# Deliberately never drops one in favor of the other, even though that
# was considered: a quick word-overlap check against a real duplicate
# pair (FIDE's 401-significant-word recap vs Chess.com's 21-word blurb
# of the same event) showed the two texts can look almost entirely
# different by any similarity score purely because of a length mismatch,
# while the short one still carried its own genuinely unique fact (a
# second upset FIDE's piece didn't mention). There's no cheap, reliable
# way to tell "pure repeat" from "shorter but complementary" apart from
# actually reading both -- so always merge and let draft.py's own
# synthesis (which does read both in full) decide what's worth using
# from each, rather than risk silently discarding a source that had
# something the other didn't.

# Capitalized words that recur across unrelated stories -- organization
# names, honorifics, dates, generic event vocabulary -- rather than the
# distinctive player/person names that actually indicate two write-ups
# cover the same specific event. A bigram touching one of these is
# skipped rather than treated as a real name match.
GENERIC_NAME_WORDS = {
    "the", "this", "that", "these", "those", "a", "an", "and", "or", "but",
    "with", "from", "after", "before", "chess", "olympiad", "world", "fide",
    "gm", "im", "cm", "wgm", "wim", "fm", "wfm", "champion", "championship",
    "tournament", "round", "day", "team", "open", "cup", "league",
    "international", "national", "federation", "committee", "council",
    "president", "interim", "vice", "chief", "arbiter", "commission",
    "congress", "games", "game", "presidential", "samarkand",
    # Titles written out in full ("grandmaster", unlike "gm", is 4+ letters
    # so the length floor doesn't catch it). Caught live 2026-09-30: a Titled
    # Tuesday report and the London Classic announcement merged on
    # Firouzja's name plus "Grandmaster"/"Grandmasters" alone.
    "grandmaster", "grandmasters", "master", "masters",
    "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february",
    "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "in", "of", "for", "as", "on", "at", "to", "by",
}

# A bigram match (e.g. "Arjun Erigaisi" in both) is a strong, low-noise
# signal on its own -- two outlets independently spelling out the same
# full name essentially never happens by coincidence, so 2 of those is
# enough. A single-word match (e.g. "Argentina") is much weaker on its
# own -- team-event recaps routinely share a host country or an unrelated
# team name by coincidence -- so it takes more of them alone to count.
MIN_SHARED_BIGRAMS_FOR_SAME_STORY = 2
MIN_SHARED_SINGLE_NAMES_FOR_SAME_STORY = 4


def _enumeration_spans(text: str) -> list[tuple[int, int]]:
    """Character spans covered by an enumerated list of 3+ proper names --
    a field/roster announcement packs in far more distinct names than a
    narrative story does, purely because it's enumerating a list, not
    because it's substantively about all of them. Names found only inside
    a span like this are excluded from _name_bigrams/_single_names
    entirely (caught live: a 24-player Total Chess Tour field announcement
    false-matched three unrelated Olympiad-adjacent stories as "the same
    story" purely because a couple of its 24 listed players are also
    protagonists of real, unrelated Olympiad narratives -- a coincidence
    any large-enough roster is bound to produce against same-day chess
    news). Two distinct list shapes, both seen in real source text:

    - Comma-and-"and"-separated prose ("Levon Aronian, Liem Le, Jorden
      van Foreest, Abhimanyu Mishra, Shakhriyar Mamedyarov and Andrew
      Hong").
    - A ranked table flattened to plain text with no commas at all
      ("Magnus Carlsen (Norway) - World No. 1 Fabiano Caruana (United
      States) - World No. 3 ..."), where the actual tell is 3+
      parenthetical annotations recurring close together rather than any
      particular connecting punctuation."""
    spans = []

    name = r"[A-Z][a-zA-Z'\-]+(?:\s+[A-Za-z][a-zA-Z'\-]*){0,3}"
    run_re = re.compile(rf"{name}(?:\s*,\s*{name}){{2,}}(?:\s*,?\s+and\s+{name})?")
    spans += [m.span() for m in run_re.finditer(text)]

    # A run of 3+ "(...)" annotations within PAREN_CLUSTER_GAP characters
    # of each other, whatever sits between them -- the recurring
    # parenthetical is itself the list signature here, not the separator.
    PAREN_CLUSTER_GAP = 50
    parens = list(re.finditer(r"\([^)]{1,40}\)", text))
    i = 0
    while i < len(parens):
        j = i
        while j + 1 < len(parens) and parens[j + 1].start() - parens[j].end() <= PAREN_CLUSTER_GAP:
            j += 1
        if j - i + 1 >= 3:
            # Extend back far enough to also cover the name immediately
            # before the first parenthetical in the cluster.
            start = max(0, parens[i].start() - 60)
            spans.append((start, parens[j].end()))
        i = j + 1

    return spans


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _name_bigrams(item: dict) -> set[tuple[str, str]]:
    """Adjacent-word pairs where both words are capitalized and neither is
    generic -- a cheap proxy for "this text names a specific person or
    place", reliable enough to tell "Arjun Erigaisi" apart from ordinary
    capitalized sentence starts without needing real NER. Skips any pair
    that falls inside an _enumeration_spans() run (see there)."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    spans = _enumeration_spans(text)
    words = [(m.group(), m.start()) for m in re.finditer(r"[A-Za-z']+", text)]
    bigrams = set()
    for (a, pos_a), (b, pos_b) in zip(words, words[1:]):
        if not (a[:1].isupper() and b[:1].isupper()):
            continue
        if _in_spans(pos_a, spans) or _in_spans(pos_b, spans):
            continue
        la, lb = a.lower().rstrip("'s"), b.lower().rstrip("'s")
        if la in GENERIC_NAME_WORDS or lb in GENERIC_NAME_WORDS:
            continue
        bigrams.add((la, lb))
    return bigrams


# Ordinary words that are only capitalized because they open a sentence --
# a real name opening a sentence ("Argentina, seeded 28th, ...") must still
# count, so this is a word list rather than a blanket sentence-start rule.
SENTENCE_START_WORDS = set("""
what when where which while who whom whose why how they them their there these those
this that then than thus this here have having been being were will would could should
must might shall also after before during since until unless although though because
some many most more much each every both either neither other another such only even
just still already never always often sometimes once twice first last next later
early earlier today yesterday tomorrow tonight however meanwhile instead perhaps
indeed asked speaking according despite following given including like unlike with
without within into onto from about above below between among against along across
over under again further while once
""".split())


def _single_names(item: dict) -> set[str]:
    """Standalone capitalized, non-generic words -- catches the same-event
    case _name_bigrams misses: two outlets covering the same team-event
    round often name the same countries/players, but with an ordinary
    lowercase word breaking up the adjacency bigrams need ("Argentina,
    seeded 28th, defeated Ukraine" vs. "Iran overcame eighth-seeded
    France" -- Argentina/Ukraine/Iran/France never sit next to another
    capitalized word, so two round-3 Olympiad recaps sharing all four of
    those names still scored zero shared bigrams and were drafted as two
    separate articles covering the same round). Filtered the same way as
    bigrams (including the same enumeration-span exclusion); only used
    together with MIN_SHARED_SINGLE_NAMES_FOR_SAME_STORY precisely because
    a lone word is weaker evidence than a matched pair."""
    # Newline, not a space, between headline and summary: the summary's
    # first word starts a sentence too.
    text = f"{item.get('title', '')}\n{item.get('summary', '')}"
    spans = _enumeration_spans(text)
    names = set()
    for m in re.finditer(r"[A-Za-z']+", text):
        w = m.group()
        if not w[:1].isupper():
            continue
        if _in_spans(m.start(), spans):
            continue
        # A capital that only marks the start of a sentence says nothing
        # about the word being a name. Caught live 2026-10-01: the Turlov
        # interview merged with a schools-tournament report on "What",
        # "They", "School" and "European" alone.
        if w.lower() in SENTENCE_START_WORDS and re.search(r'(^|\n|[.!?:]["\u201c\u2018\']?)\s*$', text[: m.start()]):
            continue
        lw = w.lower().rstrip("'s")
        if lw in GENERIC_NAME_WORDS or len(lw) < 4:
            continue
        names.add(lw)
    return names


def _is_same_story(a: dict, b: dict) -> bool:
    shared_bigrams = _name_bigrams(a) & _name_bigrams(b)
    if len(shared_bigrams) >= MIN_SHARED_BIGRAMS_FOR_SAME_STORY:
        return True
    shared_singles = _single_names(a) & _single_names(b)
    if len(shared_singles) >= MIN_SHARED_SINGLE_NAMES_FOR_SAME_STORY:
        return True
    # A broad roundup piece (many teams/players named) and a narrow
    # single-match spotlight piece from the same event/day can share very
    # few names overall even when they're substantially the same story --
    # the roundup's name pool dilutes any count-based threshold (caught
    # live: FIDE's round-4 "eight teams still perfect" survey and
    # Chess.com's round-4 "U.S. sweeps Ukraine" spotlight both centered on
    # Aronian's win over Ukraine, but shared only one bigram and three
    # singles total -- under both thresholds above). One matched full name
    # (a bigram) is on its own too weak a signal by itself, since two
    # unrelated pieces can easily both mention the same famous player in
    # passing on the same day -- but a bigram match PLUS at least one
    # further shared name beyond that bigram's own two words is a much
    # more specific combination: not just the same person mentioned twice,
    # but the same person tied to the same additional context (an
    # opponent, a team, an event detail) in both pieces.
    bigram_words = {w for bg in shared_bigrams for w in bg}
    extra_singles = shared_singles - bigram_words
    return len(shared_bigrams) >= 1 and len(extra_singles) >= 1


# --- Merge guards ---
#
# _is_same_story only asks "do these two texts share enough names", which
# can't tell an election story, or an interview, from the round report it
# happens to share names with (caught in testing with ChessBase added: the
# Turlov election piece was folded into the Olympiad "Day 10" results piece,
# and the Olympic winners' interview into the round report -- which would
# have erased the interview as a piece of its own). Different kinds of story
# never merge, and a feature never merges with anything.


def _story_kind(item: dict) -> str:
    if is_feature_story(item):
        return "feature"
    if GOVERNANCE_TITLE_RE.search(item.get("title") or ""):
        return "governance"
    return "other"


def _compatible_for_merge(a: dict, b: dict) -> bool:
    kind_a, kind_b = _story_kind(a), _story_kind(b)
    return "feature" not in (kind_a, kind_b) and kind_a == kind_b


MERGE_CHECK_MODEL = "claude-sonnet-5-5"
_merge_verdicts: dict = {}


def confirm_same_story(client, a: dict, b: dict) -> bool:
    """The name-overlap test above only proposes a merge; a short model
    check decides. Name overlap stopped being a usable signal once ingest
    started pulling full article text -- long pieces share plenty of common
    names (caught live 2026-10-02: the U.S. Championship announcement merged
    with Freestyle Friday and a stalking case on "Anna", "Women",
    "YouTube"). Without a client (local runs) nothing merges: a missed
    merge costs a near-duplicate draft a reviewer drops, a wrong merge
    publishes another story's facts."""
    if client is None:
        return False
    key = (a.get("sourceUrl"), b.get("sourceUrl"))
    if key in _merge_verdicts:
        return _merge_verdicts[key]
    prompt = (
        "Do these two chess news items report the SAME specific news event "
        "(the same announcement, result, list or incident), so one article "
        "could cover both? Sharing a tournament, a player or a topic is not "
        "enough. Answer only YES or NO.\n\n"
        f"A: {a.get('title')}\n{(a.get('summary') or '')[:800]}\n\n"
        f"B: {b.get('title')}\n{(b.get('summary') or '')[:800]}"
    )
    try:
        response = client.messages.create(
            model=MERGE_CHECK_MODEL,
            max_tokens=2048,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b_.text for b_ in response.content if b_.type == "text").strip().upper()
        verdict = text.startswith("YES")
    except Exception as exc:  # noqa: BLE001 -- fail closed: no merge
        print(f"  Merge check failed ({type(exc).__name__}: {exc}) -- not merging.", file=sys.stderr)
        verdict = False
    if not verdict:
        print(f"  Not merging (model says different stories): {a['title']} / {b['title']}")
    _merge_verdicts[key] = verdict
    return verdict


def merge_duplicate_stories(scored: list[dict], client=None) -> list[dict]:
    """scored is sorted by selectionScore descending, so the first member
    of any same-story group encountered is already the highest-scoring
    one -- it stays as the item's own fields, and every later match in
    the group is folded into its "additionalSources" list instead of
    appearing as its own separate candidate. Calendar aggregates are
    exempt: they're built from our own tournament data, not outlet
    reporting, so "two outlets covered the same event" doesn't apply.

    At most one member per distinct sourceName: merging exists to combine
    independent outlets' coverage of the same event (a FIDE recap + a
    Chess.com recap of the same round), not to accumulate everything one
    outlet's own _is_same_story() heuristic happens to flag. Caught live
    (2026-09-25): a genuine FIDE+Chess.com merge of the real Round 8
    recap also absorbed a second, completely unrelated FIDE article (an
    education summit piece) purely on shared name-overlap -- the word-
    count heuristic couldn't reliably tell that pairing apart from a
    real match (confirmed: both scored the same 8 shared "single name"
    words). A second item from a source already represented in the group
    is exactly the shape of case where that heuristic is least trustworthy
    (a single outlet's own multiple same-day stories share bylines,
    datelines, and recurring names for reasons that have nothing to do
    with being the same story), and correctly excluding it costs nothing
    real: it still gets scored and considered as its own standalone
    candidate, exactly like any other story that didn't merge with
    anything."""
    result: list[dict] = []
    for item in scored:
        if item["kind"] in CALENDAR_KINDS:
            result.append(item)
            continue
        match = next(
            (
                existing
                for existing in result
                if existing["kind"] not in CALENDAR_KINDS
                and _compatible_for_merge(item, existing)
                and _is_same_story(item, existing)
                and item["sourceName"] != existing["sourceName"]
                and item["sourceName"] not in {s["sourceName"] for s in existing.get("additionalSources", [])}
                and confirm_same_story(client, existing, item)
            ),
            None,
        )
        if match is None:
            result.append(item)
            continue
        match.setdefault("additionalSources", []).append(
            {
                "sourceName": item["sourceName"],
                "sourceUrl": item["sourceUrl"],
                "title": item["title"],
                "summary": item.get("summary", ""),
            }
        )
    return result


def main() -> None:
    if not CANDIDATES_PATH.exists():
        print("No candidates.json found -- run ingest.py first.")
        return

    candidates = json.loads(CANDIDATES_PATH.read_text())

    trend_titles = load_trend_titles()
    print(f"Fan buzz: {len(trend_titles)} r/chess post title(s) loaded" + ("" if trend_titles else " (no bonus today)"))

    scored = []
    for item in candidates:
        if is_promotional(item):
            continue
        total, breakdown = score_item(item, trend_titles)
        if total <= 0:
            continue
        scored.append({**item, "selectionScore": total, "scoreBreakdown": breakdown})

    scored.sort(key=lambda x: x["selectionScore"], reverse=True)
    scored = dedupe_by_topic(scored)
    # Needs ANTHROPIC_API_KEY (set on the pipeline's select step); without
    # one -- a local run -- the model checks are skipped rather than failing.
    client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        from api_usage import track

        client = track(anthropic.Anthropic())
    scored = merge_duplicate_stories(scored, client)
    scored = drop_already_covered(client, scored)
    scored = drop_superseded_previews(client, scored)

    calendar_items = [item for item in scored if item["kind"] in CALENDAR_KINDS][:MAX_CALENDAR_ARTICLES_PER_DAY]
    external_items = [item for item in scored if item["kind"] not in CALENDAR_KINDS]

    rating_list_items = [item for item in external_items if is_rating_list_story(item)][:MAX_RATING_LIST_ARTICLES_PER_DAY]
    remaining_external = [item for item in external_items if item not in rating_list_items]

    guaranteed_external = remaining_external[:MIN_EXTERNAL_ARTICLES]
    extra_pool = remaining_external[MIN_EXTERNAL_ARTICLES:MAX_EXTERNAL_ARTICLES]
    extra_external = [item for item in extra_pool if item["selectionScore"] >= SCORE_THRESHOLD_FOR_EXTRA]

    selected = calendar_items + rating_list_items + guaranteed_external + extra_external

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SELECTED_PATH.write_text(json.dumps(selected, indent=2))

    print(f"Selected {len(selected)} item(s) from {len(candidates)} candidate(s):")
    for item in selected:
        buzz = item["scoreBreakdown"].get("fanBuzz", 0)
        print(f"  [{item['selectionScore']:>3}] {item['sourceName']}: {item['title']}" + (f"  (+{buzz} fan buzz)" if buzz else ""))
        for extra in item.get("additionalSources", []):
            print(f"        + merged with {extra['sourceName']}: {extra['title']}")


if __name__ == "__main__":
    main()
