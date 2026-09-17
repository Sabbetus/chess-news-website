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

MIN_SHARED_NAMES_FOR_SAME_STORY = 2


def _name_bigrams(item: dict) -> set[tuple[str, str]]:
    """Adjacent-word pairs where both words are capitalized and neither is
    generic -- a cheap proxy for "this text names a specific person or
    place", reliable enough to tell "Arjun Erigaisi" apart from ordinary
    capitalized sentence starts without needing real NER."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    words = [w for w in re.findall(r"[A-Za-z']+", text) if w]
    bigrams = set()
    for a, b in zip(words, words[1:]):
        if not (a[:1].isupper() and b[:1].isupper()):
            continue
        la, lb = a.lower().rstrip("'s"), b.lower().rstrip("'s")
        if la in GENERIC_NAME_WORDS or lb in GENERIC_NAME_WORDS:
            continue
        bigrams.add((la, lb))
    return bigrams


def _is_same_story(a: dict, b: dict) -> bool:
    return len(_name_bigrams(a) & _name_bigrams(b)) >= MIN_SHARED_NAMES_FOR_SAME_STORY


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
