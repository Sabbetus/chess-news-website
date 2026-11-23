"""Link quoted moves in an article body to our own game viewer.

A move written in the text ("23.h4!", "27...Qe4?") becomes a link to
#ply-<n>, which GameViewer.astro turns into "show this position". Only
moves that match the game's actual main line at that move number and side
are linked; anything else (a side variation the article discusses, or a
move written wrong) is left as plain text and reported, so a mismatch is
visible in review instead of silently pointing at the wrong position.

    python scripts/game_links.py <article.md> <game.pgn>
"""

import re
import sys

# 23.h4  23. h4  23...Qe5  with optional +/#/!/? suffixes. Not inside an
# existing Markdown link (lookbehind on "[").
MOVE_RE = re.compile(
    r"(?<![\[\w.])(\d{1,3})\.(\.\.)?\s?((?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?)[+#]?[!?]{0,2})"
)


def mainline_sans(pgn: str) -> list[str]:
    moves = pgn.split("\n\n", 1)[-1]
    moves = re.sub(r"\{[^}]*\}", " ", moves)
    while True:
        stripped = re.sub(r"\([^()]*\)", " ", moves)
        if stripped == moves:
            break
        moves = stripped
    moves = re.sub(r"\$\d+|\d+\.(\.\.)?|1-0|0-1|1/2-1/2|\*", " ", moves)
    return moves.split()


def _bare(san: str) -> str:
    return re.sub(r"[+#!?]", "", san)


def link_moves(body: str, pgn: str) -> tuple[str, list[str]]:
    sans = mainline_sans(pgn)
    unmatched: list[str] = []

    def replace(m: re.Match) -> str:
        number, black, san = int(m.group(1)), bool(m.group(2)), m.group(3)
        ply = 2 * number - (0 if black else 1)
        if 1 <= ply <= len(sans) and _bare(sans[ply - 1]) == _bare(san):
            return f"[{m.group(0)}](#ply-{ply})"
        unmatched.append(m.group(0))
        return m.group(0)

    # A move already linked to the old Lichess embed anchor
    # ("[15.Nb1!](#game-embed)") becomes a plain move first, so it gets its
    # own position link below.
    def unwrap(m: re.Match) -> str:
        return m.group(1) if MOVE_RE.fullmatch(m.group(1)) else m.group(0)

    body = re.sub(r"\[([^\]]+)\]\(#game-embed\)", unwrap, body)

    def link_part(part: str) -> str:
        # Moves written as one line ("1.e4 c6 2.d4 d5 3.exd5") are linked
        # only if every numbered move in the line is the game's -- caught
        # 2026-11-02: the Panov Attack's "1.e4" was linked to a Ruy Lopez
        # game because its first move happened to match.
        matches = list(MOVE_RE.finditer(part))
        runs: list[list[re.Match]] = []
        for m in matches:
            if runs and _SEQUENCE_GAP_RE.fullmatch(part[runs[-1][-1].end():m.start()]):
                runs[-1].append(m)
            else:
                runs.append([m])
        out, pos = [], 0
        for run in runs:
            ok = all(_played(m) for m in run)
            for m in run:
                out.append(part[pos:m.start()])
                if ok:
                    out.append(replace(m))
                else:
                    unmatched.append(m.group(0))
                    out.append(m.group(0))
                pos = m.end()
        out.append(part[pos:])
        return "".join(out)

    def _played(m: re.Match) -> bool:
        number, black, san = int(m.group(1)), bool(m.group(2)), m.group(3)
        ply = 2 * number - (0 if black else 1)
        return 1 <= ply <= len(sans) and _bare(sans[ply - 1]) == _bare(san)

    # Existing links are left alone: link text is skipped below.
    out_lines = []
    for line in body.split("\n"):
        # Skip text already inside [..](..) by splitting around links.
        parts = re.split(r"(\[[^\]]*\]\([^)]*\))", line)
        out_lines.append("".join(p if p.startswith("[") and "](" in p else link_part(p) for p in parts))
    return "\n".join(out_lines), unmatched


# Text between two numbered moves of one written line: nothing, or Black's
# reply ("1.e4 c6 2.d4").
_SAN = r"(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|O-O(?:-O)?)[+#]?[!?]{0,2}"
_SEQUENCE_GAP_RE = re.compile(rf"\s*(?:{_SAN}\s*)?")
_LINE_START_RE = re.compile(r"(?<![\w.])1\.\s?(?=[KQRBNa-hO])")
_LINE_TOKEN_RE = re.compile(rf"\s*(?:(\d{{1,3}})(?:\.\.\.|\u2026|\.)\s?)?({_SAN})")


