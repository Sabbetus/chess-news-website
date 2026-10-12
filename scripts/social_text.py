"""Social copy must not contain a bare domain like "Chess.com": Facebook
and X turn it into a link and show that site's preview card instead of
ours (user's call, 2026-10-07). Written as "Chesscom" instead."""

import re

_DOMAIN_RE = re.compile(r"\bchess\.com\b", re.IGNORECASE)


def delink(text: str) -> str:
    return _DOMAIN_RE.sub(lambda m: m.group(0).replace(".", ""), text or "")


# X allows 280 characters; the posted link counts as 23 and follows a blank
# line, so the copy itself can use at most 255. Caught live 2026-10-12: a
# 268-character Bundesliga post didn't fit.
X_COPY_LIMIT = 255


def fit_for_x(text: str) -> tuple[str, bool]:
    """(copy, ok): copy over the limit is cut back to whole sentences that
    fit; ok is False when even the first sentence is too long, so the run
    report can flag it for a rewrite."""
    text = (text or "").strip()
    if len(text) <= X_COPY_LIMIT:
        return text, True
    kept = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > X_COPY_LIMIT:
            break
        kept = candidate
    return (kept, True) if kept else (text, False)
