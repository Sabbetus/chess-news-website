"""Swap a board for the game its linked sentence describes (user's call,
2026-11-15: fix the board, not just flag it).

When check_embed_sentence finds that the sentence carrying the "#game-embed"
link contradicts the embedded game ("Giri beat Mishra" on a drawn game), the
game the sentence means is almost always another game between the same two
players in the same round or the one either side of it (a two-game
mini-match, a tiebreak). This looks there and returns the first game the
sentence agrees with.
"""

from __future__ import annotations

import re

from broadcast_facts import _get
from game_links import _surname, check_embed_sentence, is_unplayed


def _pair(pgn: str) -> frozenset[str] | None:
    white = re.search(r'\[White\s+"([^"]+)"\]', pgn)
    black = re.search(r'\[Black\s+"([^"]+)"\]', pgn)
    if not (white and black):
        return None
    return frozenset({_surname(white.group(1)), _surname(black.group(1))})


def matching_pair_game(embed_url: str, embed_pgn: str, body: str) -> tuple[str, str] | None:
    """(new embed URL, its PGN) for a game between the same pair that the
    linked sentence agrees with, or None. `body` still carries the link."""
    parts = embed_url.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    round_id, current_game = parts[-2], parts[-1]
    pair = _pair(embed_pgn)
    if not pair:
        return None
    response = _get(f"https://lichess.org/api/broadcast/-/-/{round_id}", accept="application/json")
    if response is None:
        return None
    try:
        data = response.json()
        tour_id = data["tour"]["id"]
    except (ValueError, KeyError, TypeError):
        return None
    tour = _get(f"https://lichess.org/api/broadcast/{tour_id}", accept="application/json")
    if tour is None:
        return None
    try:
        rounds = tour.json().get("rounds", [])
    except ValueError:
        return None
    index = next((i for i, r in enumerate(rounds) if r.get("id") == round_id), None)
    if index is None:
        return None
    # The same round first (a tiebreak or match round), then the round
    # before and after (a mini-match spread over two rounds).
    for i in (index, index - 1, index + 1):
        if not 0 <= i < len(rounds):
            continue
        pgn_text = _get(f"https://lichess.org/api/broadcast/round/{rounds[i]['id']}.pgn")
        if pgn_text is None:
            continue
        for game in re.split(r"\n\n\n+", pgn_text.text.strip()):
            url = re.search(r'\[GameURL\s+"([^"]+)"\]', game)
            if not url or url.group(1).rstrip("/").endswith("/" + current_game):
                continue
            if _pair(game) != pair or re.search(r'\[Result\s+"\*"\]', game) or is_unplayed(game):
                continue
            if check_embed_sentence(body, game, url.group(1))[1] is None:
                return url.group(1).replace("lichess.org/broadcast/", "lichess.org/embed/broadcast/", 1), game
    return None
