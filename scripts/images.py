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


# The lead image slot renders at 680px wide. A source photo much narrower
# than that gets stretched to fill it and looks visibly blurry -- found in
# testing with a 222x224px Commons photo that was otherwise a perfectly
# relevant, correctly-licensed match. SVGs are vector and scale cleanly
# regardless of their reported "native" size, so they're exempt.
MIN_IMAGE_WIDTH = 500
MIN_IMAGE_HEIGHT = 350


def _is_high_enough_resolution(title: str, info: dict) -> bool:
    if title.lower().endswith(".svg"):
        return True
    width = info.get("width") or 0
    height = info.get("height") or 0
    return width >= MIN_IMAGE_WIDTH and height >= MIN_IMAGE_HEIGHT


_QUERY_WORD_PATTERN = re.compile(r"[A-Za-z]+")


def _title_matches_query(title: str, query: str, strict: bool) -> bool:
    """Require the candidate's filename to actually contain part of the
    search query, not just something Commons' full-text search matched
    somewhere in the file's page. Without this, a resolution or license
    rejection on the one genuinely relevant result can fall through to an
    unrelated file that only coincidentally shares a word with the query
    (found in testing: "Renato Terry" fell through to a photo of a
    different, unrelated person once the real match was filtered out for
    being too small).

    `strict` requires ALL significant query words to appear in the title,
    not just one -- used for auto-extracted headline-fragment queries like
    "Terry Extends" (not a real name; "Extends" only got capitalized by
    Title Case styling), where a single-word match let through a
    completely different "Terry" once tried in testing. Lenient (any-word)
    matching stays for the deliberately-constructed queries (explicit
    subject, org name, continent/country) that testing already confirmed
    work well with it -- e.g. "Asian Team Chess Championship..." correctly
    matches an "{continent} chess tournament" query without containing
    every word of it."""
    significant_words = [w for w in _QUERY_WORD_PATTERN.findall(query) if len(w) >= 4]
    if not significant_words:
        return True
    title_lower = title.lower()
    if strict:
        return all(word.lower() in title_lower for word in significant_words)
    return any(word.lower() in title_lower for word in significant_words)


def _fetch_first_licensed_file(titles: list, query: str, strict: bool) -> dict | None:
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
            "iiprop": "url|extmetadata|timestamp|size",
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
        if not _title_matches_query(title, query, strict):
            continue
        page = pages_by_title.get(title)
        if not page:
            continue
        info_list = page.get("imageinfo")
        if not info_list:
            continue
        info = info_list[0]
        if not _is_high_enough_resolution(title, info):
            continue
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


def search_image(query: str, strict: bool = False) -> dict | None:
    """Search Commons for one query, return the first acceptably-licensed
    file, or None if nothing usable was found."""
    try:
        titles = _search_titles(query, limit=8)
        return _fetch_first_licensed_file(titles, query, strict)
    except Exception:  # noqa: BLE001 -- image sourcing is best-effort, never fatal
        return None


def build_query_cascade(item: dict, drafted_title: str, image_subjects: list | None = None) -> list:
    """Ordered list of (query, strict) tuples to try, most specific first,
    for a drafted article. `item` is the original candidate dict (from
    selected.json); `drafted_title` is the headline Claude wrote;
    `image_subjects` is the list of specific people/orgs/events Claude named
    as central to the piece, if any, most likely to have a good photo first
    -- e.g. a piece comparing a lesser-known player to Magnus Carlsen should
    try Carlsen too, not just fall to a generic org logo once the primary
    subject comes up empty. `strict` marks auto-extracted headline-fragment
    queries, which need a stronger title-match bar than the
    deliberately-constructed ones (see _title_matches_query)."""
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
                queries.append((tournament_name, False))
            if country:
                # Deliberately just "{country} chess", not "... chess
                # tournament": the 3-word version matched Commons' full-text
                # search against unrelated scanned documents (a 1967 school
                # yearbook that happened to mention both words somewhere in
                # its OCR'd text) rather than actual tournament photography.
                queries.append((f"{country} chess", False))

        name = item.get("continentName") or continent_name
        if name:
            queries.append((f"{name} chess tournament", False))
            queries.append((f"{name} chess", False))
    else:
        for subject in image_subjects or []:
            if subject:
                queries.append((subject, False))
        # No auto-extracted headline-fragment fallback here: tried and
        # dropped in testing. Even requiring every word to match, generic
        # capitalized fragments like "Thursday Record" (from a headline,
        # not a real name) matched Wikimedia files for entirely unrelated
        # subjects (a musician, in one case) -- too unreliable to keep at
        # any strictness. Claude's own imageSubject already covers this
        # case when a real subject exists; when it's empty or too specific
        # to find, falling straight to the org/continent/generic queries
        # below is safer than guessing from the headline text.
        source_name = item.get("sourceName", "")
        if source_name:
            queries.append((f"{source_name} logo", False))
        if continent_name:
            queries.append((f"{continent_name} chess", False))

    queries.append(("chess tournament", False))
    return queries


def pick_image_for_item(item: dict, drafted_title: str, image_subjects: list | None = None) -> dict | None:
    for query, strict in build_query_cascade(item, drafted_title, image_subjects):
        result = search_image(query, strict)
        if result:
            return result
    return None
