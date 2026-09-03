"""
Ingestion: pulls candidate news items from the three configured sources and
writes them to data/candidates.json for the selection step to score.

Sources:
  - Chess.com news RSS   (https://www.chess.com/rss/news)      -- "drama" beat
  - FIDE news RSS        (https://www.fide.com/feed/)          -- official/serious beat
  - chesstournamentcalendar.com's own tournament data          -- per-continent
    monthly aggregate pieces (NOT single-tournament previews -- a preview of
    one tournament is thin and duplicates what the calendar site itself
    already shows; an aggregate view across a continent is something no
    other outlet can produce, because it's our dataset). Two aggregate
    types per continent, see continents.py and the docstring on
    fetch_calendar_aggregates() below.

Each run only adds items not already seen (by URL, or by a synthetic id
for calendar aggregates -- continent + month + type) -- data/seen.json
tracks what's been ingested before so re-runs don't reprocess the same
period twice.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from continents import CONTINENT_CODES, CONTINENT_NAMES, continent_code_for, continent_url

DATA_DIR = Path(__file__).parent.parent / "data"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
SEEN_PATH = DATA_DIR / "seen.json"

CHESS_COM_RSS = "https://www.chess.com/rss/news"
FIDE_RSS = "https://www.fide.com/feed/"
CALENDAR_DATA_URL = "https://chesstournamentcalendar.com/data/tournaments.json"
# archive.json carries concluded tournaments (tournaments.json is upcoming-only),
# needed for the "biggest tournaments of last month" retrospective aggregate.
CALENDAR_ARCHIVE_URL = "https://chesstournamentcalendar.com/data/archive.json"

REQUEST_TIMEOUT = 20
USER_AGENT = "chess-news-ingest/0.1 (+https://github.com/Sabbetus/chess-news-website)"


def load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=2))


def fetch_rss(url: str, source_name: str, source_tier: str) -> list[dict]:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    items = []
    for entry in parsed.entries:
        link = entry.get("link")
        title = entry.get("title")
        if not link or not title:
            continue
        published = entry.get("published_parsed")
        published_iso = (
            datetime(*published[:6], tzinfo=timezone.utc).isoformat()
            if published
            else None
        )
        summary = re.sub("<[^>]+>", "", entry.get("summary", "")).strip()
        items.append(
            {
                "kind": "news",
                "sourceName": source_name,
                "sourceTier": source_tier,
                "sourceUrl": link,
                "title": title,
                "summary": summary,
                "publishedAt": published_iso,
            }
        )
    return items


NOTABLE_NAME_KEYWORDS = [
    "championship", "invitational", "national", "international", "cup",
    "festival", "open", "grand prix", "masters", "classic",
]
MAX_TOURNAMENTS_PER_AGGREGATE = 20

# Fields actually useful for drafting -- archive.json entries carry bulky
# extras (playerHistory, consecutiveMisses, lastSeen, ...) that only add
# prompt noise/cost with no drafting value.
TOURNAMENT_FIELDS_FOR_PROMPT = [
    "name", "slug", "startDate", "endDate", "city", "country", "countryCode",
    "rounds", "timeControl", "playersRegistered", "prizePool", "currency",
    "ratingRequirement", "organizer", "websiteUrl",
]


def _trim_tournament(t: dict) -> dict:
    return {k: t[k] for k in TOURNAMENT_FIELDS_FOR_PROMPT if k in t}


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def _shift_month(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _notability_score(t: dict) -> int:
    """Heuristic for ranking tournaments that lack a reliable playersRegistered
    figure (e.g. most US entries) -- used only for the 'coming up' aggregate,
    where the goal is to surface highlights, not a strict ranking."""
    score = 0
    name = (t.get("name") or "").lower()
    score += sum(3 for kw in NOTABLE_NAME_KEYWORDS if kw in name)
    if t.get("ratingRequirement"):
        score += 3
    if t.get("prizePool"):
        score += 3
    rounds = t.get("rounds")
    if isinstance(rounds, (int, float)) and rounds >= 7:
        score += 2
    if t.get("registrationUrl") or t.get("websiteUrl"):
        score += 1
    return score


# Publishing schedule within the month, per user decision: "biggest tournaments"
# (a look back at last month) runs in the first half of the month, one continent
# per scheduled day; "what's coming up" (a look ahead at next month) runs in the
# second half. This guarantees at most one calendar-sourced article per day --
# ingestion only ever builds the single item scheduled for today, if any -- and
# spreads the 6 continents x 2 article types across the month instead of
# dumping them all on day 1.
CALENDAR_SCHEDULE = {
    1: ("calendar-biggest", "EU"), 3: ("calendar-biggest", "AS"),
    5: ("calendar-biggest", "NA"), 7: ("calendar-biggest", "SA"),
    9: ("calendar-biggest", "AF"), 11: ("calendar-biggest", "OC"),
    16: ("calendar-comingup", "EU"), 18: ("calendar-comingup", "AS"),
    20: ("calendar-comingup", "NA"), 22: ("calendar-comingup", "SA"),
    24: ("calendar-comingup", "AF"), 26: ("calendar-comingup", "OC"),
}


def in_range(t: dict, start: date, end: date) -> bool:
    raw = t.get("startDate")
    if not raw:
        return False
    try:
        d = datetime.fromisoformat(raw).date()
    except ValueError:
        return False
    return start <= d < end


def _build_biggest(code: str, today: date) -> dict | None:
    """'Biggest tournaments' aggregate: last month's concluded tournaments in
    this continent, ranked by playersRegistered (unreliable/missing for some
    countries, e.g. most US entries -- those just won't rank, which is an
    honest reflection of the data)."""
    archive_resp = requests.get(CALENDAR_ARCHIVE_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    archive_resp.raise_for_status()
    concluded = [t for t in archive_resp.json() if t.get("status") == "concluded"]

    last_month_first = _shift_month(date(today.year, today.month, 1), -1)
    last_month_start, last_month_end = _month_bounds(last_month_first.year, last_month_first.month)
    month_label = last_month_start.strftime("%B %Y")

    pool = [
        t for t in concluded
        if continent_code_for(t.get("countryCode")) == code and in_range(t, last_month_start, last_month_end)
    ]
    ranked = sorted(
        (t for t in pool if isinstance(t.get("playersRegistered"), (int, float)) and t["playersRegistered"] > 0),
        key=lambda t: t["playersRegistered"],
        reverse=True,
    )[:MAX_TOURNAMENTS_PER_AGGREGATE]
    if not ranked:
        return None  # nothing rankable this continent this month -- skip rather than publish an empty piece

    return {
        "kind": "calendar-biggest",
        "sourceName": "Chess Tournament Calendar",
        "sourceTier": "own-data",
        "sourceUrl": continent_url(code),
        "dedupeKey": f"calendar-biggest:{code}:{last_month_start.isoformat()}",
        "title": f"Biggest {CONTINENT_NAMES[code]} tournaments of {month_label}",
        "summary": (
            f"{len(pool)} tracked tournaments in {CONTINENT_NAMES[code]} during {month_label}, "
            f"{len(ranked)} with a known player count, ranked by players registered."
        ),
        "publishedAt": None,
        "continentCode": code,
        "continentName": CONTINENT_NAMES[code],
        "monthLabel": month_label,
        "totalTracked": len(pool),
        "tournamentData": [_trim_tournament(t) for t in ranked],
    }


def _build_comingup(code: str, today: date) -> dict | None:
    """'What's coming up' aggregate: next month's scheduled tournaments in this
    continent. Ranked by playersRegistered where available, falling back to a
    notability heuristic for countries without reliable player counts (e.g.
    North America) so those aren't just left empty."""
    upcoming_resp = requests.get(CALENDAR_DATA_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    upcoming_resp.raise_for_status()
    upcoming = upcoming_resp.json()

    next_month_first = _shift_month(date(today.year, today.month, 1), 1)
    next_month_start, next_month_end = _month_bounds(next_month_first.year, next_month_first.month)
    month_label = next_month_start.strftime("%B %Y")

    pool = [
        t for t in upcoming
        if continent_code_for(t.get("countryCode")) == code and in_range(t, next_month_start, next_month_end)
    ]
    if not pool:
        return None

    with_players = [t for t in pool if isinstance(t.get("playersRegistered"), (int, float)) and t["playersRegistered"] > 0]
    without_players = [t for t in pool if t not in with_players]
    with_players.sort(key=lambda t: t["playersRegistered"], reverse=True)
    without_players.sort(key=_notability_score, reverse=True)
    highlights = (with_players + without_players)[:MAX_TOURNAMENTS_PER_AGGREGATE]

    return {
        "kind": "calendar-comingup",
        "sourceName": "Chess Tournament Calendar",
        "sourceTier": "own-data",
        "sourceUrl": continent_url(code),
        "dedupeKey": f"calendar-comingup:{code}:{next_month_start.isoformat()}",
        "title": f"What's coming up in {CONTINENT_NAMES[code]} chess: {month_label}",
        "summary": (
            f"{len(pool)} tracked tournaments in {CONTINENT_NAMES[code]} during {month_label} "
            f"({len(with_players)} with a known player count)."
        ),
        "publishedAt": None,
        "continentCode": code,
        "continentName": CONTINENT_NAMES[code],
        "monthLabel": month_label,
        "totalTracked": len(pool),
        "tournamentData": [_trim_tournament(t) for t in highlights],
    }


def fetch_calendar_aggregates() -> list[dict]:
    """Returns at most one per-continent monthly aggregate candidate -- whichever
    is due today per CALENDAR_SCHEDULE -- or an empty list on unscheduled days."""
    today = datetime.now(timezone.utc).date()
    scheduled = CALENDAR_SCHEDULE.get(today.day)
    if scheduled is None:
        return []

    kind, code = scheduled
    item = _build_biggest(code, today) if kind == "calendar-biggest" else _build_comingup(code, today)
    return [item] if item else []


def dedupe_key(item: dict) -> str:
    return item.get("dedupeKey") or item["sourceUrl"]


def main() -> None:
    seen = load_seen()

    raw_items: list[dict] = []
    raw_items += fetch_rss(CHESS_COM_RSS, "Chess.com", "drama")
    raw_items += fetch_rss(FIDE_RSS, "FIDE", "serious")
    raw_items += fetch_calendar_aggregates()

    new_items = [item for item in raw_items if dedupe_key(item) not in seen]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(new_items, indent=2))

    seen.update(dedupe_key(item) for item in new_items)
    save_seen(seen)

    print(f"Ingested {len(new_items)} new candidate(s) out of {len(raw_items)} fetched.")


if __name__ == "__main__":
    main()
