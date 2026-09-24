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
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
SELECTED_PATH = DATA_DIR / "selected.json"

MIN_EXTERNAL_ARTICLES = 2
MAX_EXTERNAL_ARTICLES = 4
MAX_CALENDAR_ARTICLES_PER_DAY = 1
SCORE_THRESHOLD_FOR_EXTRA = 60  # out of 100 -- above this, external articles 3-4 are allowed through

CALENDAR_KINDS = {"calendar-biggest", "calendar-comingup"}

# Higher-traffic / more clearly newsworthy outlets get a base bump.
SOURCE_TIER_SCORE = {
    "drama": 25,    # Chess.com -- high engagement potential
    "serious": 20,  # FIDE -- official/authoritative
    "own-data": 15, # calendar aggregates -- always relevant to us, but not breaking news
}

# Keyword weight groups: title/summary matches add points per hit (capped).
KEYWORD_WEIGHTS = {
    # High-interest storylines readers actually click on.
    "scandal": 20, "cheat": 20, "cheating": 20, "controversy": 15, "banned": 15,
    "world champion": 15, "world championship": 15, "olympiad": 12,
    "record": 10, "youngest": 10, "grandmaster": 8, "gm title": 8,
    "prize": 6, "upset": 8, "protest": 10, "investigation": 12,
    "rating list": 18, "fide rating": 14,
}
MAX_KEYWORD_SCORE = 30

# The monthly FIDE rating list release (and chess.com/FIDE pieces built
# around it, e.g. "Praggnanandhaa Indian No. 1 On September FIDE Rating
# List") is a recurring, evergreen-interest story that the plain keyword
# score can lose to that day's scandal/drama pieces -- but unlike those,
# it only exists once a month, so losing the slot means it's just gone.
# Guarantee it a spot the same way calendar items get one.
RATING_LIST_PATTERN = re.compile(r"\brating list\b", re.IGNORECASE)
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


def is_promotional(item: dict) -> bool:
    title = (item.get("title") or "").strip().lower()
    return any(re.search(pattern, title) for pattern in PROMO_TITLE_PATTERNS)


# Nordic/regional relevance -- boosts stories that matter for the site's
# Nordic Chess Festival backlink strategy, independent of which lens ends up
# writing the piece.
NORDIC_KEYWORDS = ["norway", "sweden", "denmark", "finland", "iceland", "nordic", "scandinavia"]
NORDIC_BONUS = 15


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


def score_specificity(item: dict) -> int:
    """Longer, more detailed summaries tend to indicate a substantive story."""
    summary = item.get("summary") or ""
    words = len(re.findall(r"\w+", summary))
    if words >= 40:
        return 15
    if words >= 20:
        return 8
    return 0


def score_item(item: dict) -> tuple[int, dict]:
    breakdown = {}
    breakdown["sourceTier"] = SOURCE_TIER_SCORE.get(item.get("sourceTier"), 0)

    text = f"{item.get('title', '')} {item.get('summary', '')}"
    breakdown["keywords"] = score_keywords(text)
    breakdown["nordic"] = score_nordic(text)
    breakdown["specificity"] = score_specificity(item)

    total = sum(breakdown.values())
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
    "congress", "games", "game", "monday", "tuesday", "wednesday",
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
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    spans = _enumeration_spans(text)
    names = set()
    for m in re.finditer(r"[A-Za-z']+", text):
        w = m.group()
        if not w[:1].isupper():
            continue
        if _in_spans(m.start(), spans):
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


def merge_duplicate_stories(scored: list[dict]) -> list[dict]:
    """scored is sorted by selectionScore descending, so the first member
    of any same-story group encountered is already the highest-scoring
    one -- it stays as the item's own fields, and every later match in
    the group is folded into its "additionalSources" list instead of
    appearing as its own separate candidate. Calendar aggregates are
    exempt: they're built from our own tournament data, not outlet
    reporting, so "two outlets covered the same event" doesn't apply."""
    result: list[dict] = []
    for item in scored:
        if item["kind"] in CALENDAR_KINDS:
            result.append(item)
            continue
        match = next(
            (existing for existing in result if existing["kind"] not in CALENDAR_KINDS and _is_same_story(item, existing)),
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

    scored = []
    for item in candidates:
        if is_promotional(item):
            continue
        total, breakdown = score_item(item)
        if total <= 0:
            continue
        scored.append({**item, "selectionScore": total, "scoreBreakdown": breakdown})

    scored.sort(key=lambda x: x["selectionScore"], reverse=True)
    scored = dedupe_by_topic(scored)
    scored = merge_duplicate_stories(scored)

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
        print(f"  [{item['selectionScore']:>3}] {item['sourceName']}: {item['title']}")
        for extra in item.get("additionalSources", []):
            print(f"        + merged with {extra['sourceName']}: {extra['title']}")


if __name__ == "__main__":
    main()
