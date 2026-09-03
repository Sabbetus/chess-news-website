"""
AI drafting: for each item in data/selected.json, calls Claude (Sonnet 5) to
write a companion piece, then writes a Markdown file into
src/content/articles/ with reviewStatus: "draft" in its frontmatter --
nothing here ever sets reviewStatus to "published" directly; that only
happens when a human approves and merges the PR (see the pipeline workflow).

Every article carries two independent pieces of metadata:
  - continent: the site's primary browsing category (europe/asia/
    north-america/south-america/africa/oceania/global). Calendar aggregate
    items already know theirs from ingestion; for news items the model
    infers it from the story content, falling back to "global" when no
    single continent fits.
  - lens: the analytical angle the piece is written through -- shapes the
    prompt, shown on-site as a secondary label, not the primary category.
    "tournament-db" is reserved for calendar aggregates (forced, not
    chosen); news items get one of four lenses (drama, historical-parallel,
    money-angle, community-pulse), picked by the model as whichever best
    fits that specific story.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from continents import CONTINENT_SLUGS

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SELECTED_PATH = DATA_DIR / "selected.json"
ARTICLES_DIR = ROOT / "src" / "content" / "articles"

MODEL = "claude-sonnet-5"

CALENDAR_KINDS = {"calendar-biggest", "calendar-comingup"}

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

# The four lenses a news item can be drafted through -- the model picks
# whichever fits the specific story best (see NEWS_SYSTEM_PROMPT).
LENS_OPTIONS = {
    "drama": (
        "Drama angle: lean into any scandal, controversy, or conflict in the "
        "story -- add color and reasonable speculation about motives, stakes, "
        "and fallout, the way a sharp opinion columnist would. Only pick this "
        "lens when the story actually has a scandal/conflict/controversy "
        "element to work with -- don't manufacture drama that isn't there."
    ),
    "historical-parallel": (
        "Historical parallel: ground the story against chess history -- a "
        "similar record, controversy, or milestone from the past, and what "
        "changed (or didn't) between then and now. Only pick this lens when a "
        "genuine, specific historical parallel exists -- not a vague "
        "'chess has always had drama' gesture."
    ),
    "money-angle": (
        "Money angle: analyze the story through prize funds, sponsorship, "
        "appearance fees, or the broader economics of the event/players "
        "involved -- what it costs, who's paying, what it signals about where "
        "money is moving in chess. Only pick this lens when there's a real "
        "financial angle to dig into."
    ),
    "community-pulse": (
        "Community pulse: characterize how players, streamers, and fans are "
        "actually reacting to this story -- the range of takes, where "
        "opinion splits, what's getting argued about. Do not invent specific "
        "quotes or usernames; characterize the reaction in general terms "
        "grounded in what's plausible for a story like this."
    ),
}

CONTINENT_OPTIONS = "europe, asia, north-america, south-america, africa, oceania, global"

NEWS_SYSTEM_PROMPT = f"""You are writing for a small, curated chess news site. Every \
piece is a companion analysis to a linked source article -- never a reworded \
summary of the source. Add genuine analysis and context a casual reader wouldn't \
get from the source alone. Be accurate: never invent facts, quotes, or statistics \
not present in the source material given to you. If you are not confident about a \
detail, omit it rather than guess.

First, pick the single best-fitting lens for THIS story from these options:
{chr(10).join(f"- {name}: {desc}" for name, desc in LENS_OPTIONS.items())}

Then pick the single most relevant continent for this story from: {CONTINENT_OPTIONS}. \
Use "global" only when no single continent genuinely fits (e.g. a story about \
international chess governance or an online-only event with no regional angle) -- \
prefer picking a real continent whenever the story has any regional anchor \
(a player's federation, a tournament's location, etc.).

Respond with ONLY a JSON object (no markdown fences, no commentary) with these \
exact keys:
{{
  "lens": "one of: {', '.join(LENS_OPTIONS.keys())}",
  "continent": "one of: {CONTINENT_OPTIONS}",
  "title": "a clear, specific headline for this companion piece (not the source's title verbatim)",
  "bodyMarkdown": "the full article body in Markdown, 300-600 words",
  "socialCopy": "a single short social post (under 260 characters) teasing the piece, no hashtags spam, at most one relevant hashtag"
}}"""

AGGREGATE_SYSTEM_PROMPT = """You are writing for a small, curated chess news site. \
This piece is original reporting from the site's own tournament database, not \
commentary on someone else's article. Be accurate: never invent facts or figures \
not present in the tournament data given to you. If you are not confident about a \
detail, omit it rather than guess.

Respond with ONLY a JSON object (no markdown fences, no commentary) with these \
exact keys:
{
  "title": "a clear, specific headline for this piece (not a generic restatement)",
  "bodyMarkdown": "the full article body in Markdown, 300-600 words",
  "socialCopy": "a single short social post (under 260 characters) teasing the piece, no hashtags spam, at most one relevant hashtag"
}"""


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80].rstrip("-")


def build_user_prompt(item: dict) -> str:
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
    is_aggregate = item["kind"] in CALENDAR_KINDS
    system_prompt = AGGREGATE_SYSTEM_PROMPT if is_aggregate else NEWS_SYSTEM_PROMPT
    user_prompt = build_user_prompt(item)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(f"No text content returned for: {item['title']}")

    parsed = parse_response("".join(text_blocks))

    if is_aggregate:
        lens = "tournament-db"
        continent = CONTINENT_SLUGS[item["continentCode"]]
    else:
        lens = parsed["lens"]
        if lens not in LENS_OPTIONS:
            raise ValueError(f"Model returned unknown lens {lens!r} for: {item['title']}")
        continent = parsed["continent"]
        if continent not in CONTINENT_SLUGS.values() and continent != "global":
            raise ValueError(f"Model returned unknown continent {continent!r} for: {item['title']}")

    slug = slugify(parsed["title"])
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.md"

    frontmatter = {
        "title": parsed["title"],
        "publishDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sourceName": item["sourceName"],
        "sourceUrl": item["sourceUrl"],
        "lens": lens,
        "continent": continent,
        "selectionScore": item["selectionScore"],
        "reviewStatus": "draft",
        "socialCopy": parsed["socialCopy"],
    }
    if is_aggregate:
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
