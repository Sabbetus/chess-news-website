"""Post published articles to Facebook and Threads, a few at a time.

Run on a schedule (see .github/workflows/social.yml). Each run:
  1. Scans src/content/articles/ for every reviewStatus: "published" article
     and adds any not already tracked to data/social-queue.json, ordered by
     publishDate ascending -- this both seeds the initial backlog and picks
     up newly merged articles automatically, with no separate "enqueue on
     merge" step needed.
  2. Posts the oldest POSTS_PER_RUN still-unposted entries to Facebook and
     Threads together (same article, same run) -- each article's socialCopy
     frontmatter (a hook written for sharing, distinct from its page title)
     plus the article link.
  3. Marks each as posted (with a timestamp) and writes the queue back.

Oldest-first, not newest-first: new articles just join the back of the
queue, so a growing backlog of not-yet-announced-on-social articles
actually drains over time instead of being perpetually skipped in favor
of whatever published today.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = REPO_ROOT / "src" / "content" / "articles"
QUEUE_PATH = REPO_ROOT / "data" / "social-queue.json"
SITE_URL = "https://chessori.com"

# Drop to 1 once the backlog of already-published, not-yet-posted articles
# is cleared -- 2/run x 4 runs/day comfortably outpaces the ~2-3 articles/day
# the pipeline currently produces, so this is a temporary catch-up rate.
POSTS_PER_RUN = 2

FACEBOOK_GRAPH_VERSION = "v21.0"
THREADS_API_VERSION = "v1.0"


def _frontmatter_field(text: str, field: str) -> str | None:
    match = re.search(rf'^{field}:\s*"?([^"\n]+?)"?\s*$', text, re.M)
    return match.group(1) if match else None


def load_published_articles() -> list[dict]:
    articles = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if _frontmatter_field(text, "reviewStatus") != "published":
            continue
        title = _frontmatter_field(text, "title")
        publish_date = _frontmatter_field(text, "publishDate")
        social_copy = _frontmatter_field(text, "socialCopy")
        if not title or not publish_date:
            continue
        articles.append(
            {
                "slug": path.stem,
                "title": title,
                # socialCopy is written as a hook for sharing (tension, a
                # concrete detail, sometimes a hashtag) -- falls back to
                # the article title only if a draft is missing the field.
                "socialCopy": social_copy or title,
                "publishDate": publish_date,
            }
        )
    return articles


def load_queue() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))


def save_queue(queue: list[dict]) -> None:
    QUEUE_PATH.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")


def sync_queue(queue: list[dict], articles: list[dict]) -> list[dict]:
    known_slugs = {entry["slug"] for entry in queue}
    new_entries = [
        {
            "slug": a["slug"],
            "title": a["title"],
            "socialCopy": a["socialCopy"],
            "publishDate": a["publishDate"],
            "postedFacebookAt": None,
            "postedThreadsAt": None,
        }
        for a in articles
        if a["slug"] not in known_slugs
    ]
    new_entries.sort(key=lambda e: e["publishDate"])
    return queue + new_entries


def post_to_facebook(message: str, link: str) -> None:
    page_id = os.environ["FACEBOOK_PAGE_ID"]
    token = os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"]
    url = f"https://graph.facebook.com/{FACEBOOK_GRAPH_VERSION}/{page_id}/feed"
    data = urllib.parse.urlencode({"message": message, "link": link, "access_token": token}).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request) as response:
        response.read()


def _wait_for_threads_container(creation_id: str, token: str) -> None:
    """Threads processes a media container asynchronously after creation --
    publishing before it reaches FINISHED fails with a "Media Not Found"
    error, even though the create call already returned an id. Poll status
    with a short backoff instead of publishing immediately."""
    status_url = (
        f"https://graph.threads.net/{THREADS_API_VERSION}/{creation_id}"
        f"?fields=status,error_message&access_token={token}"
    )
    for attempt in range(10):
        with urllib.request.urlopen(status_url) as response:
            status = json.loads(response.read())
        if status.get("status") == "FINISHED":
            return
        if status.get("status") == "ERROR":
            raise RuntimeError(f"Threads container failed to process: {status}")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Threads container {creation_id} did not finish processing in time")


def post_to_threads(text: str) -> None:
    user_id = os.environ["THREADS_USER_ID"]
    token = os.environ["THREADS_ACCESS_TOKEN"]
    base = f"https://graph.threads.net/{THREADS_API_VERSION}/{user_id}"

    create_data = urllib.parse.urlencode(
        {"media_type": "TEXT", "text": text, "access_token": token}
    ).encode()
    create_request = urllib.request.Request(f"{base}/threads", data=create_data, method="POST")
    with urllib.request.urlopen(create_request) as response:
        creation_id = json.loads(response.read())["id"]

    _wait_for_threads_container(creation_id, token)

    publish_data = urllib.parse.urlencode(
        {"creation_id": creation_id, "access_token": token}
    ).encode()
    publish_request = urllib.request.Request(f"{base}/threads_publish", data=publish_data, method="POST")
    with urllib.request.urlopen(publish_request) as response:
        response.read()


def main() -> None:
    queue = sync_queue(load_queue(), load_published_articles())
    pending = [e for e in queue if e["postedFacebookAt"] is None or e["postedThreadsAt"] is None]

    if not pending:
        print("Social queue empty -- nothing to post.")
        save_queue(queue)
        return

    to_post = pending[:POSTS_PER_RUN]
    now = datetime.now(timezone.utc).isoformat()

    for entry in to_post:
        link = f"{SITE_URL}/articles/{entry['slug']}/"
        message = f"{entry['socialCopy']}\n\n{link}"
        print(f"Posting: {entry['title']}")

        # Each platform is tracked independently so a failure on one
        # doesn't cause the next run to re-post to the other.
        if entry["postedFacebookAt"] is None:
            try:
                post_to_facebook(entry["socialCopy"], link)
                entry["postedFacebookAt"] = now
            except urllib.error.HTTPError as exc:
                print(f"  Facebook post failed: {exc.code} {exc.read().decode()}", file=sys.stderr)

        if entry["postedThreadsAt"] is None:
            try:
                post_to_threads(message)
                entry["postedThreadsAt"] = now
            except urllib.error.HTTPError as exc:
                print(f"  Threads post failed: {exc.code} {exc.read().decode()}", file=sys.stderr)
            except RuntimeError as exc:
                print(f"  Threads post failed: {exc}", file=sys.stderr)

    save_queue(queue)


if __name__ == "__main__":
    main()
