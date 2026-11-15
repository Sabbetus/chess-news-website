"""The event's own results, colours and next pairings from its Lichess
broadcast, as ground truth for the fact check (user's call, 2026-11-15).

Most resets come from wrong results, colours, pairings or rounds left --
often the source's own slips (Chess.com's "Martirosyan plays Giri" for the
Total Chess final round, ChessBase's "fifth win" for So), which a check
against the source alone cannot catch. The broadcast PGNs are the record:
the fact check gets the last few rounds' results and the next round's
pairings, and corrects the article where it disagrees with them.

Best effort: any failure returns None and the fact check runs as before.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone

import requests

from lichess_game import (
    KNOWN_BROADCAST_TOURNAMENTS,
    REQUEST_TIMEOUT,
    USER_AGENT,
    _search_tours,
)

ROUNDS_BACK = 4
MAX_GAMES_PER_ROUND = 40
MAX_CHARS = 12000
MAX_SECTIONS = 4


def _get(url: str, accept: str | None = None) -> requests.Response | None:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    for attempt in (1, 2):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429 and attempt == 1:
                time.sleep(60)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            print(f"    broadcast facts: fetch failed for {url}: {exc}", file=sys.stderr)
            return None
    return None


def _tour_ids(event: str, around: datetime) -> list[str]:
    key = event.strip().lower()
    known = next((ids for name, ids in KNOWN_BROADCAST_TOURNAMENTS.items() if name in key), None)
    if known:
        return list(known)[:2]
    # Sectioned events (Open 50+, Women 65+...) are one broadcast per
    # section: take the sections of the best match, up to four.
    tours = _search_tours(event, around)
    if not tours:
        return []
    base = (tours[0].get("name") or "").split("|")[0].strip().lower()
    same = [t for t in tours if (t.get("name") or "").split("|")[0].strip().lower() == base]
    return [t["id"] for t in same[:MAX_SECTIONS]]


def _games(pgn_text: str) -> list[str]:
    lines = []
    for game in re.split(r"\n\n\n+", pgn_text.strip()):
        white = re.search(r'\[White\s+"([^"]+)"\]', game)
        black = re.search(r'\[Black\s+"([^"]+)"\]', game)
        result = re.search(r'\[Result\s+"([^"]+)"\]', game)
        if not (white and black):
            continue
        res = result.group(1) if result else "*"
        res = {"1-0": "1-0 (White won)", "0-1": "0-1 (Black won)", "1/2-1/2": "draw", "*": "not finished"}.get(res, res)
        lines.append(f"  {white.group(1)} (White) - {black.group(1)} (Black): {res}")
    return lines[:MAX_GAMES_PER_ROUND]


def broadcast_facts(event: str, around: datetime | None = None) -> str | None:
    """A plain-text block of recent results and next pairings, or None."""
    if not event:
        return None
    around = around or datetime.now(timezone.utc)
    try:
        tour_ids = _tour_ids(event, around)
    except Exception as exc:  # noqa: BLE001 -- best effort
        print(f"    broadcast facts: search failed for {event!r}: {exc}", file=sys.stderr)
        return None
    blocks = []
    for tour_id in tour_ids:
        response = _get(f"https://lichess.org/api/broadcast/{tour_id}", accept="application/json")
        if response is None:
            continue
        try:
            data = response.json()
        except ValueError:
            continue
        name = (data.get("tour") or {}).get("name") or tour_id
        rounds = data.get("rounds", [])
        played = [r for r in rounds if r.get("finished") or r.get("ongoing")]
        upcoming = [r for r in rounds if not (r.get("finished") or r.get("ongoing"))][:1]
        lines = [f"Broadcast: {name}"]
        back = ROUNDS_BACK if len(tour_ids) == 1 else 2
        for round_ in played[-back:] + upcoming:
            pgn = _get(f"https://lichess.org/api/broadcast/round/{round_['id']}.pgn")
            if pgn is None:
                continue
            state = "next round, pairings" if round_ in upcoming else ("in progress" if round_.get("ongoing") else "finished")
            games = _games(pgn.text)
            if games:
                lines.append(f"{round_.get('name')} ({state}):")
                lines += games
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    if not blocks:
        print(f"    broadcast facts: nothing found for {event!r}", file=sys.stderr)
        return None
    text = "\n\n".join(blocks)
    print(f"    broadcast facts: {len(text)} chars for {event!r}", file=sys.stderr)
    return text[:MAX_CHARS]
