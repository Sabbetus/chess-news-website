"""Fan buzz: saves the titles of r/chess's top posts of the day to
data/trends.json, which selection.py uses as a small, capped scoring nudge
for candidate stories the chess community is already talking about.

Only titles are read, only as a ranking signal -- nothing from Reddit is ever
republished, quoted or shown on the site, which keeps clear of Reddit's
API/content terms and of an unmoderated feed of memes and accusations about
real people. Uses the public RSS feed with a descriptive User-Agent (Reddit
rate-limits generic browser-style agents, and shared cloud IPs get throttled
regardless), so this is best-effort by design: on any failure it leaves the
previous file alone and exits 0, and selection ignores a file older than
selection.TRENDS_MAX_AGE_HOURS -- a Reddit outage means no bonus, never a
failed pipeline run.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

DATA_DIR = Path(__file__).parent.parent / "data"
TRENDS_PATH = DATA_DIR / "trends.json"

# Reddit started answering 404 at the first address from GitHub's runners
# around 2026-11-18, which silently switched the fan-buzz nudge off. The
# same top-of-day listing is tried at Reddit's other official addresses, in
# order; the first that answers with posts wins.
REDDIT_FEEDS = [
    ("rss", "https://www.reddit.com/r/chess/top/.rss?t=day"),
    ("rss", "https://old.reddit.com/r/chess/top/.rss?t=day"),
    ("json", "https://www.reddit.com/r/chess/top.json?t=day&limit=25"),
    ("json", "https://old.reddit.com/r/chess/top.json?t=day&limit=25"),
]
REDDIT_RSS = REDDIT_FEEDS[0][1]
USER_AGENT = "chess-herald-trends/0.1 (+https://github.com/Sabbetus/chess-news-website)"
REQUEST_TIMEOUT = 20
MAX_POSTS = 25


def _titles(kind: str, content: bytes) -> list[str]:
    if kind == "json":
        children = json.loads(content).get("data", {}).get("children", [])
        return [c["data"]["title"].strip() for c in children[:MAX_POSTS] if c.get("data", {}).get("title")]
    parsed = feedparser.parse(content)
    return [e.title.strip() for e in parsed.entries[:MAX_POSTS] if e.get("title")]


def fetch_titles() -> tuple[list[str], str]:
    """(titles, address used). Raises the last error when every address fails."""
    last: Exception | None = None
    for kind, url in REDDIT_FEEDS:
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            titles = _titles(kind, resp.content)
            if titles:
                return titles, url
        except (requests.RequestException, ValueError) as exc:
            print(f"  r/chess: {url} failed ({type(exc).__name__}: {exc})", file=sys.stderr)
            last = exc if isinstance(exc, requests.RequestException) else requests.RequestException(str(exc))
    if last:
        raise last
    return [], ""


def main() -> None:
    try:
        titles, used = fetch_titles()
    except requests.RequestException as exc:
        print(f"r/chess trends unavailable ({type(exc).__name__}: {exc}) -- skipping, no fan-buzz bonus today.", file=sys.stderr)
        return
    if not titles:
        print("r/chess feed returned no posts -- skipping, no fan-buzz bonus today.", file=sys.stderr)
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRENDS_PATH.write_text(
        json.dumps(
            {"fetchedAt": datetime.now(timezone.utc).isoformat(), "source": used, "titles": titles},
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"Saved {len(titles)} r/chess top-of-day title(s) to {TRENDS_PATH.name}.")


if __name__ == "__main__":
    main()
