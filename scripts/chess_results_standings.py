"""Fetch top-N team standings from chess-results.com for a known major tournament.

Used to attach a verified standings table to daily results articles for
ongoing major tournaments (Olympiad, etc.), instead of asking the drafting
model to transcribe rankings out of source prose -- a source article rarely
states the full order clearly, and reconstructing it from memory/inference
is exactly the kind of fabrication this pipeline has been burned by before
(see CLAUDE.md's standing rules). The table is built entirely from parsed
HTML; the model never touches the numbers.

If chess-results doesn't have the tournament, the page structure doesn't
match, or the fetch fails for any reason, callers get None back and are
expected to skip the table for that day -- an incomplete article beats a
wrong one.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# chess-results assigns a new tournament id ("tnr") per edition -- these
# must be updated by hand each time a tracked tournament recurs (or a new
# one is added). Keep this in sync with MAJOR_TOURNAMENT_KEYWORDS in
# selection.py: a tournament only gets a standings table here if it's also
# recognized there as newsworthy enough to score the major-tournament bonus.
KNOWN_TOURNAMENTS: dict[str, dict[str, str]] = {
    "olympiad": {
        "open": "1469895",
        "women": "1469896",
    },
}

# Columns, in order: Rk. | SNo | FED | (flag) | Team | Group | Games | + | = | - | TB1 | TB2 | TB3 | TB4
# TB1 is match points (the primary sort key for a Swiss team event); TB3 is
# board/game points. TB2 and TB4 are further tiebreaks we don't currently
# surface. Verified against the real Round 7 Olympiad standings page.
_ROW_RE = re.compile(
    r'<tr class="CRng[12]">\s*'
    r'<td class="CRc">(?P<rank>\d+)</td>'
    r'<td class="CRc">\d+</td>'
    r'<td class="CRc">(?P<fed>[A-Z]{3})</td>'
    r'<td class="CR"><div[^>]*></div></td>'
    r'<td class="CR"><a[^>]*>(?P<name>[^<]+)</a></td>'
    r'<td class="CRc">[^<]*</td>'
    r'<td class="CRc">\d+</td>'
    r'<td class="CRc">(?P<wins>\d+)</td>'
    r'<td class="CRc">(?P<draws>\d+)</td>'
    r'<td class="CRc">(?P<losses>\d+)</td>'
    r'<td class="CRc">(?P<match_points>[\d,]+)</td>'
    r'<td class="CRc">(?P<tb2>[\d,]+)</td>'
    r'<td class="CRc">(?P<board_points>[\d,]+)</td>'
)

MIN_PLAUSIBLE_ROWS = 3


@dataclass
class StandingsRow:
    rank: int
    federation: str
    team: str
    wins: int
    draws: int
    losses: int
    match_points: float
    board_points: float


def _fetch(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return None


def fetch_team_standings(
    tournament_key: str,
    section: str = "open",
    round_num: int | None = None,
    top_n: int = 10,
) -> list[StandingsRow] | None:
    """Top-N team standings for a known tournament, or None if unavailable.

    round_num omitted fetches the current/latest ranking page.
    """
    tnr = KNOWN_TOURNAMENTS.get(tournament_key, {}).get(section)
    if not tnr:
        return None

    url = f"https://chess-results.com/tnr{tnr}.aspx?lan=1&art=0&turdet=YES&flag=30"
    if round_num is not None:
        url += f"&rd={round_num}"

    html = _fetch(url)
    if not html:
        return None

    rows: list[StandingsRow] = []
    for match in _ROW_RE.finditer(html):
        rows.append(
            StandingsRow(
                rank=int(match["rank"]),
                federation=match["fed"],
                team=match["name"].strip(),
                wins=int(match["wins"]),
                draws=int(match["draws"]),
                losses=int(match["losses"]),
                match_points=float(match["match_points"].replace(",", ".")),
                board_points=float(match["board_points"].replace(",", ".")),
            )
        )
        if len(rows) >= top_n:
            break

    # A genuine standings page for a real ongoing tournament always has at
    # least a handful of ranked teams -- fewer than that means the regex
    # didn't actually match the real table (a page-layout change, an error
    # page, a JS-only shell) rather than a small field, so treat it as a
    # failed fetch rather than publish a suspiciously short table.
    if len(rows) < MIN_PLAUSIBLE_ROWS:
        return None

    return rows


def standings_markdown_table(rows: list[StandingsRow], section_label: str = "") -> str:
    heading = f"**{section_label} standings**" if section_label else "**Standings**"
    lines = [
        heading,
        "",
        "| Rank | Team | W–D–L | Match Pts | Board Pts |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.rank} | {row.team} | {row.wins}–{row.draws}–{row.losses} "
            f"| {row.match_points:g} | {row.board_points:g} |"
        )
    return "\n".join(lines)
