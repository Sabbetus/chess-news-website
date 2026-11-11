"""Post published articles to Facebook and Threads, a few at a time.

Run on a schedule (see .github/workflows/social.yml). Each run:
  1. Scans src/content/articles/ for every reviewStatus: "published" article
     and adds any not already tracked to data/social-queue.json -- this both
     seeds the initial backlog and picks up newly merged articles
     automatically, with no separate "enqueue on merge" step needed.
  2. Posts the POSTS_PER_RUN still-unposted entries with the highest
     selectionScore to Facebook and Threads together (same article, same
     run) -- each article's socialCopy frontmatter (a hook written for
     sharing, distinct from its page title) plus the article link.
  3. Marks each as posted (with a timestamp) and writes the queue back.

Highest-score-first, with publishDate ascending as the tiebreak: the day's
lead story should hit social fastest rather than wait behind older,
lower-rated backlog entries. The tiebreak still drains ties oldest-first
so nothing gets stuck behind same-scored newer arrivals. At 24 runs/day
against ~3-5 articles/day, the backlog empties same-day in practice, so
this doesn't starve lower-scored older entries the way it would if supply
regularly outpaced posting slots.
"""
from __future__ import annotations
from social_text import delink, fit_for_x  # noqa: E402

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
SITE_URL = "https://chessherald.com"

# One per run: at 12 runs/day this still comfortably outpaces the
# ~2-3 articles/day the pipeline produces, while keeping each run's post
# count low enough that a newly published article doesn't have to wait
# behind a backlog before going out. The initial catch-up backlog (this
# was 2/run while it drained) is gone as of 2026-09-16.
POSTS_PER_RUN = 1

FACEBOOK_GRAPH_VERSION = "v21.0"
THREADS_API_VERSION = "v1.0"


def _frontmatter_field(text: str, field: str) -> str | None:
    """Values are written with internal quotes backslash-escaped (see
    draft.py/weekly_recap.py's frontmatter writer), e.g.
    socialCopy: "a \"windmill\" tactic". A naive [^"\n]+ character class
    excludes literal " entirely, so it can't match past the first escaped
    quote and the whole regex fails on any such line -- caught live:
    three articles with a quoted word in their socialCopy silently had
    their title posted to social media instead, since the caller falls
    back to the title when this returns None. Match a proper quoted
    string (an escaped-char alternation, same idea as parsing a JSON
    string) first, then fall back to a bare unquoted value for fields
    like selectionScore that aren't quoted at all."""
    match = re.search(rf'^{field}:\s*"((?:[^"\\]|\\.)*)"\s*$', text, re.M)
    if match:
        return match.group(1).replace('\\"', '"')
    match = re.search(rf'^{field}:\s*([^"\n]+?)\s*$', text, re.M)
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
        selection_score = _frontmatter_field(text, "selectionScore")
        if not title or not publish_date:
            continue
        articles.append(
            {
                "slug": path.stem,
                "title": title,
                # socialCopy is written as a hook for sharing (tension, a
                # concrete detail, sometimes a hashtag) -- falls back to
                # the article title only if a draft is missing the field.
                "socialCopy": fit_for_x(delink(social_copy or title))[0],
                "publishDate": publish_date,
                "selectionScore": int(selection_score) if selection_score else 0,
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
            "selectionScore": a["selectionScore"],
            "postedFacebookAt": None,
            "postedThreadsAt": None,
        }
        for a in articles
        if a["slug"] not in known_slugs
    ]
    new_entries.sort(key=lambda e: e["publishDate"])
    return queue + new_entries


def refresh_pending(queue: list[dict], articles: list[dict]) -> list[dict]:
    """Pending entries follow the article as it is now, not as it was
    queued (caught 2026-11-07: an Esports World Cup piece removed from the
    site was still posted hours later, and the Bavarian post went out with
    its old "half a point back" copy and old score). An entry whose article
    is gone or unpublished is withdrawn and never posted; its copy, title
    and score are re-read from the article on every run."""
    current = {a["slug"]: a for a in articles}
    for entry in queue:
        if entry.get("withdrawn") or (entry["postedFacebookAt"] and entry["postedThreadsAt"]):
            continue
        article = current.get(entry["slug"])
        if article is None:
            entry["withdrawn"] = True
            print(f"Withdrawn (no longer published): {entry['title']}")
            continue
        for key in ("title", "socialCopy", "selectionScore"):
            entry[key] = article[key]
    return queue


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


def _next_for(queue: list[dict], key: str) -> list[dict]:
    """The POSTS_PER_RUN highest-scoring entries still missing `key`. Each
    platform has its own line (caught 2026-11-10: Facebook's token expired,
    the top entry kept failing on Facebook, and because both platforms took
    the same entry, nothing else went out on Threads either for a day)."""
    waiting = [e for e in queue if not e.get("withdrawn") and e.get(key) is None]
    waiting.sort(key=lambda e: (-e.get("selectionScore", 0), e["publishDate"]))
    return waiting[:POSTS_PER_RUN]


def main() -> None:
    articles = load_published_articles()
    queue = refresh_pending(sync_queue(load_queue(), articles), articles)
    facebook = _next_for(queue, "postedFacebookAt")
    threads = _next_for(queue, "postedThreadsAt")

    if not facebook and not threads:
        print("Social queue empty -- nothing to post.")
        save_queue(queue)
        return

    now = datetime.now(timezone.utc).isoformat()
    failures = 0
    for entry in facebook:
        link = f"{SITE_URL}/articles/{entry['slug']}/"
        print(f"Posting to Facebook: {entry['title']}")
        try:
            post_to_facebook(entry["socialCopy"], link)
            entry["postedFacebookAt"] = now
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            # An annotation shows on the run page, so an expired token is
            # visible without reading the log (the run itself still succeeds,
            # so the queue is committed).
            print(f"::error title=Facebook post failed::{exc.code} {body[:300]}")
            print(f"  Facebook post failed: {exc.code} {body}", file=sys.stderr)
            failures += 1

    for entry in threads:
        link = f"{SITE_URL}/articles/{entry['slug']}/"
        print(f"Posting to Threads: {entry['title']}")
        try:
            post_to_threads(f"{entry['socialCopy']}\n\n{link}")
            entry["postedThreadsAt"] = now
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            print(f"::error title=Threads post failed::{exc.code} {body[:300]}")
            print(f"  Threads post failed: {exc.code} {body}", file=sys.stderr)
            failures += 1
        except RuntimeError as exc:
            print(f"::error title=Threads post failed::{exc}")
            print(f"  Threads post failed: {exc}", file=sys.stderr)
            failures += 1

    save_queue(queue)
    # The workflow fails the run at its very end when this is set, after
    # the queue is committed (see .github/workflows/social.yml).
    if failures and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("failed=true\n")


if __name__ == "__main__":
    main()
