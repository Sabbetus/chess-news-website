"""Research helper for the /players/ reference pages (not part of the daily
pipeline). For each FIDE top-100 rank given, collects the facts a player page
needs from Wikipedia, and the infobox photo from Commons, into a JSON file a
writer drafts the page from.

Every Wikipedia page is checked against FIDE: its infobox FIDE_id must equal
the player's FIDE ID, or the page is rejected (names collide; FIDE IDs don't).
Photos go through images.py's licence check and localize_image, so they land
in the same committed master store as article photos.

    python scripts/player_research.py 1-20 research.jsonl
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


def lead(text: str) -> str:
    body = re.sub(r"\{\{[^{}]*\}\}", "", re.sub(r"\{\{[^{}]*\}\}", "", text))
    body = body.split("\n==", 1)[0]
    return clean(body)[:2500]


def photo(filename: str) -> dict | None:
    if not filename:
        return None
    title = "File:" + filename.replace("File:", "").strip()
    try:
        data = images._get({"action": "query", "titles": title, "prop": "imageinfo",
                            "iiprop": "url|extmetadata|size", "iiurlwidth": 1600})
        page = next(iter(data["query"]["pages"].values()))
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        licence = meta.get("LicenseShortName", {}).get("value", "")
        if not images._license_ok(licence):
            return {"rejected": f"licence {licence!r}"}
        artist = images._extract_artist_name(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        source_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        local = images.localize_image({
            "url": info.get("thumburl") or info["url"],
            "credit": f"{artist}, {licence}, via Wikimedia Commons",
            "sourceUrl": source_url,
        })
        return local | {"width": info["width"], "height": info["height"]} if local else {"rejected": "download failed"}
    except Exception as exc:  # noqa: BLE001 -- research helper, keep going
        return {"rejected": f"{type(exc).__name__}: {exc}"}


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
        "photo": photo(image_name),
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
    players = [p for i, p in enumerate(TOP100["players"], start=1) if lo <= i <= hi and p["fideId"] not in done]
    for p in players:
        result = research(p)
        with open(out_path, "a") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"{p['name']}: {'ok' if result.get('wikipedia') else 'NO PAGE'}", file=sys.stderr)


if __name__ == "__main__":
    main()
