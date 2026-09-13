"""
Weekly Recap: a standalone drafting path, separate from the daily
ingest/select/draft pipeline. Run once a week (Sundays), it gathers every
article The Chess Herald itself published in the last 7 days and asks
Claude for a short roundup linking back to each one -- there is no single
external source here, so it skips ingest.py/selection.py entirely and
writes straight into src/content/articles/ with type: "recap" in its
frontmatter.

reviewStatus starts at "draft" like every other piece; a human still
reviews and merges the PR before it goes live (see the pipeline workflow's
review-PR step, which this script's own workflow mirrors).
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

from draft import (
    ARTICLES_DIR,
    BATCH_MAX_RETRIES,
    MODEL,
    STYLE_GUIDE,
    check_paragraph_lengths,
    fix_long_paragraphs,
    parse_response,
    slugify,
)

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
RUN_REPORT_PATH = DATA_DIR / "weekly-recap-report.md"

RECAP_WINDOW_DAYS = 7


_IMAGE_BLOCK_RE = re.compile(
    r'^image:\s*\n'
    r'\s*src:\s*"(?P<src>[^"]+)"\s*\n'
    r'\s*credit:\s*"(?P<credit>[^"]*)"\s*\n'
    r'\s*sourceUrl:\s*"(?P<sourceUrl>[^"]+)"\s*$',
    re.M,
)


def recent_published_articles(days: int) -> list[dict]:
    """Title, slug, publish date, selection score, image (if any), and a
    short excerpt for every non-recap article published in the last `days`
    days, oldest first -- read straight from the files like draft.py's own
    published_articles(), so a hand-edited or manually-added article is
    included too."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    entries = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if 'reviewStatus: "published"' not in text or 'type: "recap"' in text:
            continue
        title = re.search(r'^title:\s*"(.*?)"\s*$', text, re.M)
        date = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"\s*$', text, re.M)
        if not title or not date:
            continue
        try:
            pub_date = datetime.strptime(date.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if pub_date < cutoff:
            continue

        body = text.split("---", 2)[-1].strip()
        first_para = next(
            (p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")), ""
        )
        score_match = re.search(r"^selectionScore:\s*([\d.]+)\s*$", text, re.M)
        image_match = _IMAGE_BLOCK_RE.search(text)
        entries.append(
            {
                "slug": path.stem,
                "title": title.group(1),
                "date": date.group(1),
                "excerpt": first_para,
                "selectionScore": float(score_match.group(1)) if score_match else 0.0,
                "image": (
                    {
                        "src": image_match.group("src"),
                        "credit": image_match.group("credit"),
                        "sourceUrl": image_match.group("sourceUrl"),
                    }
                    if image_match
                    else None
                ),
            }
        )

    entries.sort(key=lambda e: e["date"])
    return entries


def pick_recap_image(entries: list[dict]) -> dict | None:
    """Reuse the photo from this week's highest-scoring article that
    actually has one -- the recap has no single subject of its own to
    source a new photo for, but the site's article-page layout expects a
    hero image, and one of the week's own articles almost always has a
    usable one already downloaded. `src` (e.g. "./_images/Foo.webp") is a
    plain relative path resolved by Astro's image() schema helper from the
    entry file's own directory -- since every article lives in the same
    src/content/articles/ directory, the recap can point at the exact same
    already-downloaded file with no new download or license lookup."""
    candidates = [e for e in entries if e["image"]]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e["selectionScore"])["image"]


RECAP_SYSTEM_PROMPT = f"""You are writing the Weekly Recap for a small, curated chess news \
site. This is a roundup of stories The Chess Herald itself already published this week -- \
you are not reporting anything new, just summarizing and linking back to pieces that \
already exist. Be accurate: base every sentence only on the excerpt given for each \
article, never invent a detail, score, or outcome that isn't in it.

{STYLE_GUIDE}

FORMAT. Cover every article you're given -- a brief mention, not a full retelling, but \
follow the same paragraph-length target as the style guide above: 2-4 sentences and \
roughly 60 words per paragraph, not 1-2 thin sentences. Where a single article doesn't \
have enough in its excerpt to fill a paragraph on its own, that's exactly when grouping \
with a genuinely related one (a shared theme, tournament, or storyline) belongs -- don't \
leave paragraphs short when a natural pairing exists. Group naturally; don't force a \
grouping that isn't really there, and don't pad an unrelated single-story paragraph with \
invented detail just to hit the word target -- a slightly shorter paragraph beats a \
fabricated one. Every single article must be linked exactly once, using the \
"/articles/<slug>/" path exactly as given, with the anchor text being the fact or \
headline itself, never "read more" or the bare title repeated verbatim.

Open with one short paragraph framing the week as a whole (2-3 sentences, no more) \
before getting into the individual stories -- not a generic "another busy week in \
chess" line, something that actually names the shape of what happened (e.g. which \
theme dominated, how many stories, any throughline). Do not add a closing \
summary paragraph at the end restating what the piece already covered -- end on the \
last story instead.

Respond with ONLY the fields below, each introduced by its marker line exactly as \
shown (@@NAME@@ alone on its own line) -- no markdown fences, no JSON, no commentary \
before, between, or after them:

@@TITLE@@
a headline for this week's recap in the form "Weekly Recap: <the week's actual throughline>" \
(e.g. "Weekly Recap: Rating Shakeups and a Controversial Finish in St. Louis") -- name the \
real theme, not a generic placeholder like "This Week in Chess"
@@SOCIAL_COPY@@
a single short social post (under 260 characters) teasing this week's recap, no hashtag spam, at most one relevant hashtag. Never include a URL or domain name of any kind -- the posting script appends the real article link separately, and a guessed one is always wrong.
@@BODY_MARKDOWN@@
the full recap body in Markdown"""


def build_user_prompt(entries: list[dict]) -> str:
    parts = [f"This week's published articles ({len(entries)} total), in the order published:"]
    for e in entries:
        parts.append("")
        parts.append(f"- Title: {e['title']}")
        parts.append(f"  Link: /articles/{e['slug']}/")
        parts.append(f"  Date: {e['date']}")
        parts.append(f"  Excerpt: {e['excerpt']}")
    return "\n".join(parts)


def main() -> None:
    entries = recent_published_articles(RECAP_WINDOW_DAYS)
    if not entries:
        print(f"No articles published in the last {RECAP_WINDOW_DAYS} days -- skipping this week's recap.")
        return

    client = anthropic.Anthropic(max_retries=BATCH_MAX_RETRIES)
    user_prompt = build_user_prompt(entries)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=RECAP_SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": user_prompt}],
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        print("FAILED to draft this week's recap: no text content returned", file=sys.stderr)
        sys.exit(1)

    parsed = parse_response(text_blocks[-1])

    slug = slugify(parsed["title"])
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.md"

    frontmatter = {
        "title": parsed["title"],
        "type": "recap",
        "publishDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "continent": "global",
        "selectionScore": 0,
        "reviewStatus": "draft",
        "socialCopy": (parsed.get("socialCopy") or "").strip() or parsed["title"],
    }
    image = pick_recap_image(entries)
    if image:
        frontmatter["image"] = image

    fm_lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')
            fm_lines.append(f'{key}: "{escaped}"')
        elif isinstance(value, dict):
            fm_lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                escaped = str(sub_value).replace('"', '\\"')
                fm_lines.append(f'  {sub_key}: "{escaped}"')
        else:
            fm_lines.append(f"{key}: {value}")
    fm_lines.append("---")

    body_markdown = parsed["bodyMarkdown"]
    offenders = check_paragraph_lengths(body_markdown)
    if offenders:
        body_markdown = fix_long_paragraphs(client, body_markdown, offenders)
        offenders = check_paragraph_lengths(body_markdown)

    out_path.write_text("\n".join(fm_lines) + "\n\n" + body_markdown.strip() + "\n")
    print(f"Drafted: {out_path.relative_to(ROOT)} (from {len(entries)} article(s))")

    lines = [f"Drafted this week's recap from {len(entries)} article(s)."]
    if offenders:
        spots = ", ".join(f"#{i} ({n} words)" for i, n in offenders)
        lines += ["", f"**Paragraph(s) over the style-guide word ceiling:** {spots}"]
    RUN_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
