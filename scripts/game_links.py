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

    # Leave frontmatter and existing links alone: only the body text after
    # the closing "---" is rewritten, and link text is skipped by the regex.
    out_lines = []
    for line in body.split("\n"):
        # Skip text already inside [..](..) by splitting around links.
        parts = re.split(r"(\[[^\]]*\]\([^)]*\))", line)
        out_lines.append("".join(p if p.startswith("[") and "](" in p else MOVE_RE.sub(replace, p) for p in parts))
    return "\n".join(out_lines), unmatched


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