def illegal_lines(body: str) -> list[str]:
    """Lines written from move 1 ("1.e4 c6 2.d4 d5 3.cxd5") that can't be
    played on a board -- caught 2026-11-02: the Panov Attack given as
    "3.cxd5" (ChessBase's slip) went into a draft. Returns each bad line
    up to and including the first illegal move."""
    import chess

    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    bad = []
    for start in _LINE_START_RE.finditer(text):
        board, pos, played = chess.Board(), start.start() + 2, ["1."]
        while True:
            m = _LINE_TOKEN_RE.match(text, pos)
            if not m:
                break
            san = re.sub(r"[!?]", "", m.group(2))
            if m.group(1):
                played.append(f"{m.group(1)}.")
            played.append(m.group(2))
            try:
                board.push_san(san)
            except ValueError:
                bad.append(" ".join(played).replace(". ", ".").replace("1. ", "1."))
                break
            pos = m.end()
    return bad


def fix_embed_link(body: str, pgn: str) -> str:
    """A quoted move linked to "#game-embed" must be a move of that game.
    Caught 2026-10-28: Clutch Chess day 1 linked 58...hxg5 (game 1) to the
    embedded game 2. A move that isn't in the game is unlinked, and the
    first quoted move that is gets the link instead (none if none is)."""
    sans = mainline_sans(pgn)

    def played(m: re.Match) -> bool:
        number, black, san = int(m.group(1)), bool(m.group(2)), m.group(3)
        ply = 2 * number - (0 if black else 1)
        return 1 <= ply <= len(sans) and _bare(sans[ply - 1]) == _bare(san)

    def check(m: re.Match) -> str:
        move = MOVE_RE.fullmatch(m.group(1))
        return m.group(0) if move is None or played(move) else m.group(1)

    fixed = re.sub(r"\[([^\]]+)\]\(#game-embed\)", check, body)
    if "(#game-embed)" in fixed:
        return fixed
    for m in MOVE_RE.finditer(fixed):
        before = fixed[: m.start()]
        if played(m) and before.count("[") == before.count("]"):
            return fixed[: m.start()] + f"[{m.group(0)}](#game-embed)" + fixed[m.end():]
    return fixed


def main() -> None:
    article_path, pgn_path = sys.argv[1], sys.argv[2]
    text = open(article_path, encoding="utf-8").read()
    head, sep, body = text[3:].partition("\n---\n")
    pgn = open(pgn_path, encoding="utf-8").read()
    new_body, unmatched = link_moves(body, pgn)
    open(article_path, "w", encoding="utf-8").write("---" + head + sep + new_body)
    print(f"Linked moves; not in the main line (left as text): {unmatched or 'none'}")


if __name__ == "__main__":
    main()


_WIN_VERBS = r"(?:beat|beats|defeated|defeats|outplayed|downed|won against|overcame|took down|ground down)"
_LOSE_VERBS = r"(?:lost to|loses to|fell to|was beaten by|went down to|resigned (?:to|against)|(?:ran|runs) out of time (?:against|after|versus|vs\.?)|lost on time (?:to|against))"
_DRAW_VERBS = r"(?:drew|draws|held|holds|split the point|drawn)"


def _surname(name: str) -> str:
    name = name.split(",")[0] if "," in name else name.split()[-1] if name.split() else name
    return name.strip().lower()


# Game types a sentence and a broadcast round name can both carry.
_GAME_TYPES = {
    "armageddon": r"armageddon",
    "classical": r"fast[- ]classic(?:al)?|classical",
    "rapid": r"rapid",
    "blitz": r"blitz",
}


def _game_type(text: str) -> str | None:
    found = [t for t, pat in _GAME_TYPES.items() if re.search(rf"\b(?:{pat})\b", text, re.I)]
    return found[0] if len(found) == 1 else None


def is_unplayed(pgn: str) -> bool:
    """A forfeit recorded as a game (2026-11-23: Carlsen's forfeited fast
    classic against Artemiev, "1. d4 1-0", Termination "Unplayed", became the
    board for his fast-classic win). Never a board."""
    return bool(re.search(r'\[Termination\s+"Unplayed"\]', pgn, re.I))


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                 "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}


