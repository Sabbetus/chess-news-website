"""Static tweet quotes for articles: finds the posts on X that a story's own
source page(s) embed, and stores each as plain text in the article's
frontmatter (tweetEmbeds) so the site can render it as a quote.

The site never loads anything from X. The text comes from X's public oEmbed
endpoint at draft time and is stored in the repo, so a reader's browser makes
no request to X unless they click through to the original post, the build
can't fail because X is down, and a reviewer sees exactly what will be
published in the PR (deleting an entry from the frontmatter removes it).

Which posts: whatever the source page already embedded, minus accounts that
are institutions rather than people (federations, event and outlet accounts
-- see ORG_HANDLES). That keeps the personalities and commentators a story
quotes, without keeping a list of personality handles up to date by hand;
anything odd that slips through is a one-line delete in the PR. Best-effort
throughout: any failure means no quotes, never a failed draft.
"""

import html
import re
import sys
from datetime import datetime

import requests

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
OEMBED_URL = "https://publish.twitter.com/oembed"
REQUEST_TIMEOUT = 20

MAX_SOURCE_PAGES = 3
MAX_TWEETS_PER_ARTICLE = 3
MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 500

# Institutional / outlet accounts (lowercase). Deliberately not exhaustive: a
# missed one shows up in the PR and gets deleted there.
ORG_HANDLES = {
    "fide_chess", "fide", "chess24com", "chess24", "chesscom", "chess", "lichess",
    "uschess", "englishchess", "ecu_chess", "chessscotland", "saintlouischess",
    "grandchesstour", "worldchess", "norwaychess", "tatasteelchess", "totalchess",
    "gclchess", "globalchessleague", "chessbase", "chessbase_in", "chessbaseindia",
    "chessolympiad", "chessolympiad2026", "aicf_chess", "chessdom", "chessbrahs",
    "takechesstake", "chessable", "chessdotcom",
}

# Regional and sub-brand accounts ("chesscom_in", "fide_chess") -- caught
# live: Chess.com's India account slipped through an exact-match list.
ORG_HANDLE_PREFIXES = ("chesscom", "chess24", "fide_", "fide")


def is_org_handle(handle: str) -> bool:
    lowered = handle.lower()
    return lowered in ORG_HANDLES or lowered.startswith(ORG_HANDLE_PREFIXES)


_TWEET_BLOCKQUOTE_RE = re.compile(r'<blockquote[^>]*class="[^"]*twitter-tweet[^"]*"[^>]*>.*?</blockquote>', re.DOTALL)
_STATUS_LINK_RE = re.compile(r'https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)')
_MEDIA_OR_SHORT_LINK_RE = re.compile(r"(?:pic\.(?:twitter|x)\.com|https?://t\.co)/\S*")


def find_embedded_tweets(page_html: str) -> list[tuple[str, str]]:
    """(handle, status_id) for each tweet the page embeds, in page order.
    The last status link inside an embed block is the tweet's own permalink
    (earlier ones are quoted or replied-to posts)."""
    found, seen = [], set()
    for block in _TWEET_BLOCKQUOTE_RE.findall(page_html):
        links = _STATUS_LINK_RE.findall(block)
        if not links:
            continue
        handle, status_id = links[-1]
        if status_id in seen:
            continue
        seen.add(status_id)
        found.append((handle, status_id))
    return found


def clean_tweet_text(paragraph_html: str) -> str:
    """Plain, single-line text safe to write into a double-quoted YAML string
    (draft.py's frontmatter writer escapes quotes but not backslashes or
    newlines). Drops t.co and pic.twitter.com tokens, which are meaningless
    without X."""
    text = re.sub(r"<br\s*/?>", " ", paragraph_html)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = _MEDIA_OR_SHORT_LINK_RE.sub("", text)
    text = text.replace("\\", "/").replace(" ", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'"([^"]*)"', "“\\1”", text)
    return text.replace('"', "”")


def _parse_date(text: str) -> str:
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def fetch_tweet_quote(handle: str, status_id: str) -> dict | None:
    try:
        resp = requests.get(
            OEMBED_URL,
            params={"url": f"https://x.com/{handle}/status/{status_id}", "omit_script": "true", "dnt": "true"},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    embed_html = data.get("html", "")
    paragraph = re.search(r"<p[^>]*>(.*?)</p>", embed_html, re.DOTALL)
    if not paragraph:
        return None
    text = clean_tweet_text(paragraph.group(1))
    if len(text) < MIN_TEXT_CHARS:
        return None
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 1].rstrip() + "…"

    author_handle = (data.get("author_url") or "").rstrip("/").rsplit("/", 1)[-1] or handle
    date_link = re.findall(r"<a [^>]*>([^<]+)</a>\s*</blockquote>", embed_html)
    return {
        "url": f"https://x.com/{author_handle}/status/{status_id}",
        "author": clean_tweet_text(data.get("author_name") or author_handle),
        "handle": author_handle,
        "text": text,
        "date": _parse_date(date_link[-1]) if date_link else "",
    }


def tweet_quotes_for_item(item: dict) -> list[dict]:
    """Quotes for a selected item, from its primary and additional source
    pages. Never raises."""
    urls = [item["sourceUrl"]] + [extra["sourceUrl"] for extra in item.get("additionalSources", [])]
    quotes, seen = [], set()
    for url in urls[:MAX_SOURCE_PAGES]:
        try:
            page = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            if page.status_code != 200:
                continue
            candidates = find_embedded_tweets(page.text)
        except requests.RequestException:
            continue
        for handle, status_id in candidates:
            if is_org_handle(handle) or status_id in seen:
                continue
            seen.add(status_id)
            quote = fetch_tweet_quote(handle, status_id)
            if quote is None or is_org_handle(quote["handle"]):
                continue
            quotes.append(quote)
            if len(quotes) >= MAX_TWEETS_PER_ARTICLE:
                return quotes
    return quotes


if __name__ == "__main__":
    for source_url in sys.argv[1:]:
        for q in tweet_quotes_for_item({"sourceUrl": source_url}):
            print(q)
