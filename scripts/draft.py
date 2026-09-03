"""
AI drafting: for each item in data/selected.json, calls Claude (Sonnet 5) to
write a companion piece through one of three lenses, then writes a Markdown
file into src/content/articles/ with reviewStatus: "draft" in its
frontmatter -- nothing here ever sets reviewStatus to "published" directly;
that only happens when a human approves and merges the PR (see
scripts/open_review_pr.py / the pipeline workflow).

Lens selection:
  - calendar-biggest / calendar-comingup items (per-continent monthly
    aggregates from our own tournament data) always use "tournament-db" --
    they ARE our own tournament data, no other lens makes sense. The two
    kinds get different prompt instructions (retrospective ranking vs.
    forward-looking highlights) even though they share the same lens label.
  - news items use "nordic-angle" if the story mentions a Nordic country
    (scored during selection), otherwise "organizer-pov" as the default
    analytical angle for regular news.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SELECTED_PATH = DATA_DIR / "selected.json"
ARTICLES_DIR = ROOT / "src" / "content" / "articles"

MODEL = "claude-sonnet-5"

# Instructions for the two calendar aggregate kinds -- keyed by candidate
# "kind" rather than "lens", since both use the tournament-db lens but need
# very different framing (retrospective ranking vs. forward-looking list).
AGGREGATE_INSTRUCTIONS = {
    "calendar-biggest": (
        "Write an original retrospective piece ranking the biggest tournaments "
        "in this continent last month, grounded entirely in the tournament data "
        "provided (a JSON list, already sorted by players registered, largest "
        "first). This is original reporting from our own database, not "
        "commentary on someone else's article. Cover the top entries by name, "
        "player count, location, and anything else notable (format, rating "
        "requirement) given in the data -- do not invent details not present in "
        "the data. Note that this ranking is limited to tournaments with a "
        "known player count in our data; if the total tracked count is "
        "meaningfully higher than the number ranked, say so plainly rather than "
        "implying the list is exhaustive (e.g. some countries, like the US, "
        "don't reliably report player counts to our sources, so they may be "
        "under-represented here even if they hosted plenty of tournaments)."
    ),
    "calendar-comingup": (
        "Write an original preview piece highlighting notable tournaments "
        "coming up next month in this continent, grounded entirely in the "
        "tournament data provided (a JSON list of highlights, some ranked by "
        "player count, others -- where player counts aren't reliably reported "
        "-- selected as notable by name/format/rating requirement). This is "
        "original reporting from our own database, not commentary on someone "
        "else's article. Cover a handful of the most interesting entries by "
        "name, date, location, and any other notable detail given in the data "
        "-- do not invent details not present in the data. Mention the overall "
        "count of tracked tournaments in the continent that month for context."
    ),
}

LENS_INSTRUCTIONS = {
    "nordic-angle": (
        "Write a companion piece analyzing this story specifically through a "
        "Nordic/regional lens -- most chess news coverage is Anglo-centric, so "
        "highlight what this means for Nordic players, federations, or the Nordic "
        "chess scene specifically. If the story doesn't have an obvious direct "
        "Nordic connection, draw a genuine, non-forced comparison (e.g. how a "
        "similar situation has played out in Nordic chess, or what Nordic "
        "organizers/players could take from it). Do not restate the source "
        "article -- add real analysis."
    ),
    "organizer-pov": (
        "Write a companion piece analyzing this story from the perspective of "
        "someone who actually organizes chess tournaments -- the logistics, "
        "decisions, and tradeoffs a reporter without that experience wouldn't "
        "surface (e.g. arbiting decisions, venue/scheduling implications, "
        "registration or funding angles, what this means operationally for other "
        "organizers). Do not restate the source article -- add real analysis."
    ),
}

SYSTEM_PROMPT = """You are writing for a small, curated chess news site. Every \
piece is a companion analysis to a linked source article (or, for tournament \
previews, original writing from the site's own tournament database) -- never a \
reworded summary of the source. Add genuine analysis and context a casual reader \
wouldn't get from the source alone. Be accurate: never invent facts, quotes, or \
statistics not present in the source material or tournament data given to you. \
If you are not confident about a detail, omit it rather than guess.

Respond with ONLY a JSON object (no markdown fences, no commentary) with these \
exact keys:
{
  "title": "a clear, specific headline for this companion piece (not the source's title verbatim)",
  "bodyMarkdown": "the full article body in Markdown, 300-600 words",
  "socialCopy": "a single short social post (under 260 characters) teasing the piece, no hashtags spam, at most one relevant hashtag"
}"""


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80].rstrip("-")


CALENDAR_KINDS = {"calendar-biggest", "calendar-comingup"}


def pick_lens(item: dict) -> str:
    if item["kind"] in CALENDAR_KINDS:
        return "tournament-db"
    if item.get("scoreBreakdown", {}).get("nordic", 0) > 0:
        return "nordic-angle"
    return "organizer-pov"


def build_user_prompt(item: dict, lens: str) -> str:
    if item["kind"] in CALENDAR_KINDS:
        parts = [
            AGGREGATE_INSTRUCTIONS[item["kind"]],
            "",
            f"Continent: {item['continentName']}",
            f"Month: {item['monthLabel']}",
            f"Total tournaments tracked in this continent this month: {item['totalTracked']}",
            f"Continent page URL (for reference, not required in the body): {item['sourceUrl']}",
            f"Tournament data (JSON list): {json.dumps(item['tournamentData'])}",
        ]
        return "\n".join(parts)

    parts = [
        LENS_INSTRUCTIONS[lens],
        "",
        f"Source title: {item['title']}",
        f"Source URL: {item['sourceUrl']}",
        f"Source name: {item['sourceName']}",
    ]
    if item.get("summary"):
        parts.append(f"Source summary/excerpt: {item['summary']}")
    return "\n".join(parts)


def parse_response(text: str) -> dict:
    text = text.strip()
    # Defensive: strip accidental code fences even though the prompt asks for none.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def draft_one(client: anthropic.Anthropic, item: dict) -> Path:
    lens = pick_lens(item)
    user_prompt = build_user_prompt(item, lens)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(f"No text content returned for: {item['title']}")

    parsed = parse_response("".join(text_blocks))

    slug = slugify(parsed["title"])
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.md"

    frontmatter = {
        "title": parsed["title"],
        "publishDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sourceName": item["sourceName"],
        "sourceUrl": item["sourceUrl"],
        "lens": lens,
        "selectionScore": item["selectionScore"],
        "reviewStatus": "draft",
        "socialCopy": parsed["socialCopy"],
    }
    if item["kind"] in CALENDAR_KINDS:
        # Extra context for reviewers -- not part of the content schema (unknown
        # frontmatter keys are stripped at build time), but visible in the raw
        # file/PR diff, which is where a reviewer actually looks.
        frontmatter["aggregateKind"] = item["kind"]
        frontmatter["continentName"] = item["continentName"]
        frontmatter["monthLabel"] = item["monthLabel"]
        frontmatter["totalTracked"] = item["totalTracked"]

    fm_lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')
            fm_lines.append(f'{key}: "{escaped}"')
        else:
            fm_lines.append(f"{key}: {value}")
    fm_lines.append("---")

    out_path.write_text("\n".join(fm_lines) + "\n\n" + parsed["bodyMarkdown"].strip() + "\n")
    return out_path


def main() -> None:
    if not SELECTED_PATH.exists():
        print("No selected.json found -- run select.py first.")
        sys.exit(1)

    selected = json.loads(SELECTED_PATH.read_text())
    if not selected:
        print("No items selected -- nothing to draft.")
        return

    client = anthropic.Anthropic()

    written = []
    for item in selected:
        try:
            path = draft_one(client, item)
            written.append(path)
            print(f"Drafted: {path.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001 -- one bad draft shouldn't kill the run
            print(f"FAILED to draft '{item['title']}': {exc}", file=sys.stderr)

    print(f"Wrote {len(written)}/{len(selected)} draft(s).")


if __name__ == "__main__":
    main()
