"""Finnish clubs at the European Club Cup, for a sub-section of every Club
Cup piece (user's call, 2026-10-18: the Finnish angle as a sub-theme, not
the main story).

Data comes from chess-results.com. The tournament ids are taken from links
on the source pages (ChessBase links its "all teams" tables); when no
source links one, CHESS_RESULTS_IDS below is the fallback -- add each new
edition's ids there. The team starting list shown with federation flags
(flag=30) carries each team's federation, so the Finnish clubs are read
straight from it rather than guessed from team names.

Best-effort like the game boards: any failure returns None and the piece
is drafted without the sub-section.
"""

import html
import re
import time

import requests

USER_AGENT = "Chess-Herald-Pipeline/1.0 (https://chessherald.com)"
TIMEOUT = 30
FEDERATION = "FIN"
CLUB_CUP_RE = re.compile(r"\bclub cup\b", re.IGNORECASE)
TNR_RE = re.compile(r"chess-results\.com/tnr(\d+)", re.IGNORECASE)
# Fallback when no source page links chess-results: edition -> ids (Open,
# Women's). The 2026 ids were read from ChessBase's preview.
CHESS_RESULTS_IDS = {"2026": ["1475190", "1475191"]}
MAX_ROUNDS = 11


def _get(url: str) -> str | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
        time.sleep(1)  # chess-results rate-limits bursts
        return resp.text
    except requests.RequestException:
        return None


def _cells(row_html: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def is_club_cup(item: dict) -> bool:
    return bool(CLUB_CUP_RE.search(f"{item.get('title', '')} {(item.get('summary') or '')[:400]}"))


def tournament_ids(item: dict) -> list[str]:
    ids: list[str] = []
    for url in [item.get("sourceUrl", "")] + [s.get("sourceUrl", "") for s in item.get("additionalSources") or []]:
        page = _get(url) if url else None
        for tnr in TNR_RE.findall(page or ""):
            if tnr not in ids:
                ids.append(tnr)
    if not ids:
        year = (item.get("publishedAt") or "")[:4]
        ids = list(CHESS_RESULTS_IDS.get(year, []))
    return ids


def _federation_teams(tnr: str) -> tuple[str, list[tuple[str, str]]]:
    """(tournament name, [(seed, team)]) for teams of FEDERATION."""
    page = _get(f"https://chess-results.com/tnr{tnr}.aspx?lan=1&art=0&flag=30") or ""
    title = re.search(r"<h2>(.*?)</h2>", page, re.S)
    name = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else f"tnr{tnr}"
    teams = []
    for row in re.findall(r'<tr class="CRng[12]">(.*?)</tr>', page, re.S):
        if FEDERATION in row:
            cells = _cells(row)
            if len(cells) > 3:
                teams.append((cells[1], cells[3]))
    return name, teams


def _round_rows(tnr: str, rnd: int) -> list[list[str]]:
    page = _get(f"https://chess-results.com/tnr{tnr}.aspx?lan=1&art=2&rd={rnd}") or ""
    return [c for c in (_cells(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)) if len(c) >= 6 and c[0].isdigit()]


def finnish_clubs_facts(item: dict) -> str | None:
    if not is_club_cup(item):
        return None
    lines = []
    for tnr in tournament_ids(item):
        name, teams = _federation_teams(tnr)
        if not teams:
            continue
        names = {team for _, team in teams}
        results: dict[str, list[str]] = {team: [] for team in names}
        upcoming: dict[str, str] = {}
        for rnd in range(1, MAX_ROUNDS + 1):
            rows = _round_rows(tnr, rnd)
            if not rows:
                break
            played = False
            for c in rows:
                home, away, s1, s2 = c[1], c[2], c[3], c[5]
                for team, opp, mine, theirs in ((home, away, s1, s2), (away, home, s2, s1)):
                    if team in names:
                        if mine:
                            results[team].append(f"round {rnd}: {mine}-{theirs} vs {opp}")
                            played = True
                        else:
                            upcoming.setdefault(team, f"round {rnd} vs {opp}")
            if not played:
                break
        lines.append(f"{name} -- Finnish ({FEDERATION}) teams, with starting seed:")
        for seed, team in teams:
            done = "; ".join(results[team]) or "no rounds played yet"
            nxt = f"; next: {upcoming[team]}" if team in upcoming else ""
            lines.append(f"- {team} (seed {seed}): {done}{nxt}")
    return "\n".join(lines) if lines else None


FINNISH_SUBSECTION_INSTRUCTION = (
    "Finnish clubs: the reader base follows the Finnish teams closely. Add one short "
    "sub-section (a bold heading and one or two short paragraphs) on how the Finnish "
    "clubs listed below are doing, using only these results. It is a sub-theme: keep "
    "the main story first and do not mention Finland in the headline. Name each "
    "Finnish team and its result; scores are team match scores (board points). If the "
    "list is empty, leave the sub-section out."
)
