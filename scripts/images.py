"""Picks a real, legally-reusable photo for an article from Wikimedia
Commons -- no scraping of chess.com/FIDE's own (copyrighted) images, and no
Claude API calls involved; this is a plain HTTP search against Commons'
public API, filtered to genuinely free licenses.

Search is a cascade of increasingly generic queries (specific subject ->
organization -> continent/region -> nothing found), and the first query that
returns an acceptably-licensed file wins. Callers should treat a `None`
result as normal, not an error: most stories, especially smaller or
governance/money-angle ones, won't have a specific real photo available, and
fall back to the site's SVG placeholder thumbnail instead.
"""

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from continents import CONTINENT_NAMES

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "Chessori-ImagePicker/1.0 (https://chessori.com; contact: sabbe.the.technomage@gmail.com)"

# Only accept files under licenses that are unambiguously free to reuse
# (with attribution where the license requires it). Anything else -- most
# notably plain "All rights reserved" press photos some uploaders mislabel
# -- is skipped.
ACCEPTED_LICENSE_PREFIXES = ("cc0", "cc by", "public domain")

# Wikimedia Commons throttles unauthenticated/shared-IP traffic; keep a
# small gap between requests so a run of several articles doesn't trip it.
REQUEST_DELAY_SECONDS = 2.0

_last_request_time = 0.0


def _get(params: dict, retries: int = 3) -> dict:
    global _last_request_time
    import json

    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})

    for attempt in range(retries + 1):
        elapsed = time.monotonic() - _last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                _last_request_time = time.monotonic()
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            _last_request_time = time.monotonic()
            if exc.code == 429 and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 8.0
                time.sleep(delay)
                continue
            raise


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


_DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _photo_date(meta: dict) -> str:
    """Sortable date string for when the photo was actually taken, from
    Commons' DateTimeOriginal field -- deliberately NOT falling back to the
    file's upload timestamp, which reflects nothing about the photo's
    subject (an old document scanned and uploaded yesterday would otherwise
    sort as "recent"). A file with no DateTimeOriginal sorts as unknown/
    oldest rather than winning on a recency it can't actually claim."""
    raw = _strip_html(meta.get("DateTimeOriginal", {}).get("value", ""))
    match = _DATE_PATTERN.search(raw)
    return match.group(0) if match else "0000-00-00"


def _search_titles(query: str, limit: int = 5) -> list:
    data = _get(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srnamespace": 6,  # File namespace
            "srlimit": limit,
        }
    )
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def _license_ok(license_short_name: str) -> bool:
    name = (license_short_name or "").strip().lower()
    return any(name.startswith(prefix) for prefix in ACCEPTED_LICENSE_PREFIXES)


# Commons' full-text search matches words anywhere in a file's page (OCR'd
# text in a scanned document, a caption, a description), not just its
# title or subject -- a query can land on a completely unrelated PDF/book
# scan that happens to contain the search words somewhere. Real tournament
# photos and logos are never document-scan formats, so excluding those
# extensions outright is a cheap, general guard against that failure mode.
_REJECTED_EXTENSIONS = (".pdf", ".djvu", ".tiff", ".tif")


def _is_photo_file(title: str) -> bool:
    return not title.lower().endswith(_REJECTED_EXTENSIONS)


def _fetch_first_licensed_file(titles: list) -> dict | None:
    """Among the given candidate titles, return the most recently-taken
    acceptably-licensed file -- not just the first one Commons' text search
    happened to rank highest. Search relevance has no relationship to photo
    age, and an old photo of a young player (or a much-changed player) reads
    as wrong even when it's the "right" person and properly licensed."""
    if not titles:
        return None

    data = _get(
        {
            "action": "query",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|timestamp",
            "iiurlwidth": 1200,
        }
    )
    pages = data.get("query", {}).get("pages", {})
    # Preserve search-result order (dict iteration order from the API
    # response doesn't match titles order).
    pages_by_title = {p.get("title"): p for p in pages.values() if p.get("title")}

    candidates = []
    for title in titles:
        if not _is_photo_file(title):
            continue
        page = pages_by_title.get(title)
        if not page:
            continue
        info_list = page.get("imageinfo")
        if not info_list:
            continue
        info = info_list[0]
        meta = info.get("extmetadata", {})
        license_name = meta.get("LicenseShortName", {}).get("value", "")
        if not _license_ok(license_name):
            continue

        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Wikimedia Commons contributor"
        url = info.get("thumburl") or info.get("url")
        page_url = f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        date = _photo_date(meta)

        candidates.append(
            (
                date,
                {
                    "url": url,
                    "credit": f"{artist}, {license_name}, via Wikimedia Commons",
                    "sourceUrl": page_url,
                },
            )
        )

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def search_image(query: str) -> dict | None:
    """Search Commons for one query, return the first acceptably-licensed
    file, or None if nothing usable was found."""
    try:
        titles = _search_titles(query, limit=8)
        return _fetch_first_licensed_file(titles)
    except Exception:  # noqa: BLE001 -- image sourcing is best-effort, never fatal
        return None


