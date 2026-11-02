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
