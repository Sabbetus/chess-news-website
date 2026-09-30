"""Cross-day duplicate check: drops a candidate that reports a news event one
of our own recently published articles already covered.

selection.py's merge_duplicate_stories only compares candidates within one
day's pool, and seen.json only tracks URLs -- so when a second outlet
reports an event days after the first (caught live, 2026-09-29: Chess.com's
write-up of the Total Chess field announcement, four days after we'd
published FIDE's), the late write-up looks brand new and gets drafted as a
near-duplicate.

A name-overlap heuristic (the kind _is_same_story uses within a day) can't
safely do this across days: a recurring event like the weekly Bullet Brawl
shares the same names and event vocabulary every single week, so name
overlap would drop each new week's genuinely new result as a "repeat" of
the last. Telling "same announcement, reported late" from "same event
series, new result" takes actually reading the two, so this asks a model,
once per run, over titles + short summaries only.

Before any of that, a candidate whose URL is already the source (main or
additional) of a recently published article is dropped outright -- no model
needed. Caught live, 2026-09-30: ChessBase's Uzbekistan winners' interview
came back a day after we'd published it under a headline ("The
Anti-Motivator and the Silent Killer") that gave the title comparison
nothing to match on.

Fails open everywhere: a missing API key, an API error, or an unparseable
answer keeps every candidate. A duplicate slipping through costs one
reviewable draft; a wrongly dropped story costs a story nobody sees.
"""

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARTICLES_DIR = Path(__file__).parent.parent / "src" / "content" / "articles"

# Same model as draft.py's MODEL -- kept in sync by hand because draft.py
# imports selection.py, so selection.py (and this module) can't import it back.
COVERAGE_MODEL = "claude-sonnet-5-5"

LOOKBACK_DAYS = 7
MAX_CANDIDATES_CHECKED = 20
CANDIDATE_SUMMARY_CHARS = 600

SYSTEM_PROMPT = """\
You are the duplicate-story editor for a chess news site. You are given \
(1) articles the site published in the last week and (2) today's candidate \
stories from outside outlets. Identify each candidate that reports the SAME \
specific news event as a published article -- the same announcement, the \
same result, the same incident -- just written up by another outlet or on a \
later day.

Do NOT flag a candidate for merely sharing a topic, a player, a tournament, \
or a recurring event with a published article. A new round of the same \
tournament, a new week of a weekly event (a new Bullet Brawl winner), a \
follow-up development, or a different angle on a shared subject is a \
different story. When unsure, do not flag it -- a missed duplicate is \
cheap, a wrongly dropped story is not.

Answer with only a JSON object: {"already_covered": [{"candidate": <number>, \
"published_title": "<exact title of the matching published article>", \
"reason": "<one short sentence>"}]}. Use an empty list when nothing matches."""


def recent_published(today: datetime | None = None) -> list[dict]:
    today = (today or datetime.now(timezone.utc)).date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    entries = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if 'reviewStatus: "published"' not in text:
            continue
        title = re.search(r'^title:\s*"(.*?)"\s*$', text, re.M)
        date = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"\s*$', text, re.M)
        if not title or not date:
            continue
        if datetime.strptime(date.group(1), "%Y-%m-%d").date() < cutoff:
            continue
        social = re.search(r'^socialCopy:\s*"(.*)"\s*$', text, re.M)
        urls = {_norm_url(u) for u in re.findall(r'^\s*(?:-\s*)?sourceUrl:\s*"(.*?)"\s*$', text, re.M)}
        entries.append(
            {"title": title.group(1), "date": date.group(1), "summary": social.group(1) if social else "", "urls": urls}
        )
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def _norm_url(url: str) -> str:
    return url.strip().split("#")[0].split("?")[0].rstrip("/").lower().replace("http://", "https://")


def drop_same_url(scored: list[dict], published: list[dict]) -> list[dict]:
    """Drop any news candidate whose own URL is already a source of a
    published article. Exact matching only, so it can never catch a
    different story by mistake."""
    by_url = {u: entry["title"] for entry in published for u in entry.get("urls", ())}
    kept = []
    for item in scored:
        title = by_url.get(_norm_url(item.get("sourceUrl", ""))) if item["kind"] == "news" else None
        if title:
            print(f"  Dropping already-covered story: {item['sourceName']}: {item['title']}")
            print(f"      already published as '{title}': same source URL")
            continue
        kept.append(item)
    return kept


def _build_prompt(candidates: list[dict], published: list[dict]) -> str:
    lines = ["PUBLISHED ARTICLES (last week):"]
    for entry in published:
        lines.append(f"- [{entry['date']}] {entry['title']} -- {entry['summary']}")
    lines.append("")
    lines.append("TODAY'S CANDIDATES:")
    for i, item in enumerate(candidates, start=1):
        summary = (item.get("summary") or "")[:CANDIDATE_SUMMARY_CHARS]
        lines.append(f"{i}. [{item['sourceName']}, {item.get('publishedAt') or 'undated'}] {item['title']} -- {summary}")
    return "\n".join(lines)


def _parse_covered(text: str, count: int) -> dict[int, dict]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in response")
    covered = {}
    for entry in json.loads(text[start : end + 1]).get("already_covered", []):
        number = entry.get("candidate")
        if isinstance(number, int) and 1 <= number <= count:
            covered[number - 1] = entry
    return covered


def drop_already_covered(client, scored: list[dict], published: list[dict] | None = None) -> list[dict]:
    """scored is sorted best-first. Only the top MAX_CANDIDATES_CHECKED
    external candidates are checked (a day selects at most a handful, so
    anything ranked lower is never reached); calendar aggregates are our
    own data, not outlet reporting, and are never checked."""
    published = recent_published() if published is None else published
    scored = drop_same_url(scored, published)
    checked = [item for item in scored if item["kind"] == "news"][:MAX_CANDIDATES_CHECKED]
    if client is None or not checked or not published:
        return scored

    try:
        response = client.messages.create(
            model=COVERAGE_MODEL,
            # Headroom for thinking at low effort, the same lesson as every
            # other call in this pipeline (see verify_claims in draft.py):
            # a tight cap lets thinking eat the whole budget before any text.
            max_tokens=4096,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(checked, published)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        if response.stop_reason == "max_tokens" or not text:
            raise ValueError(f"no usable answer (stop_reason={response.stop_reason!r})")
        covered = _parse_covered(text, len(checked))
    except Exception as exc:  # noqa: BLE001 -- fail open, see module docstring
        print(f"Cross-day duplicate check skipped ({type(exc).__name__}: {exc}) -- keeping all candidates.", file=sys.stderr)
        return scored

    drop_ids = set()
    for index, entry in covered.items():
        item = checked[index]
        print(f"  Dropping already-covered story: {item['sourceName']}: {item['title']}")
        print(f"      already published as '{entry.get('published_title', '?')}': {entry.get('reason', '')}")
        drop_ids.add(id(item))
    return [item for item in scored if id(item) not in drop_ids]
