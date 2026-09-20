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
import subprocess
import sys
import urllib.parse
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
from images import _get, _photo_date

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


def _file_last_commit_time(path: Path) -> datetime | None:
    """UTC timestamp of the most recent commit that touched this file.
    Returns None if git history isn't available for this file (a shallow
    checkout, or any other git failure)."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=True,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None
    ts = result.stdout.strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except ValueError:
        return None


_PUBLISHED_DIFF_RE = re.compile(r'^\+\s*reviewStatus:\s*"published"\s*$', re.M)


def _file_publish_time(path: Path) -> datetime | None:
    """UTC timestamp of the commit that actually flipped this article's
    reviewStatus to "published" -- a proxy for "when did this article
    actually go live" that's immune to later, unrelated edits.

    _file_last_commit_time alone isn't enough: a published article gets
    touched again more often than assumed (caught live: a lens rename, a
    source-link fix, and other bulk edits all bumped already-published
    articles' last-commit timestamp weeks after they actually went live,
    which swept them past the next recap's cutoff and back into its
    coverage a second time). Walking each commit's patch for this file and
    taking the most recent one that actually added a `reviewStatus:
    "published"` line finds the real publish moment regardless of how many
    cosmetic edits came after it. Falls back to the file's last commit
    time when no such diff is found (e.g. a file committed already-
    published, with no draft->published transition to find), and to None
    when git history isn't available at all."""
    try:
        result = subprocess.run(
            ["git", "log", "--follow", "-p", "--format=COMMIT %H %cI", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return _file_last_commit_time(path)

    for block in result.stdout.split("\nCOMMIT ")[0:]:
        block = block[len("COMMIT "):] if block.startswith("COMMIT ") else block
        header, _, patch = block.partition("\n")
        parts = header.split()
        if len(parts) < 2:
            continue
        ts = parts[1]
        if _PUBLISHED_DIFF_RE.search(patch):
            try:
                return datetime.fromisoformat(ts).astimezone(timezone.utc)
            except ValueError:
                continue
    return _file_last_commit_time(path)


def _last_recap_cutoff() -> datetime | None:
    """The publish timestamp (see _file_publish_time) of the most recently
    published recap article -- articles that went live after this point
    haven't been covered by any recap yet, at whatever time of day they
    actually went live. None if there's no prior published recap, or git
    history isn't available."""
    latest: datetime | None = None
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if 'type: "recap"' not in text or 'reviewStatus: "published"' not in text:
            continue
        ts = _file_publish_time(path)
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    return latest


def recent_published_articles(days: int) -> list[dict]:
    """Title, slug, publish date, and a short excerpt for every non-recap
    article published since the last recap actually went out (by commit
    time, not calendar date -- see _last_recap_cutoff), oldest first --
    read straight from the files like draft.py's own published_articles(),
    so a hand-edited or manually-added article is included too. Falls back
    to a flat `days`-day window from now when there's no prior recap to
    anchor to, or git history isn't available at all."""
    cutoff_dt = _last_recap_cutoff()
    if cutoff_dt is not None:
        print(f"Using per-article commit time since the last recap ({cutoff_dt.isoformat()}).", file=sys.stderr)
    else:
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        print(f"No prior recap found -- falling back to the {days}-day window from now.", file=sys.stderr)

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

        commit_ts = _file_publish_time(path)
        if commit_ts is not None:
            if commit_ts <= cutoff_dt:
                continue
        elif pub_date < cutoff_dt.date():
            continue

        body = text.split("---", 2)[-1].strip()
        first_para = next(
            (p.strip() for p in body.split("\n\n") if p.strip() and not p.strip().startswith("#")), ""
        )
        entries.append(
            {
                "slug": path.stem,
                "title": title.group(1),
                "date": date.group(1),
                "excerpt": first_para,
            }
        )

    entries.sort(key=lambda e: e["date"])
    return entries


def all_published_images() -> list[dict]:
    """Every photo already downloaded across the site's entire published
    history (not just this week) -- used to find every existing photo of a
    given subject, regardless of which article originally sourced it.

    Unlike draft.py's RECENT_IMAGE_COOLDOWN (which exists so the homepage
    grid doesn't show the same photo twice to a visitor at once), the
    recap's hero image has no such neighbor to duplicate -- it doesn't
    even appear on the homepage, just its own article page -- so recency
    of use elsewhere is deliberately not a factor here."""
    images = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        image_match = _IMAGE_BLOCK_RE.search(text)
        if not image_match:
            continue
        images.append(
            {
                "src": image_match.group("src"),
                "credit": image_match.group("credit"),
                "sourceUrl": image_match.group("sourceUrl"),
            }
        )
    return images


def _commons_title_from_source_url(source_url: str) -> str | None:
    """"https://commons.wikimedia.org/wiki/File%3AFoo_Bar.jpg" ->
    "File:Foo Bar.jpg", the page title the Commons API expects. Underscores
    become spaces: the API normalizes titles that way in its response
    regardless of which form is requested, so matching against its output
    later requires starting from the same normalized form -- comparing the
    underscored request form against the spaced response form silently
    matched nothing in practice. None for anything that isn't a Commons
    file page (defensive; every image this site sources is one)."""
    path = urllib.parse.urlparse(source_url).path
    title = urllib.parse.unquote(path.rsplit("/wiki/", 1)[-1]).replace("_", " ")
    return title if title.startswith("File:") else None


def _real_photo_dates(source_urls: list[str]) -> dict[str, str]:
    """Commons sourceUrl -> the photo's own DateTimeOriginal (via
    images.py's _photo_date, which deliberately never falls back to an
    upload timestamp -- see its docstring). This is the actual recency
    that matters for picking "the latest photo of this person": when our
    own site downloaded or wrote about it is unrelated to how old the
    photograph itself is."""
    titles_by_url = {u: t for u in source_urls if (t := _commons_title_from_source_url(u))}
    if not titles_by_url:
        return {}
    try:
        data = _get(
            {
                "action": "query",
                "titles": "|".join(titles_by_url.values()),
                "prop": "imageinfo",
                "iiprop": "extmetadata",
            }
        )
    except Exception as exc:  # noqa: BLE001 -- best-effort; caller falls back on a miss
        print(f"  recap image: Commons date lookup failed, falling back: {exc}", file=sys.stderr)
        return {}

    pages = data.get("query", {}).get("pages", {})
    dates_by_title = {}
    for page in pages.values():
        title = page.get("title")
        info_list = page.get("imageinfo")
        if not title or not info_list:
            continue
        dates_by_title[title] = _photo_date(info_list[0].get("extmetadata", {}))

    return {url: dates_by_title[title] for url, title in titles_by_url.items() if title in dates_by_title}


def pick_recap_image(subject: str) -> dict | None:
    """Find every already-downloaded photo of `subject` anywhere in the
    site's history (matched against each photo's Commons credit/sourceUrl,
    which reliably carries the subject's name even when the locally-saved
    file was renamed to an article slug) and return the one with the most
    recent real-world photo date, per Wikimedia's own metadata -- NOT
    whichever of our own articles happened to download it most recently,
    which says nothing about how old the photograph actually is. `src`
    (e.g. "./_images/Foo.webp") is a plain relative path resolved by
    Astro's image() schema helper from the entry file's own directory --
    since every article lives in the same src/content/articles/
    directory, the recap can point at the exact same already-downloaded
    file with no new download or license lookup.

    Matches on the full subject name first, falling back to just the last
    word (surname) -- Commons credit lines don't follow one fixed format,
    and a surname-only match is still a correct match for a chess figure,
    who is essentially never confused with someone else sharing only a
    first name in this corpus."""
    if not subject:
        return None
    candidates = all_published_images()

    def matches(img: dict, needle: str) -> bool:
        haystack = f"{img['credit']} {img['sourceUrl']}".lower()
        return needle.lower() in haystack

    found = [img for img in candidates if matches(img, subject)]
    if not found:
        last_word = subject.strip().split()[-1] if subject.strip() else ""
        if last_word:
            found = [img for img in candidates if matches(img, last_word)]
    if not found:
        return None
    if len(found) == 1:
        best = found[0]
    else:
        real_dates = _real_photo_dates([img["sourceUrl"] for img in found])
        # Missing metadata sorts as unknown/oldest ("0000-00-00"), same
        # convention as images.py's own _photo_date -- never lets a photo
        # with no confirmed date win over one that's actually dated.
        best = max(found, key=lambda img: real_dates.get(img["sourceUrl"], "0000-00-00"))

    return {"src": best["src"], "credit": best["credit"], "sourceUrl": best["sourceUrl"]}


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
@@IMAGE_SUBJECT@@
the ONE real person (or, failing that, organization/event) THIS recap's own headline is \
actually about -- e.g. "Magnus Carlsen", not "Magnus Carlsen and Ian Nepomniachtchi" and \
not a made-up description. A separate step searches the site's own photo library for this \
exact name, so it must be a specific full name, not a theme or paraphrase. Leave this \
field completely empty only if the headline genuinely has no single central figure.
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


_ARTICLE_LINK_RE = re.compile(r"/articles/([a-z0-9-]+)/")


def check_recap_links(body_markdown: str, entries: list[dict]) -> list[str]:
    """Every "/articles/<slug>/" link in the drafted body against the real
    slugs it was given -- the model is handed the exact slug for each
    article in build_user_prompt (see the `Link:` line) but can still
    transcribe it wrong when writing the body (caught live: 2026-09-20's
    recap linked a slightly-misremembered slug). Returns the full bad
    links, unmodified -- never auto-fix by fuzzy-matching, since a wrong
    guess here would silently point at the wrong article."""
    real_slugs = {e["slug"] for e in entries}
    found = set(_ARTICLE_LINK_RE.findall(body_markdown))
    bad = found - real_slugs
    return sorted(f"/articles/{slug}/" for slug in bad)


def main() -> None:
    entries = recent_published_articles(RECAP_WINDOW_DAYS)
    if not entries:
        print(f"No articles published in the last {RECAP_WINDOW_DAYS} days -- skipping this week's recap.")
        return

    client = anthropic.Anthropic(max_retries=BATCH_MAX_RETRIES)
    user_prompt = build_user_prompt(entries)

    response = client.messages.create(
        model=MODEL,
        # Was 4096 -- too tight for a week with a lot of published articles
        # to synthesize (caught live: a 19-article week produced a recap
        # that silently cut off mid-sentence, mid-link, 260 words in,
        # because the model's own reasoning ate most of the budget before
        # it got to writing BODY_MARKDOWN -- the exact failure mode
        # documented in draft.py's paragraph fix-up, just not yet guarded
        # against here). Scales with entry count instead of a flat number,
        # same reasoning as that fix.
        max_tokens=max(4096, 512 * len(entries)),
        system=RECAP_SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": user_prompt}],
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks or response.stop_reason == "max_tokens":
        # A max_tokens stop is the truncation failure itself, even when
        # some text did come back (still better to fail loudly than
        # publish a recap that cuts off mid-sentence) -- see the comment
        # above.
        block_types = [b.type for b in response.content]
        print(
            f"FAILED to draft this week's recap: response truncated or empty "
            f"(stop_reason={response.stop_reason!r}, content block types={block_types!r})",
            file=sys.stderr,
        )
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
    image = pick_recap_image((parsed.get("imageSubject") or "").strip())
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

    bad_links = check_recap_links(body_markdown, entries)

    out_path.write_text("\n".join(fm_lines) + "\n\n" + body_markdown.strip() + "\n")
    print(f"Drafted: {out_path.relative_to(ROOT)} (from {len(entries)} article(s))")

    lines = [f"Drafted this week's recap from {len(entries)} article(s)."]
    if offenders:
        spots = ", ".join(f"#{i} ({n} words)" for i, n in offenders)
        lines += ["", f"**Paragraph(s) over the style-guide word ceiling:** {spots}"]
    if bad_links:
        lines += [
            "",
            "**Broken article link(s) -- slug doesn't match any given article, likely a "
            "model transcription error (caught live: 2026-09-20's recap linked "
            "`/articles/freedom-holding-as-fide-s-newest-world-title-backer/` when the "
            "real slug was `freedom-holding-signs-on-as-fide-s-newest-world-title-backer`). "
            "Fix manually before merging:**",
        ]
        lines += [f"- `{link}`" for link in bad_links]
    RUN_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
