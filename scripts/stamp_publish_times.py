"""Stamp `publishedAt` (an ISO timestamp) on every published article that
lacks one, so structured data, the RSS feed and the news sitemap carry the
real publication time instead of midnight UTC (user's call, 2026-11-15).

How the time is found:
  1. From git history when it is there: the commit that flipped
     `reviewStatus` to "published" (the same rule scripts/weekly_recap.py
     uses for "when did this go live").
  2. Otherwise now: the deploy workflow runs this before every build, so a
     freshly published article is stamped by the first deploy after it
     landed on main, a few minutes after it went live.

Idempotent: an article that already has `publishedAt` is left alone.
Run with --dry-run to list what would change.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "src" / "content" / "articles"

_PUBLISHED_RE = re.compile(r'^\+\s*reviewStatus:\s*"published"\s*$', re.M)


def git_publish_time(path: Path) -> datetime | None:
    """The newest commit whose patch adds reviewStatus "published" to this
    file, or its first commit when it was committed already published."""
    try:
        out = subprocess.run(
            ["git", "log", "--follow", "-p", "--format=COMMIT %H %cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, timeout=60, check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None
    blocks = [b for b in out.split("COMMIT ") if b.strip()]
    times = []
    for block in blocks:
        header, _, patch = block.partition("\n")
        parts = header.split()
        if len(parts) < 2:
            continue
        try:
            when = datetime.fromisoformat(parts[1]).astimezone(timezone.utc)
        except ValueError:
            continue
        times.append(when)
        if _PUBLISHED_RE.search(patch):
            # Newest first: the first hit is the latest publish.
            return when
    # No draft -> published transition (committed already published): the
    # file's oldest commit. A shallow clone has one commit for everything,
    # which is no better than "now", so only trust a real history.
    if len(blocks) > 1 and times:
        return times[-1]
    return None


def stamp(path: Path, now: datetime, dry_run: bool) -> str | None:
    text = path.read_text(encoding="utf-8")
    head, sep, rest = text.partition("\n---\n")
    if not text.startswith("---") or not sep:
        return None
    if not re.search(r'^reviewStatus:\s*"published"\s*$', head, re.M):
        return None
    if re.search(r"^publishedAt:", head, re.M):
        return None
    date = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"\s*$', head, re.M)
    if not date:
        return None
    floor = datetime.fromisoformat(date.group(1) + "T00:00:00+00:00")
    # A time is only believed when it falls within a day and a half of the
    # article's own publishDate: older pieces were bulk-edited later (a lens
    # rename, a front-matter change), so their git time is the edit's, not
    # the publication's. Those are left unstamped -- midnight UTC, as before
    # -- rather than given a made-up time.
    plausible = lambda t: t is not None and floor <= t <= floor + timedelta(hours=36)
    when = next((t for t in (git_publish_time(path), now) if plausible(t)), None)
    if when is None:
        return None
    when = when.replace(microsecond=0)
    stamped = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not dry_run:
        new_head = head.replace(date.group(0), f'{date.group(0)}\npublishedAt: "{stamped}"', 1)
        path.write_text(new_head + sep + rest, encoding="utf-8")
    return stamped


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    now = datetime.now(timezone.utc)
    changed = 0
    for path in sorted(ARTICLES.glob("*.md")):
        stamped = stamp(path, now, dry_run)
        if stamped:
            changed += 1
            print(f"{path.stem}: {stamped}")
    print(f"{'Would stamp' if dry_run else 'Stamped'} {changed} article(s).")


if __name__ == "__main__":
    main()
