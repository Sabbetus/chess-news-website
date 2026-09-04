"""One-off backfill: replays the normal daily ingest -> select -> draft cycle
for each past day in a date range, instead of only "today". This exists
because the real pipeline only started running once the site already had a
few days of RSS backlog sitting unprocessed -- this catches that backlog up
to look exactly like it would have if the pipeline had been running each of
those days, rather than dumping the whole window's "best of" as one
unrepresentative burst.

For news items: groups already-fetched RSS candidates by their real
publishedAt date, then re-runs selection.py's exact scoring/caps
independently per day (never across days), and drafts with publishDate set
to that real date -- not the day this script actually runs.

For calendar aggregates: builds whichever CALENDAR_SCHEDULE slot(s) fall
inside the range and haven't been produced yet, exactly like ingest.py would
have on that historical day, using ingest.py's own _build_biggest/
_build_comingup so the tournament-selection logic is identical.

Usage:
  python scripts/backfill.py --start 2026-08-25 --end 2026-09-04 [--dry-run]

--dry-run prints the per-day selection (what would be drafted) without
calling the Claude API or writing any files -- always run this first to
sanity-check the plan and see how many articles/how much cost is involved
before spending anything for real.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ingest
import selection

ROOT = Path(__file__).parent.parent
ARTICLES_DIR = ROOT / "src" / "content" / "articles"
DATA_DIR = ROOT / "data"
SEEN_PATH = DATA_DIR / "seen.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def already_drafted_urls() -> set[str]:
    """Source URLs that already have an article file -- read straight out of
    each file's frontmatter rather than tracked separately, so this can never
    drift from what's actually on disk."""
    urls = set()
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text()
        match = re.search(r'^sourceUrl:\s*"(.*?)"\s*$', text, re.MULTILINE)
        if match:
            urls.add(match.group(1))
    return urls


def item_date(item: dict) -> date | None:
    raw = item.get("publishedAt")
    if not raw:
        return None
    return datetime.fromisoformat(raw).astimezone(timezone.utc).date()


def collect_news_candidates(start: date, end: date, exclude_urls: set[str]) -> dict[date, list[dict]]:
    raw_items: list[dict] = []
    raw_items += ingest.fetch_rss(ingest.CHESS_COM_RSS, "Chess.com", "drama")
    raw_items += ingest.fetch_rss(ingest.FIDE_RSS, "FIDE", "serious")

    by_day: dict[date, list[dict]] = {}
    for item in raw_items:
        if item["sourceUrl"] in exclude_urls:
            continue
        d = item_date(item)
        if d is None or not (start <= d <= end):
            continue
        by_day.setdefault(d, []).append(item)
    return by_day


def select_for_day(items: list[dict]) -> list[dict]:
    """Exact same scoring/caps as selection.py's main(), applied to one day's
    candidates in isolation -- never competing against another day's crop."""
    scored = []
    for item in items:
        if selection.is_promotional(item):
            continue
        total, breakdown = selection.score_item(item)
        if total <= 0:
            continue
        scored.append({**item, "selectionScore": total, "scoreBreakdown": breakdown})

    scored.sort(key=lambda x: x["selectionScore"], reverse=True)
    scored = selection.dedupe_by_topic(scored)

    guaranteed = scored[: selection.MIN_EXTERNAL_ARTICLES]
    extra_pool = scored[selection.MIN_EXTERNAL_ARTICLES : selection.MAX_EXTERNAL_ARTICLES]
    extra = [item for item in extra_pool if item["selectionScore"] >= selection.SCORE_THRESHOLD_FOR_EXTRA]
    return guaranteed + extra


def collect_calendar_slots(start: date, end: date) -> list[tuple[date, dict]]:
    """Every CALENDAR_SCHEDULE slot whose calendar day falls in [start, end],
    built exactly as ingest.py would have on that historical day. Skips a
    slot if its dedupeKey is already in seen.json (already produced)."""
    seen = ingest.load_seen()
    slots = []
    for d in daterange(start, end):
        scheduled = ingest.CALENDAR_SCHEDULE.get(d.day)
        if scheduled is None:
            continue
        kind, code = scheduled
        item = ingest._build_biggest(code, d) if kind == "calendar-biggest" else ingest._build_comingup(code, d)
        if item is None:
            continue
        if ingest.dedupe_key(item) in seen:
            continue
        slots.append((d, item))
    return slots


