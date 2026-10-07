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

from article_text import fetch_full_article_text
from continents import CONTINENT_CODES, CONTINENT_NAMES, continent_code_for, continent_url

DATA_DIR = Path(__file__).parent.parent / "data"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
SEEN_PATH = DATA_DIR / "seen.json"

CHESS_COM_RSS = "https://www.chess.com/rss/news"
FIDE_RSS = "https://www.fide.com/feed/"
CHESSBASE_RSS = "https://en.chessbase.com/feed"
# ChessBase's feed holds ~100 items spanning over a year (Chess.com and FIDE
# hold the last few weeks), so without an age cap the first run would treat
# every old article as fresh news.
CHESSBASE_MAX_AGE_DAYS = 4
CALENDAR_DATA_URL = "https://chesstournamentcalendar.com/data/tournaments.json"
# archive-all.json carries concluded tournaments from every source
# (tournaments.json is upcoming-only), for the look-back aggregate. The older
# archive.json only kept chess-results events, so FIDE-listed US and
# Australian tournaments vanished once finished (switched 2026-10-05).
CALENDAR_ARCHIVE_URL = "https://chesstournamentcalendar.com/data/archive-all.json"

REQUEST_TIMEOUT = 20
USER_AGENT = "chess-herald-ingest/0.1 (+https://github.com/Sabbetus/chess-news-website)"


def load_seen() -> set[str]:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(sorted(seen), indent=2))


def fetch_rss(url: str, source_name: str, source_tier: str, max_age_days: int | None = None) -> list[dict]:
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
        if max_age_days is not None and (
            published is None or datetime.now(timezone.utc) - datetime(*published[:6], tzinfo=timezone.utc) > timedelta(days=max_age_days)
        ):
            continue
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


# Sources whose feed carries only a teaser. Chess.com's is cut off mid-word
# with "...", so a truncated tail is the tell; ChessBase's is the lede
# paragraph with no marker at all, so every ChessBase item needs the full
# page (see article_text.py for why drafting from a teaser went wrong).
ALWAYS_FETCH_FULL_TEXT = {"ChessBase"}
TRUNCATION_MARKERS = ("...", "\u2026")
# Under this, a ChessBase page has no article worth writing about -- most
# often a video-only post (an interview that lives on their YouTube channel
# and is just an embed and a headline on the site; caught in testing: the
# Keymer "interview" page is 141 characters).
MIN_FULL_TEXT_CHARS = 800


def summary_is_truncated(summary: str) -> bool:
    return summary.rstrip().endswith(TRUNCATION_MARKERS)


def needs_full_text(item: dict) -> bool:
    return item["kind"] == "news" and (
        item["sourceName"] in ALWAYS_FETCH_FULL_TEXT or summary_is_truncated(item.get("summary", ""))
    )


