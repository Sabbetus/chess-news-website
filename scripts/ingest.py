"""
Ingestion: pulls candidate news items from the three configured sources and
writes them to data/candidates.json for the selection step to score.

Sources:
  - Chess.com news RSS   (https://www.chess.com/rss/news)      -- "drama" beat
  - FIDE news RSS        (https://www.fide.com/feed/)          -- official/serious beat
  - chesstournamentcalendar.com's own tournament data          -- preview-story ideas
    (upcoming large/notable tournaments become candidate "preview" items,
    not news items -- they carry no external sourceUrl article, just our
    own data, so the AI drafting step treats them differently: full
    original writing grounded in our database rather than commentary on
    someone else's article.)

Each run only adds items not already seen (by URL, or by tournament slug
for the calendar source) -- data/seen.json tracks what's been ingested
before so re-runs don't reprocess the same stories.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

DATA_DIR = Path(__file__).parent.parent / "data"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
SEEN_PATH = DATA_DIR / "seen.json"

CHESS_COM_RSS = "https://www.chess.com/rss/news"
FIDE_RSS = "https://www.fide.com/feed/"
CALENDAR_DATA_URL = "https://chesstournamentcalendar.com/data/tournaments.json"

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


def fetch_calendar_previews() -> list[dict]:
    """Upcoming tournaments from our own calendar data, as preview-story candidates."""
    resp = requests.get(CALENDAR_DATA_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    tournaments = resp.json()

    now = datetime.now(timezone.utc).date()
    items = []
    for t in tournaments:
        start = t.get("startDate") or t.get("start_date")
        if not start:
            continue
        try:
            start_date = datetime.fromisoformat(start).date()
        except ValueError:
            continue
        days_out = (start_date - now).days
        # Only tournaments starting soon-ish make good "preview" candidates --
        # too far out and there's nothing concrete yet to write about.
        if not (0 <= days_out <= 21):
            continue
        slug = t.get("slug")
        if not slug:
            continue
        items.append(
            {
                "kind": "calendar-preview",
                "sourceName": "Chess Tournament Calendar",
                "sourceTier": "own-data",
                "sourceUrl": f"https://chesstournamentcalendar.com/tournament/{slug}/",
                "title": t.get("name", slug),
                "summary": (
                    f"Starts {start_date.isoformat()}, "
                    f"{t.get('city', 'unknown city')}, {t.get('country', '')}. "
                    f"Players registered: {t.get('playersRegistered', 'unknown')}."
                ),
                "publishedAt": None,
                "tournamentData": t,
            }
        )
    return items


def main() -> None:
    seen = load_seen()

    raw_items: list[dict] = []
    raw_items += fetch_rss(CHESS_COM_RSS, "Chess.com", "drama")
    raw_items += fetch_rss(FIDE_RSS, "FIDE", "serious")
    raw_items += fetch_calendar_previews()

    new_items = [item for item in raw_items if item["sourceUrl"] not in seen]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_PATH.write_text(json.dumps(new_items, indent=2))

    seen.update(item["sourceUrl"] for item in new_items)
    save_seen(seen)

    print(f"Ingested {len(new_items)} new candidate(s) out of {len(raw_items)} fetched.")


if __name__ == "__main__":
    main()
