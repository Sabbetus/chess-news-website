"""
Selection: scores every candidate in data/candidates.json with a simple,
explainable heuristic and picks the day's articles -- 3 guaranteed, up to
5 more if they clear the quality bar (SCORE_THRESHOLD_FOR_4_5). This is a
v1 heuristic, expected to need tuning once real data is flowing; keep the
scoring criteria named and separable so that's easy.

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

MIN_DAILY_ARTICLES = 3
MAX_DAILY_ARTICLES = 5
SCORE_THRESHOLD_FOR_EXTRA = 60  # out of 100 -- above this, articles 4-5 are allowed through

# Higher-traffic / more clearly newsworthy outlets get a base bump.
SOURCE_TIER_SCORE = {
    "drama": 25,    # Chess.com -- high engagement potential
    "serious": 20,  # FIDE -- official/authoritative
    "own-data": 15, # calendar previews -- always relevant to us, but not breaking news
}

# Keyword weight groups: title/summary matches add points per hit (capped).
KEYWORD_WEIGHTS = {
    # High-interest storylines readers actually click on.
    "scandal": 20, "cheat": 20, "cheating": 20, "controversy": 15, "banned": 15,
    "world champion": 15, "world championship": 15, "olympiad": 12,
    "record": 10, "youngest": 10, "grandmaster": 8, "gm title": 8,
    "prize": 6, "upset": 8, "protest": 10, "investigation": 12,
}
MAX_KEYWORD_SCORE = 30

# Nordic/regional relevance -- ties into the Nordic-angle lens.
NORDIC_KEYWORDS = ["norway", "sweden", "denmark", "finland", "iceland", "nordic", "scandinavia"]
NORDIC_BONUS = 15

MIN_CALENDAR_PLAYERS = 150  # below this, a calendar preview isn't "notable" enough


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

    if item["kind"] == "calendar-preview":
        players = (item.get("tournamentData") or {}).get("playersRegistered") or 0
        if not isinstance(players, (int, float)) or players < MIN_CALENDAR_PLAYERS:
            breakdown["calendarSizeGate"] = -1000  # effectively excludes it
        else:
            # Scale a modest bonus with size, capped -- bigger tournaments are
            # more broadly interesting previews.
            breakdown["calendarSizeGate"] = min(int(players / 50), 20)

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


def main() -> None:
    if not CANDIDATES_PATH.exists():
        print("No candidates.json found -- run ingest.py first.")
        return

    candidates = json.loads(CANDIDATES_PATH.read_text())

    scored = []
    for item in candidates:
        total, breakdown = score_item(item)
        if total <= 0:
            continue
        scored.append({**item, "selectionScore": total, "scoreBreakdown": breakdown})

    scored.sort(key=lambda x: x["selectionScore"], reverse=True)
    scored = dedupe_by_topic(scored)

    guaranteed = scored[:MIN_DAILY_ARTICLES]
    extra_pool = scored[MIN_DAILY_ARTICLES:MAX_DAILY_ARTICLES]
    extras = [item for item in extra_pool if item["selectionScore"] >= SCORE_THRESHOLD_FOR_EXTRA]

    selected = guaranteed + extras

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SELECTED_PATH.write_text(json.dumps(selected, indent=2))

    print(f"Selected {len(selected)} item(s) from {len(candidates)} candidate(s):")
    for item in selected:
        print(f"  [{item['selectionScore']:>3}] {item['sourceName']}: {item['title']}")


if __name__ == "__main__":
    main()
