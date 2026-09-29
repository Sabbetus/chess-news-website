"""Research helper for the /players/ reference pages (not part of the daily
pipeline). For each FIDE top-100 rank given, collects the facts a player page
needs from Wikipedia, and the infobox photo from Commons, into a JSON file a
writer drafts the page from.

Every Wikipedia page is checked against FIDE: its infobox FIDE_id must equal
the player's FIDE ID, or the page is rejected (names collide; FIDE IDs don't).
Photos go through images.py's licence check and localize_image, so they land
in the same committed master store as article photos.

    python scripts/player_research.py 1-20 research.jsonl [--women]
"""

import json
import re
import sys
import time
import urllib.parse

import requests

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import images  # noqa: E402

ROOT = images.IMAGES_DIR.parent.parent.parent.parent
TOP100 = json.loads((ROOT / "data" / "fide-top100.json").read_text())
WIKI_RAW = "https://en.wikipedia.org/w/index.php"
WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": images.USER_AGENT}


def wiki_get(url: str, params: dict) -> requests.Response:
    for attempt in range(4):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if resp.status_code != 429:
            time.sleep(1.0)
            return resp
        time.sleep(10 * (attempt + 1))
    return resp


def find_page(name: str, fide_id: str) -> tuple[str, str] | None:
    """(title, wikitext) of the page whose infobox carries this FIDE ID."""
    candidates = [name]
    found = wiki_get(WIKI_API, {"action": "query", "list": "search", "srsearch": f"{name} chess", "srlimit": 5, "format": "json"})
    if found.ok:
        candidates += [hit["title"] for hit in found.json().get("query", {}).get("search", [])]
    seen = set()
    for title in candidates:
        if title in seen:
            continue
        seen.add(title)
        resp = wiki_get(WIKI_RAW, {"title": title, "action": "raw", "redirect": "true"})
        text = resp.text if resp.ok else ""
        redirect = re.match(r"#REDIRECT\s*\[\[([^\]#|]+)", text, re.I)
        if redirect:
            title = redirect.group(1)
            resp = wiki_get(WIKI_RAW, {"title": title, "action": "raw"})
            text = resp.text if resp.ok else ""
        if re.search(r"\|\s*FIDE_?id\s*=\s*" + fide_id + r"\b", text, re.I):
            return title, text
    return None


def field(text: str, key: str) -> str:
    m = re.search(r"^\s*\|\s*" + key + r"\s*=\s*(.*)$", text, re.M | re.I)
    return clean(m.group(1)) if m else ""


def clean(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"\{\{(?:birth date and age|birth date)\|(\d{4})\|(\d{1,2})\|(\d{1,2})[^}]*\}\}", r"\1-\2-\3", s, flags=re.I)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{(?:efn|refn|sfn|cn|citation needed)[^{}]*\}\}", "", s, flags=re.I)
    s = re.sub(r"'''?", "", s)
    return re.sub(r"\s+", " ", s).strip()


