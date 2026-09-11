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
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from continents import CONTINENT_NAMES

ROOT = Path(__file__).parent.parent
# Co-located with the article content, not public/ -- this is what lets
# each article's frontmatter reference its master photo as a relative path
# ("./_images/<slug>.webp") through Astro's content-collection image()
# schema helper (see src/content/config.ts), which resolves it into a real
# typed image asset. That's what gives every on-site display size AND the
# social-card crop (see BaseLayout/article page) to Astro's own build-time
# Sharp pipeline, from this one committed file -- nothing else is generated
# or stored.
IMAGES_DIR = ROOT / "src" / "content" / "articles" / "_images"

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
    # Commons' extmetadata fields (Artist in particular) commonly carry a
    # visible value plus a hidden duplicate for machine parsing, e.g.
    # 'Unknown author<span style="display: none;">Unknown author</span>' --
    # stripping tags alone concatenates both into "Unknown authorUnknown
    # author". Drop the hidden span's content before stripping the rest.
    text = re.sub(r'<span style="display:\s*none;?">.*?</span>', "", text or "", flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


_BOLD_TAG = re.compile(r"<b>(.*?)</b>", re.DOTALL)


def _extract_artist_name(raw: str) -> str:
    """Some Commons uploaders use a full "photographer credit" template for
    the Artist field instead of a plain name -- a table/paragraph with
    instructional text repeated in multiple languages, e.g. "This photo was
    taken by <b>Name</b>.<br>Foto <b>Name</b> ... çəkilib.<br>Mention the
    author's name ...: <b>Name</b>". `_strip_html` alone turns that into one
    long run-on sentence with the name repeated 2-3 times and translator/
    instruction text mixed in -- a real credit shown on real articles this
    way (caught live: an Azerbaijani/English credit-line template).

    The name is reliably wrapped in <b> in these templates, so prefer the
    first bolded span when the field looks like this template rather than a
    plain name: either multiple identical <b> spans, or a stripped length
    long enough that it's prose, not a name. A plain name (with or without
    HTML) is always shorter than that and passes through unchanged."""
    bold_matches = _BOLD_TAG.findall(raw or "")
    stripped = _strip_html(raw)
    if bold_matches and (len(bold_matches) > 1 or len(stripped) > 60):
        return _strip_html(bold_matches[0]) or stripped
    return stripped


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


_FILENAME_WORD_PATTERN = re.compile(r"[A-Za-z]+")


def _filename_words(title: str) -> set[str]:
    """Commons file titles are underscore-separated ("Magnus_Carlsen_sig.svg"),
    not space-separated -- a raw \\b-anchored regex never fires around an
    underscore (it's a \\w character, same as the letters on either side of
    it), so a pattern like r"\\bsig\\b" silently never matches real
    filenames despite looking correct. Splitting into alpha-only tokens
    first, then matching against that set, sidesteps the problem
    entirely."""
    return {w.lower() for w in _FILENAME_WORD_PATTERN.findall(title)}


# A generic country/continent query can genuinely satisfy a lenient
# "{country} chess" match with a postage stamp, banknote, or coin
# depicting a chess motif (found real: "2002 Chess Olympiad Romanian
# stamp" for "Romania chess") -- these aren't wrong matches, they really
# do have both words, but they're philatelic/numismatic ephemera, not a
# photo of anyone or anything happening, and don't belong here regardless
# of how well they match.
_EPHEMERA_WORDS = {"stamp", "stamps", "banknote", "banknotes", "postcard", "postcards", "coin", "coins"}


def _is_ephemera(title: str) -> bool:
    return bool(_filename_words(title) & _EPHEMERA_WORDS)


# A person-name query can also turn up that person's signature/autograph as
# a standalone Commons file (found real: "Magnus_Carlsen_sig.svg") -- a
# vector squiggle, not a photo of them, but one that otherwise sails
# through every other filter (real file, correctly licensed, SVGs exempt
# from the resolution check since they're vector).
_SIGNATURE_WORDS = {"sig", "signature", "signatures", "autograph", "autographs"}


def _is_signature_file(title: str) -> bool:
    return bool(_filename_words(title) & _SIGNATURE_WORDS)


# A person's name is also, not infrequently, a street, square, or building
# named after them -- "Rue Vladimir Kramnik - Asnieres-sur-Seine" matches a
# "Vladimir Kramnik" query under every other filter (real photo file,
# correctly licensed, high enough resolution) while being a street sign,
# not a picture of the person. These filename prefixes are how Commons
# titles that kind of file across the languages sourced articles are
# likely to come from.
_PLACE_NAME_PREFIXES = (
    "rue ", "avenue ", "boulevard ", "place ", "square ", "plaza ", "street ",
    "via ", "calle ", "strasse ", "straße ", "platz ",
)


def _is_place_named_after_subject(title: str) -> bool:
    # Titles are "File:<name>.ext" once the namespace prefix is stripped by
    # the caller -- check the bare name, case-insensitively.
    name = title.split(":", 1)[-1].lower()
    return name.startswith(_PLACE_NAME_PREFIXES)


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


def _fetch_first_licensed_file(
    titles: list, query: str, strict: bool, exclude_source_urls: set | None = None
) -> dict | None:
    """Among the given candidate titles, return the most recently-taken
    acceptably-licensed file -- not just the first one Commons' text search
    happened to rank highest. Search relevance has no relationship to photo
    age, and an old photo of a young player (or a much-changed player) reads
    as wrong even when it's the "right" person and properly licensed.

    `exclude_source_urls` skips files already used as another article's
    image -- the query cascade is deterministic, so two articles that both
    name the same central subject (e.g. two money-angle pieces that both
    cite Magnus Carlsen) would otherwise pick the identical top-ranked
    photo of him."""
    if not titles:
        return None

    # Normalize once: articles written at different times (or by different
    # code versions) can have their image sourceUrl percent-encoded
    # differently -- e.g. "File:Name.jpg" vs "File%3AName.jpg", the exact
    # same Commons page as two different strings. Comparing raw strings let
    # a photo already used in another recent article slip past the
    # exclusion check and get picked again (caught live: the same Carlsen
    # photo on two GCL articles two days apart, because the older article's
    # stored URL used a raw colon that no longer matched what this function
    # constructs). Unquoting both sides makes the comparison encoding-proof.
    normalized_excludes = (
        {urllib.parse.unquote(u) for u in exclude_source_urls} if exclude_source_urls else set()
    )

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
        if _is_place_named_after_subject(title):
            continue
        if _is_ephemera(title):
            continue
        if _is_signature_file(title):
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

        page_url = f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        if urllib.parse.unquote(page_url) in normalized_excludes:
            continue

        artist = _extract_artist_name(meta.get("Artist", {}).get("value", "")) or "Wikimedia Commons contributor"
        url = info.get("thumburl") or info.get("url")
        date = _photo_date(meta)

        # Every on-site slot this image can land in is a wide landscape box
        # (1.91:1 lead, 16:9 card) rendered with object-fit: cover -- a
        # portrait-oriented source gets scaled up until its width fills the
        # box, then has most of its height cropped away. A tight face-closeup
        # portrait (the common case for headshot-style Commons photos) loses
        # so much of that height that only eyes/nose/mouth survive the crop,
        # blown up far larger than intended (found in testing: a 869x1303
        # Carlsen closeup read as a giant, awkwardly-cropped face on-site).
        # A well-composed portrait with headroom and shoulders survives the
        # same crop fine, and there's no metadata that distinguishes the two
        # -- but ANY portrait is strictly more likely to crop badly than a
        # landscape or square photo of the same subject, so treat orientation
        # as a soft preference (not a hard filter -- a portrait is still
        # better than no image) rather than trying to guess crop tightness.
        width = info.get("width") or 0
        height = info.get("height") or 1
        is_portrait = width < height

        candidates.append(
            (
                is_portrait,
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

    # Two stable passes, least-significant key first: sort by recency, then
    # re-sort by orientation -- the recency order survives within each
    # orientation tier, so this is "most recent landscape/square photo, or
    # if none exists, most recent portrait photo" rather than a pure date
    # sort or a pure orientation sort.
    candidates.sort(key=lambda c: c[1], reverse=True)
    candidates.sort(key=lambda c: c[0])
    return candidates[0][2]


def search_image(query: str, strict: bool = False, exclude_source_urls: set | None = None) -> dict | None:
    """Search Commons for one query, return the first acceptably-licensed
    file, or None if nothing usable was found."""
    try:
        titles = _search_titles(query, limit=8)
        return _fetch_first_licensed_file(titles, query, strict, exclude_source_urls)
    except Exception:  # noqa: BLE001 -- image sourcing is best-effort, never fatal
        return None


def build_query_cascade(item: dict, drafted_title: str, image_subjects: list | None = None) -> list:
    """Ordered list of (query, strict) tuples to try, most specific first,
    for a drafted article. `item` is the original candidate dict (from
    selected.json); `drafted_title` is the headline Claude wrote;
    `image_subjects` is the list of specific people/orgs/events Claude named,
    ordered by centrality to the piece (the actual subject first, a more
    photogenic secondary mention only after) -- the first one that finds a
    usable photo wins, so this order determines whose photo the article
    gets, not just which query happens to run first. `strict` marks auto-extracted headline-fragment
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
            # Try more than just the single top tournament -- when the #1
            # entry has no real photo on Commons (common; most of these are
            # small regional opens), falling straight to a generic
            # continent-level query produces the same recycled, often
            # barely-relevant image every time (a 2002 Olympiad postage
            # stamp standing in for an unrelated Craiova rapid open, in one
            # case). Every additional named tournament tried here is a real
            # chance at a genuinely specific photo before giving up on
            # specificity altogether.
            for candidate in tournaments[:5]:
                name = (candidate.get("name") or "").strip()
                if name:
                    # Strict: a specific multi-word tournament name matching on
                    # just one generic word is a real failure mode, not a
                    # hypothetical -- "2026 Perth International Open" lenient-
                    # matched a Hungry Jack's ad photo titled "...Perth
                    # International Airport..." purely off "Perth" and
                    # "International". A genuine photo of this exact tournament
                    # would still match every word easily; requiring that is a
                    # much safer bar than "any one word in common".
                    queries.append((name, True))

            country = (tournaments[0].get("country") or "").strip()
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


def pick_image_for_item(
    item: dict, drafted_title: str, image_subjects: list | None = None, exclude_source_urls: set | None = None
) -> dict | None:
    for query, strict in build_query_cascade(item, drafted_title, image_subjects):
        result = search_image(query, strict, exclude_source_urls)
        if result:
            return result
    return None


# The only local master ever stored -- every on-site display size (lead,
# card) and the social-card crop are derived from this one file by Astro's
# build-time image pipeline (see ArticleThumb.astro and the article page's
# og:image generation), not generated or committed here. 1280px covers the
# widest on-site use (960px lead slot) with real headroom for high-DPI
# screens without shipping Wikimedia's often much larger originals.
MASTER_MAX_WIDTH = 1280
MASTER_QUALITY = 82


def _fetch_bytes(url: str, retries: int) -> bytes:
    global _last_request_time
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(retries + 1):
        elapsed = time.monotonic() - _last_request_time
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                _last_request_time = time.monotonic()
                return response.read()
        except urllib.error.HTTPError as exc:
            _last_request_time = time.monotonic()
            if exc.code == 429 and attempt < retries:
                retry_after = exc.headers.get("Retry-After")
                # Capped, not honored outright: a shared-IP throttle can
                # advertise a Retry-After in the hundreds of seconds (seen
                # in testing: 600), and waiting that out here would stall
                # the whole batch on one photo. _download_bytes has a
                # fallback endpoint for exactly this case -- better to fail
                # this attempt quickly and let it try that than block.
                delay = min(float(retry_after), 15.0) if retry_after and retry_after.isdigit() else 8.0
                time.sleep(delay)
                continue
            raise


_THUMB_FILENAME = re.compile(r"/(?:\d+px-)?([^/]+)$")


def _download_bytes(url: str, retries: int = 3) -> bytes:
    """Fetch raw bytes from Commons, sharing the same rate-limit pacing and
    429/Retry-After handling as `_get` -- this hits the same Wikimedia
    infrastructure as the search API, just for a file instead of JSON.

    Falls back to commons.wikimedia.org/wiki/Special:FilePath/<filename> --
    a different endpoint that in practice sits on a separate rate-limit
    pool from direct upload.wikimedia.org fetches -- if the direct URL is
    still failing once retries are exhausted, rather than losing the image
    outright over what's often a transient, endpoint-specific throttle."""
    try:
        return _fetch_bytes(url, retries=1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        match = _THUMB_FILENAME.search(urllib.parse.urlparse(url).path)
        if not match:
            raise
        # match.group(1) comes from urlparse().path, which does NOT decode
        # percent-escapes -- it's already URL-encoded (e.g. "...%28cropped
        # %29.jpg"). quote()-ing it again without unquoting first turns
        # "%28" into "%2528", a filename that doesn't exist on Commons and
        # 404s outright (found live: a real, existing file failed to
        # localize this way). Round-trip through unquote first so the
        # re-encoding starts from the real filename, not its escaped form.
        filename = urllib.parse.quote(urllib.parse.unquote(match.group(1)))
        fallback_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width={MASTER_MAX_WIDTH}"
        return _fetch_bytes(fallback_url, retries)


_COMMONS_FILE_TITLE = re.compile(r"/([^/]+)$")


def _commons_file_stem(source_url: str) -> str:
    """A stable, filesystem-safe identifier for a Commons file, derived
    from its wiki page URL ("File:Name.jpg") rather than the article
    slug -- used as the stored filename so the same photo picked for two
    different articles (a recurring figure like Carlsen, easily picked
    again months apart, once the reuse cooldown has passed) resolves to
    one shared file on disk instead of a duplicate copy per article, and
    skips the download and re-encode entirely on the second pick. Two
    distinct Commons files can never collide here: this is the same
    "File:Title.ext" name Commons itself already guarantees is unique."""
    match = _COMMONS_FILE_TITLE.search(urllib.parse.unquote(urllib.parse.urlparse(source_url).path))
    title = re.sub(r"^File:", "", match.group(1)) if match else source_url
    title = re.sub(r"\.[A-Za-z0-9]+$", "", title)  # drop the original extension; we control the stored one
    return re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_") or "image"


def localize_image(image: dict) -> dict | None:
    """Download the Commons photo `pick_image_for_item` chose, once, and
    store a single compressed master locally -- see IMAGES_DIR above for
    why co-located with the content and why just one file. Returns a
    frontmatter-ready dict (relative `src` path in place of the hotlinked
    `url`, same `credit`/`sourceUrl`), or None if the download/decode fails.

    Reuses an already-stored file for the same Commons source without any
    network call at all when one exists (see _commons_file_stem) -- pure
    storage/bandwidth win on top of the localization itself, and it only
    grows as the same well-known players and organizations recur.

    Best-effort like the search step itself (see module docstring): a
    transient fetch failure here is a missing image, not a failed draft --
    matching how `search_image` already treats "nothing found" as normal
    rather than an error."""
    is_svg = urllib.parse.urlparse(image["url"]).path.lower().endswith(".svg")
    stem = _commons_file_stem(image["sourceUrl"])
    filename = f"{stem}.svg" if is_svg else f"{stem}.webp"
    if (IMAGES_DIR / filename).exists():
        return {
            "src": f"./_images/{filename}",
            "credit": image["credit"],
            "sourceUrl": image["sourceUrl"],
        }
    try:
        raw = _download_bytes(image["url"])
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if is_svg:
            # Pillow can't decode SVG at all (it's vector, not raster) --
            # every organization-logo pick from build_query_cascade's
            # "{source} logo" fallback query is one of these. Store the
            # vector file as-is; Astro's own image() pipeline (Sharp) can
            # rasterize an SVG source into whatever raster crop/size a
            # given slot needs, same as it does for real photos.
            (IMAGES_DIR / filename).write_bytes(raw)
        else:
            photo = Image.open(io.BytesIO(raw)).convert("RGB")
            if photo.width > MASTER_MAX_WIDTH:
                new_height = round(photo.height * MASTER_MAX_WIDTH / photo.width)
                photo = photo.resize((MASTER_MAX_WIDTH, new_height), Image.LANCZOS)
            photo.save(IMAGES_DIR / filename, "WEBP", quality=MASTER_QUALITY)
    except Exception:  # noqa: BLE001 -- image sourcing is best-effort, never fatal
        return None
    return {
        "src": f"./_images/{filename}",
        "credit": image["credit"],
        "sourceUrl": image["sourceUrl"],
    }
