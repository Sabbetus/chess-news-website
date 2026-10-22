"""Event pages follow our own final results (user's rule, 2026-10-22).

When a drafted piece reports the final result of an event that has a page in
src/content/events/, the drafter fills @@EVENT_RESULT@@; draft.py records it
as the article's `eventResult` and this module adds the winner to the event
page in the same draft PR. tests/test_pipeline_regressions.py then checks
every published article's eventResult against its event page, so a missed
or mismatched update fails the tests instead of going unnoticed.
"""

import json
import re
from pathlib import Path

EVENTS_DIR = Path(__file__).resolve().parent.parent / "src" / "content" / "events"


def event_pages() -> dict[str, str]:
    """slug -> event name, for published event pages."""
    pages = {}
    for path in sorted(EVENTS_DIR.glob("*.md")):
        text = path.read_text()
        name = re.search(r'^name:\s*"(.*?)"', text, re.MULTILINE)
        if name and re.search(r'^reviewStatus:\s*"published"', text, re.MULTILINE):
            pages[path.stem] = name.group(1)
    return pages


def instruction() -> str:
    listing = "\n".join(f"{slug}: {name}" for slug, name in event_pages().items())
    return (
        "Only when this piece reports the FINAL result of a whole edition of one of the events "
        "below (the overall winner is decided -- not a round report, not one section of a "
        "multi-section event, not a qualifier or side event), write one line:\n"
        "slug | year of the edition | winner\n"
        "with the event's slug from this list, the edition's year as the event itself numbers "
        "it, and the winner's full name (a team's name for a team event; several names "
        "separated by \"; \" only for an officially shared title). Otherwise leave this field "
        "empty.\n" + listing
    )


def parse(text: str | None) -> dict | None:
    """{"event", "year", "winners"} from the drafter's line, or None."""
    line = next((l.strip() for l in (text or "").splitlines() if l.count("|") == 2), "")
    if not line:
        return None
    slug, year, winners = (part.strip() for part in line.split("|"))
    names = [w.strip() for w in winners.split(";") if w.strip()]
    if slug not in event_pages() or not re.fullmatch(r"\d{4}", year) or not names:
        return None
    return {"event": slug, "year": int(year), "winners": names}


def frontmatter_line(result: dict) -> str:
    return (
        f'eventResult: {{ event: "{result["event"]}", year: {result["year"]}, '
        f"winners: {json.dumps(result['winners'], ensure_ascii=False)} }}"
    )


def page_winners(slug: str) -> dict[int, list[str]]:
    text = (EVENTS_DIR / f"{slug}.md").read_text()
    out = {}
    for m in re.finditer(r"^\s+- \{ year: (\d{4}), names: \[(.*?)\]", text, re.MULTILINE):
        out[int(m.group(1))] = json.loads(f"[{m.group(2)}]")
    return out


def apply(result: dict, today: str) -> str:
    """Adds the winner to the event page. Returns a one-line note for the PR."""
    path = EVENTS_DIR / f"{result['event']}.md"
    text = path.read_text()
    known = page_winners(result["event"])
    if result["year"] in known:
        if known[result["year"]] == result["winners"]:
            return f"{result['event']}: {result['year']} winner already listed"
        return (
            f"{result['event']}: page lists {', '.join(known[result['year']])} for {result['year']}, "
            f"article says {', '.join(result['winners'])} -- check by hand"
        )
    entry = f"  - {{ year: {result['year']}, names: {json.dumps(result['winners'], ensure_ascii=False)} }}\n"
    text = re.sub(r"^winners:\s*\n", lambda m: m.group(0) + entry, text, count=1, flags=re.MULTILINE)
    # The edition just finished: its dates are no longer the next edition.
    # The quarterly check fills in the next one once it's announced.
    block = re.search(r"^nextEdition:\n(?:[ \t]+.*\n)+", text, re.MULTILINE)
    if block:
        start = re.search(r'^\s+start:\s*"(\d{4})-', block.group(0), re.MULTILINE)
        if start and int(start.group(1)) <= result["year"]:
            text = text.replace(block.group(0), "", 1)
    text = re.sub(r'^updatedDate:\s*".*?"', f'updatedDate: "{today}"', text, count=1, flags=re.MULTILINE)
    path.write_text(text)
    return f"{result['event']}: added {', '.join(result['winners'])} as the {result['year']} winner"
