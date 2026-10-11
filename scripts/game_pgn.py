"""Find the PGN of the game an article is about, for our own GameViewer.

Used only when the game is NOT on Lichess -- a Lichess game keeps the
Lichess embed, which lets readers switch to other games from the same
event (user's call, 2026-10-06). pgn_from_lichess_embed is kept for other
uses but draft.py doesn't call it for the board.

Source: the page itself. Chess.com reports show each game as a diagram
  whose PGN comes from Chess.com's diagram endpoint (see
  _chesscom_diagram_pgns). ChessBase articles load their board from a PGN
  file named in a data-url attribute. One file can hold several games, so
  a game is only used when it can be picked unambiguously (the players the
  draft named, or the only game whose two players both appear in the body).

Only the main line and a few headers are kept: the source's annotations
are its own work, not ours to republish.
"""

import re
import urllib.parse

import requests

USER_AGENT = "Chess-Herald-Pipeline/1.0 (https://chessherald.com)"
TIMEOUT = 30
KEEP_HEADERS = ("Event", "Site", "Date", "Round", "White", "Black", "Result")
PGN_URL_RE = re.compile(r'data-url="([^"]+\.pgn)"', re.IGNORECASE)
CHESSCOM_DIAGRAM_RE = re.compile(r"diagram_\d+_(\d+)")
EMBED_RE = re.compile(r"lichess\.org/embed/broadcast/[^/]+/[^/]+/(\w{8})/(\w{8})")


def _get(url: str) -> str | None:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text
    except requests.RequestException:
        return None


def split_games(pgn: str) -> list[str]:
    games = re.split(r"\n\s*\n(?=\[Event )", pgn.strip().replace("\r\n", "\n"))
    return [g.strip() for g in games if g.strip().startswith("[")]


def headers(game: str) -> dict:
    return dict(re.findall(r'^\[(\w+) "([^"]*)"\]', game, re.MULTILINE))


def clean_game(game: str) -> str:
    """Headers we show plus the bare main line -- no comments, variations,
    NAGs or clock data."""
    head = headers(game)
    moves = game.split("\n\n", 1)[1] if "\n\n" in game else ""
    moves = re.sub(r"\{[^}]*\}", " ", moves)
    while True:
        stripped = re.sub(r"\([^()]*\)", " ", moves)
        if stripped == moves:
            break
        moves = stripped
    moves = re.sub(r"\$\d+|\d+\.\.\.", " ", moves)
    moves = re.sub(r"(?<=[\w+#=])[!?]+", "", moves)  # "a5??" -> "a5"
    kept = "\n".join(f'[{k} "{head[k]}"]' for k in KEEP_HEADERS if k in head)
    return kept + "\n\n" + " ".join(moves.split()) + "\n"


def _surnames(tag: str) -> set[str]:
    return {t.lower() for t in re.split(r"[\s,.]+", tag) if len(t) >= 3}


def _plays(game: str, name: str) -> bool:
    if not name:
        return False
    head = headers(game)
    surname = name.strip().split()[-1].lower()
    return surname in _surnames(head.get("White", "")) | _surnames(head.get("Black", ""))


def pick_game(games: list[str], body: str, player1: str = "", player2: str = "") -> str | None:
    if player1 and player2:
        named = [g for g in games if _plays(g, player1) and _plays(g, player2)]
        if len(named) == 1:
            return named[0]
    if len(games) == 1:
        return games[0]
    text = body.lower()
    in_body = []
    for g in games:
        head = headers(g)
        white = (head.get("White", "").split(",")[0] or "").strip().lower()
        black = (head.get("Black", "").split(",")[0] or "").strip().lower()
        if white and black and white in text and black in text:
            # Where the pair is first discussed: the later of the two names'
            # first mentions.
            in_body.append((max(text.index(white), text.index(black)), g))
    if not in_body:
        return None
    # A round report names many games; the lead game is the one whose
    # players the article reaches first (2026-10-11, U.S. Championship).
    return min(in_body, key=lambda pair: pair[0])[1]


def pgn_from_lichess_embed(embed_url: str) -> str | None:
    m = EMBED_RE.search(embed_url or "")
    if not m:
        return None
    round_id, game_id = m.groups()
    return _get(f"https://lichess.org/api/study/{round_id}/{game_id}.pgn")


def _chesscom_diagram_pgns(page: str) -> str | None:
    """Chess.com reports show games as diagrams ("diagram_3_15843838"); each
    one's PGN comes from its public diagram endpoint. Added 2026-10-11 so
    the U.S. Championship (not on Lichess) gets our own board."""
    games = []
    for diagram_id in dict.fromkeys(CHESSCOM_DIAGRAM_RE.findall(page)):
        try:
            response = requests.get(f"https://www.chess.com/callback/diagram/{diagram_id}",
                                    headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue
        if data.get("type") != "chessGame":
            continue
        for setup in data.get("setup") or []:
            if (setup.get("pgn") or "").strip().startswith("["):
                games.append(setup["pgn"].strip())
    return "\n\n".join(games) or None


def pgn_from_source_page(source_url: str) -> str | None:
    page = _get(source_url) if source_url else None
    if not page:
        return None
    m = PGN_URL_RE.search(page)
    if m:
        return _get(urllib.parse.urljoin(source_url, m.group(1)))
    if "chess.com" in urllib.parse.urlparse(source_url).netloc:
        return _chesscom_diagram_pgns(page)
    return None


def find_game_pgn(source_url: str, embed_url: str, body: str, player1: str = "", player2: str = "") -> str | None:
    """Returns a cleaned single-game PGN, or None."""
    for raw in (pgn_from_lichess_embed(embed_url) if embed_url else None, pgn_from_source_page(source_url)):
        if not raw:
            continue
        game = pick_game(split_games(raw), body, player1, player2)
        if game:
            return clean_game(game)
    return None
