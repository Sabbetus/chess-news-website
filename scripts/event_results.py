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


PLAYERS_DIR = EVENTS_DIR.parent / "players"

PLAYER_UPDATE_PROMPT = """You keep a chess news site's player profile up to date. A new \
result has just been published: the player won an edition of an event. Update the \
profile's career highlights and summary text to reflect it, with the smallest possible \
edits:

- Adjust a highlight that the new title changes (a count such as "Three-time U.S. \
Champion" -> "Four-time U.S. Champion", or a year list), or add one short highlight if \
the title is significant and no existing line covers it.
- In the summary text, change only a sentence the new title makes wrong or out of date \
(a count, "his first...", "the reigning..."). Add at most one short sentence, and only \
for a major title.
- Use only the facts given in the result and article below. Change nothing else: same \
wording, same order, same Markdown.

Respond in exactly this format and nothing else:
@@HIGHLIGHTS@@
one highlight per line, without bullets or quotes
@@BODY@@
the full summary text"""


def player_pages() -> dict[str, Path]:
    """Every name and alias of a published player page -> its file."""
    out = {}
    for path in sorted(PLAYERS_DIR.glob("*.md")):
        text = path.read_text()
        if not re.search(r'^reviewStatus:\s*"published"', text, re.MULTILINE):
            continue
        name = re.search(r'^name:\s*"(.*?)"', text, re.MULTILINE)
        block = re.search(r"^aliases:\n((?:\s+- .*\n)+)", text, re.MULTILINE)
        names = [name.group(1)] if name else []
        names += re.findall(r'- "(.*)"', block.group(1)) if block else []
        for n in names:
            out[n] = path
    return out


def update_player_pages(client, model: str, result: dict, article_title: str, article_body: str, today: str) -> list[str]:
    """For each winner with a player page, a small model edit of its
    highlights and summary. Best-effort: a failure is reported, never fatal."""
    notes = []
    pages = player_pages()
    event_name = event_pages().get(result["event"], result["event"])
    for winner in result["winners"]:
        path = pages.get(winner)
        if not path:
            continue
        text = path.read_text()
        fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not fm_match:
            continue
        frontmatter, body = fm_match.group(1), text[fm_match.end():].strip()
        hl_block = re.search(r"^highlights:\n((?:\s+- .*\n?)*)", frontmatter + "\n", re.MULTILINE)
        highlights = re.findall(r'- "(.*)"', hl_block.group(1)) if hl_block else []
        prompt = (
            f"RESULT: {winner} won the {result['year']} {event_name}.\n\n"
            f"ARTICLE: {article_title}\n{article_body[:3000]}\n\n"
            "CURRENT HIGHLIGHTS:\n" + "\n".join(highlights) + f"\n\nCURRENT SUMMARY TEXT:\n{body}"
        )
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                output_config={"effort": "low"},
                system=PLAYER_UPDATE_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            reply = "".join(b.text for b in response.content if b.type == "text")
            new_hl = reply.split("@@HIGHLIGHTS@@", 1)[1].split("@@BODY@@", 1)[0]
            new_body = reply.split("@@BODY@@", 1)[1].strip()
            new_highlights = [l.strip().strip('"').lstrip("-• ").strip() for l in new_hl.splitlines() if l.strip()]
            # A rewrite rather than an edit: keep the page as it was.
            if not new_highlights or not new_body or abs(len(new_body) - len(body)) > max(400, len(body) // 3):
                raise ValueError("reply looks like a rewrite, not a small edit")
        except Exception as exc:  # noqa: BLE001 -- the page can be updated by hand
            notes.append(f"{path.stem}: player page not updated ({type(exc).__name__}) -- update by hand")
            continue
        hl_yaml = "highlights:\n" + "".join(f'  - "{h.replace(chr(34), chr(92) + chr(34))}"\n' for h in new_highlights)
        if hl_block:
            frontmatter = (frontmatter + "\n").replace(hl_block.group(0), hl_yaml, 1).rstrip("\n")
        else:
            frontmatter += "\n" + hl_yaml.rstrip("\n")
        frontmatter = re.sub(r'^updatedDate:\s*".*?"', f'updatedDate: "{today}"', frontmatter, count=1, flags=re.MULTILINE)
        path.write_text(f"---\n{frontmatter}\n---\n\n{new_body}\n")
        notes.append(f"{path.stem}: player page highlights/summary updated for the {result['year']} {event_name}")
    return notes