# Matches runs of 2-3 consecutive Capitalized Words -- a cheap fallback for
# a full name/event phrase ("Magnus Carlsen", "Total Chess") when Claude's
# own `imageSubject` pick (see draft.py) is empty or turns up nothing.
# Deliberately does NOT fall back further to single capitalized words:
# tried in testing, a lone surname like "Carlsen" matched a Wikimedia file
# for a completely unrelated person (a 19th-century painter also named
# Carlsen) -- too high a risk of a flatly wrong photo for too little
# marginal recall.
_ENTITY_PATTERN = re.compile(r"\b[A-Z][a-zA-Z'-]*(?:\s+[A-Z][a-zA-Z'-]*){1,2}\b")

_ENTITY_STOPWORDS = {
    "the", "a", "an", "why", "who", "what", "how", "chess", "world", "new",
}


def _extract_entity_candidates(*texts: str) -> list:
    seen = set()
    candidates = []
    for text in texts:
        for match in _ENTITY_PATTERN.finditer(text or ""):
            phrase = match.group(0).strip()
            first_word = phrase.split()[0].lower()
            key = phrase.lower()
            if first_word in _ENTITY_STOPWORDS or key in seen:
                continue
            seen.add(key)
            candidates.append(phrase)
    return candidates


def build_query_cascade(item: dict, drafted_title: str, image_subject: str = "") -> list:
    """Ordered list of search queries to try, most specific first, for a
    drafted article. `item` is the original candidate dict (from
    selected.json); `drafted_title` is the headline Claude wrote;
    `image_subject` is the specific person/org/event Claude named in its
    drafting response, if any -- the most reliable candidate available."""
    queries = []
    continent_code = item.get("continentCode")
    continent_name = CONTINENT_NAMES.get(continent_code) if continent_code else None

    if item["kind"] in ("calendar-biggest", "calendar-comingup"):
        # The generic "{continent} chess tournament" query returns the same
        # small, static pool of Commons results every time, so every
        # calendar piece for a given continent ends up with the same photo
        # regardless of what month or country it's actually about. Trying
        # the month's actual top tournament (name, then country) first
        # gives the search something that genuinely differs month to
        # month, without ever forcing a worse match -- if nothing specific
        # is found, it still falls through to the same safe continent-level
        # queries as before.
        tournaments = item.get("tournamentData") or []
        if tournaments:
            top = tournaments[0]
            tournament_name = (top.get("name") or "").strip()
            country = (top.get("country") or "").strip()
            if tournament_name:
                queries.append(tournament_name)
            if country:
                # Deliberately just "{country} chess", not "... chess
                # tournament": the 3-word version matched Commons' full-text
                # search against unrelated scanned documents (a 1967 school
                # yearbook that happened to mention both words somewhere in
                # its OCR'd text) rather than actual tournament photography.
                queries.append(f"{country} chess")

        name = item.get("continentName") or continent_name
        if name:
            queries.append(f"{name} chess tournament")
            queries.append(f"{name} chess")
    else:
        if image_subject:
            queries.append(image_subject)
        queries.extend(_extract_entity_candidates(drafted_title, item["title"]))
        source_name = item.get("sourceName", "")
        if source_name:
            queries.append(f"{source_name} logo")
        if continent_name:
            queries.append(f"{continent_name} chess")

    queries.append("chess tournament")
    return queries


def pick_image_for_item(item: dict, drafted_title: str, image_subject: str = "") -> dict | None:
    for query in build_query_cascade(item, drafted_title, image_subject):
        result = search_image(query)
        if result:
            return result
    return None
