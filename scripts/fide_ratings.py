"""Refreshes data/fide-top100.json -- the /players/ page's top 100 table --
from FIDE's official monthly standard rating list.

FIDE publishes a new list on the 1st of each month. This runs inside the
daily deploy job (like fetch_popular.py) and is a no-op unless the stored
list is from an earlier month than the one FIDE is now serving, so it
downloads the ~13 MB file about once a month.

Top 100 means the open list the way FIDE's own ranking shows it: active
players only (FIDE marks inactive players with an "i" flag). The previous
month's archive gives each player's rating change and rank movement.

Best-effort: any failure (FIDE down, a format change) leaves the stored
file untouched, so the page keeps last month's table instead of breaking
the deploy.
"""

import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
OUT_PATH = ROOT / "data" / "fide-top100.json"

CURRENT_URL = "https://ratings.fide.com/download/standard_rating_list.zip"
ARCHIVE_URL = "https://ratings.fide.com/download/standard_{mon}{yy}frl.zip"
USER_AGENT = "ChessHeraldBot/1.0 (+https://chessherald.com/about/)"
TOP_N = 100
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

# Federations whose players FIDE lists family name first and English-language
# coverage keeps that order ("Wei Yi", "Le Quang Liem"), so "Wei, Yi" must not
# be flipped into "Yi Wei".
FAMILY_NAME_FIRST = {"CHN", "HKG", "TPE", "VIE", "KOR", "PRK", "MGL", "SGP"}


def download_list(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=180)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".txt"))
        return zf.read(name).decode("latin-1")


def display_name(fide_name: str, federation: str) -> str:
    if "," not in fide_name:
        return fide_name.strip()
    family, given = (part.strip() for part in fide_name.split(",", 1))
    return f"{family} {given}" if federation in FAMILY_NAME_FIRST else f"{given} {family}"


def parse_list(text: str) -> tuple[str, list[dict]]:
    """(period like "SEP26", active players sorted by rating, best first).
    The file is fixed-width; column positions come from the header line
    because FIDE has shifted them between years."""
    lines = text.splitlines()
    header = lines[0]
    period = re.search(r"\b([A-Z]{3}\d{2})\b", header[header.index("FOA") + 3 :]).group(1)
    col = {name: header.index(name) for name in ["Name", "Fed", "Sex", "Tit", "WTit", "Gms", "B-day", "Flag"]}
    col["rating"] = header.index(period)
    players = []
    for line in lines[1:]:
        if "i" in line[col["Flag"] :].strip():
            continue
        rating = line[col["rating"] : col["Gms"]].strip()
        if not rating.isdigit():
            continue
        federation = line[col["Fed"] : col["Sex"]].strip()
        birth = line[col["B-day"] : col["Flag"]].strip()
        players.append(
            {
                "fideId": line[: col["Name"]].strip(),
                "name": display_name(line[col["Name"] : col["Fed"]], federation),
                "federation": federation,
                "title": line[col["Tit"] : col["WTit"]].strip(),
                "birthYear": int(birth) if birth.isdigit() and birth != "0" else None,
                "rating": int(rating),
                "games": int(line[col["Gms"] : col["Gms"] + 4].strip() or 0),
            }
        )
    players.sort(key=lambda p: -p["rating"])
    return period, players


def period_to_date(period: str) -> datetime:
    return datetime(2000 + int(period[3:]), MONTHS.index(period[:3].lower()) + 1, 1)


def previous_period(period: str) -> str:
    d = period_to_date(period)
    year, month = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return f"{MONTHS[month - 1]}{year % 100:02d}"


def build_table(period: str, current: list[dict], previous: list[dict]) -> dict:
    prev_rating = {p["fideId"]: p["rating"] for p in previous}
    prev_rank = {p["fideId"]: i for i, p in enumerate(previous[:TOP_N], start=1)}
    rows, rank, last_rating = [], 0, None
    for i, p in enumerate(current[:TOP_N], start=1):
        # Tied ratings share a rank, the way FIDE's own list shows them.
        if p["rating"] != last_rating:
            rank, last_rating = i, p["rating"]
        rows.append(
            {
                **p,
                "rank": rank,
                "change": p["rating"] - prev_rating[p["fideId"]] if p["fideId"] in prev_rating else None,
                "previousRank": prev_rank.get(p["fideId"]),
            }
        )
    return {
        "period": period_to_date(period).strftime("%Y-%m"),
        "source": "FIDE standard rating list",
        "sourceUrl": "https://ratings.fide.com/",
        "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "players": rows,
    }


def main() -> None:
    stored = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else {}
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if stored.get("period") == this_month and "--force" not in sys.argv:
        print(f"FIDE top 100 already current ({this_month}).")
        return
    try:
        period, current = parse_list(download_list(CURRENT_URL))
        if stored.get("period") == period_to_date(period).strftime("%Y-%m") and "--force" not in sys.argv:
            print(f"FIDE hasn't published a newer list yet (still {period}).")
            return
        prev = previous_period(period)
        _, previous = parse_list(download_list(ARCHIVE_URL.format(mon=prev[:3], yy=prev[3:])))
        table = build_table(period, current, previous)
    except Exception as exc:  # noqa: BLE001 -- best-effort, see module docstring
        print(f"FIDE top 100 refresh skipped ({type(exc).__name__}: {exc}).", file=sys.stderr)
        return
    OUT_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote FIDE top 100 for {table['period']} ({len(table['players'])} players).")


if __name__ == "__main__":
    main()