def _game_number(sentence: str) -> int | None:
    """"game two" / "game 2" / "the second game" in a sentence; one number only."""
    found = set()
    for m in re.finditer(r"\bgame\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\b", sentence):
        found.add(int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS[m.group(1)])
    for m in re.finditer(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+game\b", sentence):
        found.add(_NUMBER_WORDS[m.group(1)])
    return found.pop() if len(found) == 1 else None


def check_embed_sentence(body: str, pgn: str, url: str = "") -> tuple[str, str | None]:
    """The sentence carrying the "#game-embed" link must agree with the game
    it points to: its players and its result. Caught 2026-11-14 and
    2026-11-15: "Carlsen lost to Haik Martirosyan" and "Giri beat Mishra"
    both linked to the drawn return game of the same pair. On a mismatch
    the link is removed (the board stays) and a note goes to the PR report.
    Returns (body, note or None)."""
    m = re.search(r"\[([^\]]+)\]\(#game-embed\)", body)
    if not m:
        return body, None
    white = re.search(r'\[White\s+"([^"]+)"\]', pgn)
    black = re.search(r'\[Black\s+"([^"]+)"\]', pgn)
    result = re.search(r'\[Result\s+"([^"]+)"\]', pgn)
    if not (white and black and result):
        return body, None
    w, b, res = _surname(white.group(1)), _surname(black.group(1)), result.group(1)
    # The sentence around the link.
    start = max(body.rfind(". ", 0, m.start()), body.rfind("\n", 0, m.start())) + 1
    end_candidates = [i for i in (body.find(". ", m.end()), body.find("\n", m.end())) if i != -1]
    end = min(end_candidates) if end_candidates else len(body)
    sentence = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body[start:end]).lower()
    # The game type the sentence names must be the board's round's type
    # (2026-11-20: "The fast classic ... was the Game of the Day" linked to
    # the rapid game; the sentence names no player, so nothing else caught it).
    if url:
        round_slug = url.rstrip("/").split("/")[-3] if url.count("/") >= 3 else ""
        said, board = _game_type(sentence), _game_type(round_slug.replace("-", " "))
        if said and board and said != board:
            unlinked = body[: m.start()] + m.group(1) + body[m.end():]
            return unlinked, f"board link removed: the linked sentence describes a {said} game, but the board is from the {board} round ({white.group(1)} - {black.group(1)})"
    # A board that isn't a game at all (a forfeit) never matches.
    if is_unplayed(pgn):
        unlinked = body[: m.start()] + m.group(1) + body[m.end():]
        return unlinked, f"board link removed: the board is an unplayed game ({white.group(1)} - {black.group(1)}, {res})"
    # The game number the sentence names must be the board's round's
    # (2026-11-23: "In game two's time scramble ..." linked to game 3).
    if url:
        said_n = _game_number(sentence)
        board_n = re.search(r"game-(\d{1,2})\b", url.rstrip("/").split("/")[-3] if url.count("/") >= 3 else "")
        if said_n and board_n and said_n != int(board_n.group(1)):
            unlinked = body[: m.start()] + m.group(1) + body[m.end():]
            return unlinked, f"board link removed: the linked sentence names game {said_n}, but the board is game {board_n.group(1)} ({white.group(1)} - {black.group(1)})"
    if w not in sentence and b not in sentence:
        return body, None  # the sentence names neither player: nothing to compare
    problem = None
    winner = w if res == "1-0" else b if res == "0-1" else None
    loser = b if res == "1-0" else w if res == "0-1" else None
    for x, y in ((w, b), (b, w)):
        if re.search(rf"{re.escape(x)}\b[^.]{{0,60}}?\b{_WIN_VERBS}\b[^.]{{0,40}}?\b{re.escape(y)}", sentence) or re.search(
            rf"{re.escape(y)}\b[^.]{{0,60}}?\b{_LOSE_VERBS}\b[^.]{{0,40}}?\b{re.escape(x)}", sentence
        ):
            if winner != x:
                problem = f"says {x.title()} beat {y.title()}, but the board's game ended {res}"
    if problem is None and winner and re.search(rf"\b{_DRAW_VERBS}\b", sentence) and not re.search(rf"\b{_WIN_VERBS}\b|\b{_LOSE_VERBS}\b", sentence):
        problem = f"describes a draw, but the board's game ended {res}"
    if problem is None:
        return body, None
    unlinked = body[: m.start()] + m.group(1) + body[m.end():]
    return unlinked, f"board link removed: the linked sentence {problem} ({white.group(1)} - {black.group(1)})"
