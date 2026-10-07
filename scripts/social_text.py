"""Social copy must not contain a bare domain like "Chess.com": Facebook
and X turn it into a link and show that site's preview card instead of
ours (user's call, 2026-10-07). Written as "Chesscom" instead."""

import re

_DOMAIN_RE = re.compile(r"\bchess\.com\b", re.IGNORECASE)


def delink(text: str) -> str:
    return _DOMAIN_RE.sub(lambda m: m.group(0).replace(".", ""), text or "")