def recent_career(text: str, limit: int = 6000) -> str:
    """The end of the article's career narrative, where the latest results
    are: Wikipedia's lead summary lags behind (caught live: Praggnanandhaa's
    lead had nothing on his 2026 Norway Chess and Grand Chess Tour wins)."""
    body = re.sub(r"\{\{[^{}]*\}\}", "", re.sub(r"\{\{[^{}]*\}\}", "", text))
    body = re.split(r"\n==\s*(?:Playing style|Personal life|Notable games|See also|References|Notes|External links|Awards|Books)", body)[0]
    parts = body.split("\n==", 1)
    career = clean(re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", parts[1])) if len(parts) > 1 else ""
    return career[-limit:]


def lead(text: str) -> str:
    body = re.sub(r"\{\{[^{}]*\}\}", "", re.sub(r"\{\{[^{}]*\}\}", "", text))
    body = body.split("\n==", 1)[0]
    return clean(body)[:2500]


# Game shots, group shots and selfies: a profile needs the player on their own.
_NOT_SOLO = re.compile(r"\b(vs|v|versus|against|derby|selfie|team|with|playing|plays|meets)\b", re.I)
MIN_PHOTO_WIDTH = 600
# A name match alone isn't enough (caught live: "Wei Yi" matched a bronze
# spoon and a hotpot restaurant). The file must be about chess.
_CHESS_CONTEXT = re.compile(r"chess|olympiad|tata steel|candidates|grand chess|grand swiss|world cup|masters|blitz|rapid|fide|sinquefield|norway|grenke|superbet|championship|tournament", re.I)


def photo_candidates(name: str, infobox_file: str) -> list[tuple]:
    """The newest usable solo photo of the player on Commons -- the same
    "most recent photo wins" rule the article picker uses (images.py), over a
    wider candidate set: searches for the name alone and with this year and
    last year (Commons' search ranks by text relevance, so a plain name search
    alone misses most recent event photos), plus the Wikipedia infobox photo.
    Game shots naming an opponent ("X vs Y") are skipped: a profile needs the
    player on their own."""
    year = time.gmtime().tm_year
    titles = []
    for query in (f"{name} {year}", f"{name} {year - 1}", name):
        for title in images._search_titles(query, limit=12):
            if title not in titles:
                titles.append(title)
    if infobox_file:
        titles.append("File:" + infobox_file.replace("File:", "").strip())
    candidates = []
    for i in range(0, len(titles), 20):
        data = images._get({"action": "query", "titles": "|".join(titles[i:i + 20]), "prop": "imageinfo",
                            "iiprop": "url|extmetadata|size", "iiurlwidth": 1600})
        for page in data.get("query", {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            meta = info.get("extmetadata", {})
            title = page["title"]
            description = images._strip_html(meta.get("ImageDescription", {}).get("value", ""))
            licence = meta.get("LicenseShortName", {}).get("value", "")
            if (
                not images._license_ok(licence)
                or not images._is_photo_file(title)
                or not all(part.lower() in (title + " " + description).lower() for part in name.split() if len(part) > 1)
                or _NOT_SOLO.search(title) or _NOT_SOLO.search(description)
                or not _CHESS_CONTEXT.search(title + " " + description)
                or info.get("width", 0) < MIN_PHOTO_WIDTH
            ):
                continue
            candidates.append((images._photo_date(meta) or "", info["width"] * info["height"], title, info, meta, licence))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates


def photo(name: str, infobox_file: str, surname: str = "", pick: int = 0) -> dict | None:
    """Localizes candidate number `pick` (newest first). The default is the
    newest; a reviewer looking at the contact sheet (see contact_sheet) can
    choose another when the newest is a poor shot."""
    candidates = photo_candidates(name, infobox_file)
    if pick >= len(candidates):
        return {"rejected": "no usable solo photo"}
    date, _, title, info, meta, licence = candidates[pick]
    artist = images._extract_artist_name(meta.get("Artist", {}).get("value", "")) or "Unknown author"
    local = images.localize_image({
        "url": info.get("thumburl") or info["url"],
        "credit": f"{artist}, {licence}, via Wikimedia Commons",
        "sourceUrl": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
    })
    return (local | {"date": date, "width": info["width"], "height": info["height"]}) if local else {"rejected": "download failed"}


def research(player: dict) -> dict:
    out = {"rank": player["rank"], "fideId": player["fideId"], "name": player["name"],
           "federation": player["federation"], "title": player["title"], "rating": player["rating"]}
    page = find_page(player["name"], player["fideId"])
    if not page:
        return out | {"wikipedia": None}
    title, text = page
    image_name = field(text, "image")
    return out | {
        "wikipedia": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
        "infoboxName": field(text, "name"),
        "born": field(text, "birth_date"),
        "birthplace": field(text, "birth_place"),
        "titleField": field(text, "title"),
        "peak": field(text, "peak_rating"),
        "website": field(text, "website"),
        "lead": lead(text),
        "recent": recent_career(text),
        "photoCandidates": [
            {"title": c[2], "date": c[0], "thumb": c[3].get("thumburl"), "width": c[3]["width"], "height": c[3]["height"]}
            for c in photo_candidates(player["name"], image_name)[:5]
        ],
        "infoboxImage": image_name,
    }


def main() -> None:
    """Appends one JSON line per player to the output file as it goes, and
    skips players already in it, so a slow or interrupted run resumes."""
    lo, hi = (int(x) for x in sys.argv[1].split("-"))
    out_path = sys.argv[2]
    done = set()
    try:
        with open(out_path) as f:
            done = {json.loads(line)["fideId"] for line in f if line.strip()}
    except FileNotFoundError:
        pass
    ranking = TOP100["women" if "--women" in sys.argv else "players"]
    players = [p for i, p in enumerate(ranking, start=1) if lo <= i <= hi and p["fideId"] not in done]
    for p in players:
        result = research(p)
        with open(out_path, "a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"{p['name']}: {'ok' if result.get('wikipedia') else 'NO PAGE'}", file=sys.stderr)


if __name__ == "__main__":
    main()