def restore_full_text(items: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Replaces a teaser with the article's real text. Returns
    (usable, retry_later, no_substance): an item whose page couldn't be
    fetched is retry_later (a transient failure shouldn't cost us the
    story), one whose page has too little text is no_substance (it never
    will have more), and neither may be drafted from the teaser."""
    usable, retry_later, no_substance = [], [], []
    for item in items:
        if not needs_full_text(item):
            usable.append(item)
            continue
        full = fetch_full_article_text(item["sourceUrl"])
        if full is None:
            retry_later.append(item)
        elif item["sourceName"] in ALWAYS_FETCH_FULL_TEXT and len(full) < MIN_FULL_TEXT_CHARS:
            no_substance.append(item)
        else:
            usable.append({**item, "summary": full})
    return usable, retry_later, no_substance


# Both calendar pieces list the month's most NOTABLE tournaments, not just
# the biggest fields (user's call, 2026-10-05): a multi-day classical open
# matters more than a one-day school rapid with more players, and countries
# that don't report player counts (the US, Australia) must still rank.
NOTABLE_NAME_KEYWORDS = [
    "championship", "invitational", "national", "international", "cup",
    "festival", "open", "grand prix", "masters", "classic", "norm",
    "memorial", "premier", "elite",
]
# Sections and events that are by nature minor: rating-capped sections of a
# bigger event, and school/youth/club-night events.
MINOR_NAME_PATTERNS = re.compile(
    r"\bu\s?-?\d{2,4}\b|\bunder\s?(?:\d{2,4}|section)\b|sub[\s-]?\d{1,2}\b|\b\d{3,4}\s?-\s?\d{3,4}\b"
    r"|\breserves?\b|\bminor\b|\bamateur|\bnovice|scholastic|school|escolar|colegio|kids|junior|juvenil|infantil|primary|secundaria|menores|juventud|intercolegiad"
    r"|quads?\b|action\b|club night|weekly|ladder|simul",
    re.IGNORECASE,
)
MAX_TOURNAMENTS_PER_AGGREGATE = 20
# No single country may fill the list while others have entries left --
# caught live 2026-10-05: 12 of North America's top 20 were Mexican school
# and club events.
MAX_PER_COUNTRY = 6

# Fields actually useful for drafting -- archive-all.json entries carry bulky
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


def _duration_days(t: dict) -> int:
    try:
        start = datetime.fromisoformat(t["startDate"]).date()
        end = datetime.fromisoformat(t.get("endDate") or t["startDate"]).date()
    except (KeyError, ValueError, TypeError):
        return 1
    return max(1, (end - start).days + 1)


def _notability_score(t: dict) -> float:
    """How notable a tournament is, from the fields the calendar has for
    every source (FIDE-listed US/Australian events have no player counts)."""
    name = (t.get("name") or "").lower()
    tc = (t.get("timeControl") or "").lower()
    score = {"classical": 10, "standard": 10, "rapid": 4, "blitz": 1}.get(tc, 3)
    days = _duration_days(t)
    score += 6 if days >= 4 else 4 if days >= 2 else 0
    score += min(9, sum(3 for kw in NOTABLE_NAME_KEYWORDS if kw in name))
    if MINOR_NAME_PATTERNS.search(name):
        score -= 8
    players = t.get("playersRegistered")
    if isinstance(players, (int, float)) and players > 0:
        score += min(8, players / 25)
        # Only a known count can show a small field: FIDE-listed US and
        # Australian events have no count at all and must not be penalised.
        if players < 10:
            score -= 6
    if t.get("ratingRequirement"):
        score += 2
    if t.get("prizePool"):
        score += 3
    rounds = t.get("rounds")
    if isinstance(rounds, (int, float)) and rounds >= 7:
        score += 2
    return score


_SECTION_SUFFIX_RE = re.compile(
    r"\s*[-\u2013:|(]\s*(?:group|grupo|section|secci[oó]n|open|abierto|torneo|[a-e]\b|u\d+|sub\s?\d+|\d{3,4}\s?-\s?\d{3,4}).*$",
    re.IGNORECASE,
)


def _event_key(t: dict) -> tuple:
    base = _SECTION_SUFFIX_RE.sub("", (t.get("name") or "").strip()).lower()
    return (base, t.get("countryCode"), t.get("city"), t.get("startDate"))


def _merge_sections(pool: list[dict]) -> list[dict]:
    """Sections of one event (same base name, place and start date) count
    once: the best-scoring section stands in for the event, with the
    sections' player counts summed when all are known."""
    groups: dict[tuple, list[dict]] = {}
    for t in pool:
        groups.setdefault(_event_key(t), []).append(t)
    merged = []
    for group in groups.values():
        best = max(group, key=_notability_score)
        if len(group) > 1:
            counts = [g.get("playersRegistered") for g in group]
            if all(isinstance(c, (int, float)) and c > 0 for c in counts):
                best = {**best, "playersRegistered": sum(counts)}
        merged.append(best)
    return merged


def _rank_notable(pool: list[dict]) -> list[dict]:
    """Top MAX_TOURNAMENTS_PER_AGGREGATE by notability, at most
    MAX_PER_COUNTRY per country unless nothing else is left."""
    pool = _merge_sections(pool)
    ranked = sorted(pool, key=lambda t: (_notability_score(t), t.get("playersRegistered") or 0), reverse=True)
    picked, per_country, overflow = [], {}, []
    for t in ranked:
        country = t.get("countryCode")
        if per_country.get(country, 0) < MAX_PER_COUNTRY:
            picked.append(t)
            per_country[country] = per_country.get(country, 0) + 1
        else:
            overflow.append(t)
        if len(picked) == MAX_TOURNAMENTS_PER_AGGREGATE:
            return picked
    return (picked + overflow)[:MAX_TOURNAMENTS_PER_AGGREGATE]


# Publishing schedule within the month, per user decision: "biggest tournaments"
# (a look back at last month) runs first, one continent per scheduled day,
# immediately followed by "what's coming up" (a look ahead at next month) --
# back-to-back, days 1-24, so the run of 12 calendar slots leaves any gap at
# the *end* of the month (day 25 through month-end) rather than splitting it
# in the middle. This guarantees at most one calendar-sourced article per
# day -- ingestion only ever builds the single item scheduled for today, if
# any -- and spreads the 6 continents x 2 article types across the month
# instead of dumping them all on day 1.
CALENDAR_SCHEDULE = {
    1: ("calendar-biggest", "EU"), 3: ("calendar-biggest", "AS"),
    5: ("calendar-biggest", "NA"), 7: ("calendar-biggest", "SA"),
    9: ("calendar-biggest", "AF"), 11: ("calendar-biggest", "OC"),
    14: ("calendar-comingup", "EU"), 16: ("calendar-comingup", "AS"),
    18: ("calendar-comingup", "NA"), 20: ("calendar-comingup", "SA"),
    22: ("calendar-comingup", "AF"), 24: ("calendar-comingup", "OC"),
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
    """Look-back aggregate: last month's most notable concluded tournaments
    in this continent (see _notability_score). The kind keeps its original
    "calendar-biggest" name so dedupe keys and frontmatter stay stable."""
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
    ranked = _rank_notable(pool)
    if not ranked:
        return None  # nothing tracked this continent this month -- skip rather than publish an empty piece

    return {
        "kind": "calendar-biggest",
        "sourceName": "Chess Tournament Calendar",
        "sourceTier": "own-data",
        "sourceUrl": continent_url(code),
        "dedupeKey": f"calendar-biggest:{code}:{last_month_start.isoformat()}",
        "title": f"Most notable {CONTINENT_NAMES[code]} tournaments of {month_label}",
        "summary": (
            f"{len(pool)} tracked tournaments in {CONTINENT_NAMES[code]} during {month_label}; "
            f"the {len(ranked)} most notable, ranked by format, length, event type and field size."
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
    continent, ranked by notability (see _notability_score), which works the
    same for countries with and without reported player counts."""
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
    highlights = _rank_notable(pool)

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
    # The newest source is the only one allowed to fail without stopping the
    # run: losing a day of ChessBase is fine, losing the whole day is not.
    try:
        raw_items += fetch_rss(CHESSBASE_RSS, "ChessBase", "features", max_age_days=CHESSBASE_MAX_AGE_DAYS)
    except requests.RequestException as exc:
        print(f"ChessBase feed unavailable ({type(exc).__name__}: {exc}) -- continuing without it.")
    raw_items += fetch_calendar_aggregates()

    new_items = [item for item in raw_items if dedupe_key(item) not in seen]
    new_items, retry_later, no_substance = restore_full_text(new_items)
    # retry_later is deliberately left out of `seen`: a transient fetch
    # failure shouldn't permanently cost us the story, so the next run
    # retries it for as long as it stays in the feed. no_substance goes
    # into `seen` -- refetching a video-only page every day gets nothing.
    if retry_later:
        print(f"Skipping {len(retry_later)} item(s) whose full text couldn't be fetched (will retry next run):")
        for item in retry_later:
            print(f"  {item['title']}")
    if no_substance:
        print(f"Skipping {len(no_substance)} item(s) with under {MIN_FULL_TEXT_CHARS} characters of article text (video-only or stub posts):")
        for item in no_substance:
            print(f"  {item['title']}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(new_items, indent=2))

    seen.update(dedupe_key(item) for item in new_items + no_substance)
    save_seen(seen)

    print(f"Ingested {len(new_items)} new candidate(s) out of {len(raw_items)} fetched.")


if __name__ == "__main__":
    main()
