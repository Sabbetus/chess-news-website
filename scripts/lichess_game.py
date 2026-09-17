"""Finds a real, embeddable Lichess board for a specific game a drafted
article centers on -- e.g. Erigaisi's Round 1 loss to Laohawirapap at the
46th Olympiad. Only called when draft.py's model output actually names two
players for a specific game (see @@GAME_LOOKUP@@ in NEWS_SYSTEM_PROMPT);
most articles don't name one and this is never invoked for them, since a
web_search call costs real money and most stories -- calendar aggregates,
team-score pieces, multi-game trend pieces -- have no single game to show.

Two-step process, deliberately split so the risky step (is this really the
right game) is a plain string comparison against real data, not a model
guess:
  1. Ask Claude (with the web_search tool) to find the Lichess broadcast
     round covering this game. Search is genuinely reliable for this --
     FIDE-relayed events are near-universally broadcast on Lichess, and a
     plain "<event> <player1> <player2> lichess" query finds them.
  2. Fetch that round's PGN from Lichess's own broadcast API (structured,
     official data, not scraped) and look for the one game whose
     White/Black tags match both players by surname. Only an unambiguous
     single match gets embedded -- zero or multiple matches means no
     embed, not a guess.
"""

import re

import requests

USER_AGENT = "Chess-Herald-GameFinder/1.0 (https://chessherald.com; contact: sabbe.the.technomage@gmail.com)"
REQUEST_TIMEOUT = 15

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}

FINDER_MODEL = "claude-sonnet-5"

FINDER_SYSTEM_PROMPT = """You find the Lichess broadcast round covering one specific chess game.

You'll be given an event name and two player names. Search the web for a \
Lichess broadcast of that event and identify the round containing the game \
between those two players (searching something like "<event> <player1> \
lichess broadcast" usually works -- FIDE-relayed events are almost always \
on Lichess).

Respond with ONLY a Lichess broadcast round URL in the form \
https://lichess.org/broadcast/<tournament-slug>/<round-slug>/<roundId> (the \
roundId is the 8-character code in the path; a URL that also has a specific \
game/chapter id after the roundId is fine too, it'll be ignored). If you \
cannot find a real Lichess broadcast covering this specific event with \
reasonable confidence, respond with exactly NONE and nothing else. Never \
guess a plausible-looking URL -- an absent embed is fine, a broken or wrong \
one is not."""

# Matches a Lichess broadcast URL's tournament/round-slug/roundId segments --
# tolerant of an optional trailing /chapterId, which is ignored: the actual
# game gets found deterministically in find_game_in_round below, not trusted
# from the model's own URL pick.
BROADCAST_URL_RE = re.compile(r"lichess\.org/broadcast/([^/\s]+)/([^/\s]+)/(\w{8})(?:/\w{8})?")


def _surname(full_name: str) -> str:
    return full_name.strip().split()[-1].lower() if full_name.strip() else ""


def _tag_tokens(tag_value: str) -> set[str]:
    """Lichess's broadcast PGNs give player names in whatever format the
    organizer's FIDE feed used -- "Surname, Firstname" and "Surname
    Firstname" (no comma) both show up in the same round's data. Returning
    every individual word (comma stripped) rather than picking one
    position as "the surname" is what makes the caller's match tolerant of
    both without needing to know which format a given game used."""
    return {t.strip(",").lower() for t in tag_value.replace(",", " ").split()}


def find_broadcast_round(client, event: str, player1: str, player2: str) -> tuple[str, str, str] | None:
    """Returns (tournamentSlug, roundSlug, roundId) or None."""
    user_prompt = f"Event: {event}\nPlayer 1: {player1}\nPlayer 2: {player2}"
    response = client.messages.create(
        model=FINDER_MODEL,
        max_tokens=1024,
        system=FINDER_SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": user_prompt}],
    )

    for _ in range(3):
        if response.stop_reason != "pause_turn":
            break
        response = client.messages.create(
            model=FINDER_MODEL,
            max_tokens=1024,
            system=FINDER_SYSTEM_PROMPT,
            tools=[WEB_SEARCH_TOOL],
            messages=[
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": response.content},
            ],
        )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        return None

    match = BROADCAST_URL_RE.search(text_blocks[-1])
    return (match.group(1), match.group(2), match.group(3)) if match else None


def find_game_in_round(round_id: str, player1: str, player2: str) -> str | None:
    """Fetches the round's PGN from Lichess's broadcast API and returns the
    matched game's own GameURL tag if exactly one game's White/Black pair
    matches both players by surname -- None otherwise (no game found, or
    more than one candidate, which means the match isn't confident enough
    to trust)."""
    url = f"https://lichess.org/api/broadcast/round/{round_id}.pgn"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return None

    surname1, surname2 = _surname(player1), _surname(player2)
    if not surname1 or not surname2:
        return None

    matches = []
    for game_pgn in re.split(r"\n\n\n+", response.text.strip()):
        white = re.search(r'\[White\s+"([^"]+)"\]', game_pgn)
        black = re.search(r'\[Black\s+"([^"]+)"\]', game_pgn)
        game_url = re.search(r'\[GameURL\s+"([^"]+)"\]', game_pgn)
        if not (white and black and game_url):
            continue
        white_tokens, black_tokens = _tag_tokens(white.group(1)), _tag_tokens(black.group(1))
        matched = (surname1 in white_tokens and surname2 in black_tokens) or (
            surname2 in white_tokens and surname1 in black_tokens
        )
        if matched:
            matches.append(game_url.group(1))

    return matches[0] if len(matches) == 1 else None


def embed_url_from_game_url(game_url: str) -> str:
    """https://lichess.org/broadcast/<ts>/<rs>/<roundId>/<gameId> ->
    https://lichess.org/embed/broadcast/<ts>/<rs>/<roundId>/<gameId>, the
    exact embeddable form (verified against Lichess's own route table)."""
    return game_url.replace("lichess.org/broadcast/", "lichess.org/embed/broadcast/", 1)


def find_game_embed(client, event: str, player1: str, player2: str) -> dict | None:
    """Top-level entry point: returns {"url": <embed url>} or None. Never
    raises for a "just didn't find it" outcome -- only network/programming
    errors propagate, since a missing embed is an expected, normal result
    for most calls (only invoked when draft.py's model named two players
    for one specific game in the first place)."""
    round_ref = find_broadcast_round(client, event, player1, player2)
    if round_ref is None:
        return None
    _, _, round_id = round_ref

    game_url = find_game_in_round(round_id, player1, player2)
    if game_url is None:
        return None

    return {"url": embed_url_from_game_url(game_url)}
