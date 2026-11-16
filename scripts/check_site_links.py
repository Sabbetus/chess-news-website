"""Check every internal link and asset in the built site (dist/).

Run after `npm run build`. Exits non-zero when any page links to an
internal path that the build didn't produce, listing each one with the
page it is on. External links are not fetched (they belong to other sites
and would make the check flaky); in-page "#..." anchors are skipped.
Audit item 12 (2026-11-16): the tests covered the pipeline only, so a
broken internal link or a missing image could ship unnoticed.
"""

from __future__ import annotations

import re
import sys
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit

DIST = Path(__file__).resolve().parent.parent / "dist"
SITE_HOSTS = {"chessherald.com", "www.chessherald.com"}
_ATTR_RE = re.compile(r'\b(?:href|src)\s*=\s*"([^"]*)"', re.I)
_SRCSET_RE = re.compile(r'\bsrcset\s*=\s*"([^"]*)"', re.I)


def targets(html: str) -> list[str]:
    out = [unescape(u) for u in _ATTR_RE.findall(html)]
    for srcset in _SRCSET_RE.findall(html):
        out += [part.strip().split(" ")[0] for part in unescape(srcset).split(",") if part.strip()]
    return out


def resolve(url: str, page: Path) -> Path | None:
    """The dist file a link needs, or None when it isn't ours to check."""
    parts = urlsplit(url)
    if parts.scheme in ("mailto", "tel", "javascript", "data"):
        return None
    if parts.scheme or parts.netloc:
        if parts.netloc.lower() not in SITE_HOSTS:
            return None
    path = unquote(parts.path)
    if not path:
        return None  # "#anchor" or "?query" on the same page
    if path.startswith("/"):
        target = DIST / path.lstrip("/")
    else:
        target = (page.parent / path).resolve()
    if path.endswith("/") or target.is_dir():
        # "/404/" is served from 404.html (the build's flat file for it).
        flat = target.with_name(target.name + ".html") if target.name else target
        return flat if not (target / "index.html").exists() and flat.exists() else target / "index.html"
    return target


def main() -> int:
    if not DIST.is_dir():
        print("dist/ not found -- run `npm run build` first.", file=sys.stderr)
        return 2
    broken: dict[str, set[str]] = {}
    pages = sorted(DIST.rglob("*.html"))
    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        for url in targets(html):
            target = resolve(url, page)
            if target is not None and not target.exists():
                broken.setdefault(url, set()).add(str(page.relative_to(DIST)))
    if broken:
        print(f"{len(broken)} broken internal link(s):")
        for url, where in sorted(broken.items()):
            shown = sorted(where)
            more = f" (+{len(shown) - 3} more)" if len(shown) > 3 else ""
            print(f"  {url}  <- {', '.join(shown[:3])}{more}")
        return 1
    print(f"Checked {len(pages)} pages: no broken internal links.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
