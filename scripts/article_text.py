"""Full article text for sources whose RSS feed only carries a short teaser.

Chess.com's feed description is ~250 characters cut off with "..." and
ChessBase's is the lede paragraph or two; drafting from either produced
pieces that wrote around gaps (caught live, 2026-09-29: "GM Oleksa..." and
"the excerpt we had" shipped in a draft). FIDE's feed already carries the
full text and needs nothing here.

Each site gets its own extractor because their markup differs. Every path
returns None -- never an empty string -- when it couldn't get real text, so
callers can tell "fetch failed" from "page has no text".
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

REQUEST_TIMEOUT = 20
USER_AGENT = "chess-herald-ingest/0.1 (+https://github.com/Sabbetus/chess-news-website)"
MAX_ARTICLE_TEXT_CHARS = 12000

_CHESSCOM_BODY_RE = re.compile(r'class="post-view-content">(.*?)</div>', re.DOTALL)

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "tr", "br"}
_SKIPPED_TAGS = {"script", "style", "iframe", "noscript"}
# ChessBase embeds product ads inside the story itself (a "cbadsmaindiv"
# block sits in the middle of a paragraph), so a plain "all <p> text" pull
# would ship sales copy for chess courses into the article source.
_AD_MARKERS = ("cbads", "prodbrief", "prodtitle", "cbdiagram", "productBox", "hidden-xs")


class _ChessBaseStoryParser(HTMLParser):
    """Text of ChessBase's <div id="full_story_id">, one entry per block
    element, skipping embedded ad subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip_depth = 0
        self.skipped_tag_depth = 0
        self.blocks: list[list[str]] = [[]]

    def _is_ad(self, attrs) -> bool:
        a = dict(attrs)
        marker_text = f"{a.get('id') or ''} {a.get('class') or ''}"
        return any(m in marker_text for m in _AD_MARKERS)

    def _break(self) -> None:
        if self.blocks[-1]:
            self.blocks.append([])

    def handle_starttag(self, tag, attrs) -> None:
        if self.depth == 0:
            if tag == "div" and dict(attrs).get("id") == "full_story_id":
                self.depth = 1
            return
        if tag in _SKIPPED_TAGS:
            self.skipped_tag_depth += 1
        elif tag == "div":
            self.depth += 1
            if self.skip_depth:
                self.skip_depth += 1
            elif self._is_ad(attrs):
                self.skip_depth = 1
        elif tag in _BLOCK_TAGS and not self.skip_depth:
            self._break()

    def handle_endtag(self, tag) -> None:
        if self.depth == 0:
            return
        if tag in _SKIPPED_TAGS:
            self.skipped_tag_depth = max(0, self.skipped_tag_depth - 1)
        elif tag == "div":
            if self.skip_depth:
                self.skip_depth -= 1
            self.depth -= 1
        elif tag in _BLOCK_TAGS and not self.skip_depth:
            self._break()

    def handle_data(self, data) -> None:
        if self.depth and not self.skip_depth and not self.skipped_tag_depth:
            self.blocks[-1].append(data)


def extract_chessbase_text(page_html: str) -> str | None:
    parser = _ChessBaseStoryParser()
    parser.feed(page_html)
    paragraphs = [re.sub(r"\s+", " ", " ".join(block)).strip() for block in parser.blocks]
    text = "\n\n".join(p for p in paragraphs if p)
    return text[:MAX_ARTICLE_TEXT_CHARS] if text else None


def extract_chesscom_text(page_html: str) -> str | None:
    match = _CHESSCOM_BODY_RE.search(page_html)
    if not match:
        return None
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", match.group(1), re.DOTALL)
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", "", p)).replace("\xa0", " ").strip() for p in paragraphs)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_ARTICLE_TEXT_CHARS] if text else None


def fetch_full_article_text(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if host.endswith("chessbase.com"):
        extract = extract_chessbase_text
    elif host.endswith("chess.com"):
        extract = extract_chesscom_text
    else:
        print(f"  No full-text extractor for {host}")
        return None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Could not fetch full text for {url}: {exc}")
        return None
    text = extract(resp.text)
    if text is None:
        print(f"  No article body found in {url}")
    return text
