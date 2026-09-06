"""Historical fallback for chess.com/FIDE ingestion, used only by
backfill.py -- their RSS feeds (see ingest.py's fetch_rss) only ever carry
a rolling recent window (found the hard way: items from a week or two back
had already scrolled out of both feeds by the time a second backfill run
needed them). These functions hit each source's actual archive instead,
which goes back much further, for whatever date range RSS didn't cover.

The live daily pipeline (ingest.py) never calls these -- it only ever
wants "since last run," which RSS already handles fine and more cheaply.
"""

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

REQUEST_TIMEOUT = 20
USER_AGENT = "chessori-ingest/0.1 (+https://github.com/Sabbetus/chess-news-website)"

CHESS_COM_NEWS_URL = "https://www.chess.com/news"
FIDE_API_URL = "https://www.fide.com/wp-json/wp/v2/posts"

# Safety cap so a bug (or a source restructuring its pagination) can't spin
# forever -- 40 pages is far more than one date-range backfill should ever
# need at ~24 items/page.
MAX_PAGES = 40


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def fetch_chesscom_archive(start: date, end: date) -> list[dict]:
    """Scrapes chess.com's paginated news archive (/news?page=N), which
    goes back much further than the RSS feed, for items published within
    [start, end]. The archive is reverse-chronological, so this pages
    forward until it's seen a full page entirely older than `start`."""
    items = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{CHESS_COM_NEWS_URL}?page={page}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError:
            break

        blocks = re.findall(r'<article class="post-preview-component">.*?</article>', body, re.DOTALL)
        if not blocks:
            break

        page_has_item_in_range = False
        page_all_older_than_start = True
        for block in blocks:
            href_match = re.search(r'class="post-preview-title"\s*href="([^"]+)"', block)
            title_match = re.search(r'class="post-preview-title"[^>]*>\s*([^<]+?)\s*</a>', block, re.DOTALL)
            date_match = re.search(r'<time\s+datetime="([^"]+)"', block)
            excerpt_match = re.search(r'class="post-preview-excerpt">\s*(.*?)\s*</p>', block, re.DOTALL)
            if not (href_match and title_match and date_match):
                continue

            published = datetime.strptime(date_match.group(1)[:16], "%Y-%m-%d %H:%M")
            item_date = published.date()
            if item_date < start:
                continue
            page_all_older_than_start = False
            if item_date > end:
                continue
            page_has_item_in_range = True

            items.append(
                {
                    "kind": "news",
                    "sourceName": "Chess.com",
                    "sourceTier": "drama",
                    "sourceUrl": href_match.group(1),
                    "title": html.unescape(title_match.group(1).strip()),
                    "summary": _strip_html(excerpt_match.group(1)) if excerpt_match else "",
                    "publishedAt": published.replace(tzinfo=timezone.utc).isoformat(),
                }
            )

        if page_all_older_than_start:
            break

    return items


def fetch_fide_archive(start: date, end: date) -> list[dict]:
    """FIDE's WordPress REST API supports date filtering directly
    (?after=&before=), so this is a normal paginated query rather than a
    scrape -- no need to walk backward through unrelated pages."""
    items = []
    after = f"{start.isoformat()}T00:00:00"
    before = f"{end.isoformat()}T23:59:59"

    for page in range(1, MAX_PAGES + 1):
        query = urllib.parse.urlencode(
            {"after": after, "before": before, "per_page": 50, "page": page, "orderby": "date", "order": "desc"}
        )
        request = urllib.request.Request(f"{FIDE_API_URL}?{query}", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                posts = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 400:  # page beyond the last one -- WP returns 400, not an empty list
                break
            raise
        except urllib.error.URLError:
            break

        if not posts:
            break

        for post in posts:
            items.append(
                {
                    "kind": "news",
                    "sourceName": "FIDE",
                    "sourceTier": "serious",
                    "sourceUrl": post["link"],
                    "title": _strip_html(post["title"]["rendered"]),
                    "summary": _strip_html(post["excerpt"]["rendered"])[:300],
                    "publishedAt": post["date"] + "+00:00",
                }
            )

        if len(posts) < 50:
            break

    return items