_SIGNIFICANT_WORD = re.compile(r"[a-z]{4,}")
_TOPIC_STOPWORDS = {
    "chess", "wins", "2026", "grand", "tour", "with", "from", "over", "into",
    "world", "champion", "championship", "title", "titled", "tuesday",
    "final", "finals", "prize", "player", "players", "news", "view", "match",
    "matches", "rivalry", "renew", "continues", "unrivalled", "dominance",
    "coasts", "gets", "other", "coaches", "special", "edition", "signs",
    "joins", "results", "list", "published", "decisions", "meeting",
    "council", "announcing", "announces", "official", "officially",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}


def _topic_words(item: dict) -> set[str]:
    """URL slugs are a more reliable topic signal than headlines -- outlets
    editorialize titles differently ("Wins 2026 Grand Chess Tour, Wesley So
    Clinches 3rd" vs. "Rameshbabu wins Grand Chess Tour 2026") but a slug is
    a plain, literal restatement of what the story is about
    (praggnanandhaa-wins-2026-grand-chess-tour vs.
    praggnanandhaa-rameshbabu-wins-grand-chess-tour-2026 -- much more
    overlap). Use both the slug and the title so a match on either counts."""
    slug = re.sub(r"^https?://[^/]+/?", "", item.get("sourceUrl", "")).rstrip("/")
    slug = slug.rsplit("/", 1)[-1]
    text = f"{slug} {item.get('title', '')}"
    return set(_SIGNIFICANT_WORD.findall(text.lower())) - _TOPIC_STOPWORDS


def dedupe_across_days(plan: list[tuple[date, dict]]) -> list[tuple[date, dict]]:
    """selection.dedupe_by_topic() only ever runs within a single day's
    candidates, same as the real pipeline -- fine for normal daily runs, but
    a backfill spanning many days will otherwise happily draft the same
    story twice a day apart just because a second outlet covered it later
    (e.g. Chess.com on day N, FIDE repeating it on day N+1). Titles for the
    same event often don't even share a prefix (compare "Praggnanandhaa
    Wins 2026 Grand Chess Tour, Wesley So Clinches 3rd" against
    "Praggnanandhaa Rameshbabu wins Grand Chess Tour 2026"), so this
    compares significant-word overlap rather than a literal prefix match.
    Keeps only the first (earliest-dated) occurrence of each topic across
    the whole plan. Calendar aggregates are exempt -- they're never the
    same topic twice."""
    seen_word_sets: list[set[str]] = []
    result = []
    for d, item in plan:
        if item["kind"] not in {"calendar-biggest", "calendar-comingup"}:
            words = _topic_words(item)
            # Any shared significant word (after stopword removal, so this
            # is proper nouns / distinctive terms, not generic chess-news
            # vocabulary) is treated as the same topic -- two stories about
            # different things essentially never share a specific player
            # name or event name by coincidence at this volume.
            is_dupe = any(words & prior for prior in seen_word_sets)
            if is_dupe:
                continue
            seen_word_sets.append(words)
        result.append((d, item))
    return result


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    exclude_urls = already_drafted_urls()
    news_by_day = collect_news_candidates(start, end, exclude_urls)
    calendar_slots = collect_calendar_slots(start, end)

    plan: list[tuple[date, dict]] = []
    for d in daterange(start, end):
        for item in select_for_day(news_by_day.get(d, [])):
            plan.append((d, item))
    plan += calendar_slots
    plan.sort(key=lambda pair: pair[0])
    plan = dedupe_across_days(plan)

    print(f"Backfill plan for {start} .. {end}: {len(plan)} article(s)\n")
    for d, item in plan:
        score = item.get("selectionScore", "-")
        print(f"  {d}  [{score:>3}]  {item['kind']:<18}  {item['sourceName']:<24}  {item['title']}")

    if args.dry_run:
        print("\nDry run -- nothing drafted, nothing written.")
        return

    if not plan:
        print("\nNothing to draft.")
        return

    import anthropic
    from draft import draft_one

    client = anthropic.Anthropic()
    seen = ingest.load_seen()
    written = []
    for d, item in plan:
        try:
            path = draft_one(client, item, publish_date=d.isoformat())
            written.append(path)
            print(f"Drafted: {path.relative_to(ROOT)}")
            if item["kind"] in {"calendar-biggest", "calendar-comingup"}:
                seen.add(ingest.dedupe_key(item))
        except Exception as exc:  # noqa: BLE001 -- one bad draft shouldn't kill the run
            print(f"FAILED to draft '{item['title']}': {exc}", file=sys.stderr)

    ingest.save_seen(seen)
    print(f"\nWrote {len(written)}/{len(plan)} draft(s).")


if __name__ == "__main__":
    main()
