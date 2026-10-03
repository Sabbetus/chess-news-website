"""Move the next queued explainer into the daily draft batch.

Explainers (data/explainers/NN-slug.md) are evergreen pieces written ahead
of time and released one per day so they go through the same PR review as
the news drafts instead of landing all at once. Each run takes the
lowest-numbered file, stamps today's publishDate, gives it a neutral photo
not already in recent use, and writes it to src/content/articles/ as a
draft. Runs after draft.py so the photo check sees today's news drafts.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from draft import ARTICLES_DIR, RUN_REPORT_PATH, used_image_source_urls  # noqa: E402
from images import fallback_image  # noqa: E402

QUEUE_DIR = Path(__file__).resolve().parent.parent / "data" / "explainers"


def release(today: str) -> Path | None:
    queued = sorted(QUEUE_DIR.glob("*.md"))
    if not queued:
        return None
    src = queued[0]
    slug = re.sub(r"^\d+-", "", src.stem)
    dest = ARTICLES_DIR / f"{slug}.md"
    if dest.exists():
        # Already released (e.g. a rerun the same day) -- drop it from the
        # queue rather than overwrite a file that may have been edited.
        src.unlink()
        return None

    text = src.read_text(encoding="utf-8")
    text = text.replace('publishDate: "TBD"', f'publishDate: "{today}"', 1)
    title = re.search(r'^title: "(.*)"$', text, re.M).group(1)
    photo = fallback_image(title, used_image_source_urls())
    if photo and "\nimage:" not in text:
        block = (
            "image:\n"
            f'  src: "{photo["src"]}"\n'
            f'  credit: "{photo["credit"]}"\n'
            f'  sourceUrl: "{photo["sourceUrl"]}"\n'
        )
        head, sep, body = text[3:].partition("\n---\n")
        text = "---" + head + "\n" + block.rstrip("\n") + sep + body

    dest.write_text(text, encoding="utf-8")
    src.unlink()
    return dest


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = release(today)
    if not dest:
        print("No explainer queued for today.")
        return
    left = len(list(QUEUE_DIR.glob("*.md")))
    print(f"Released explainer {dest.name} ({left} left in queue).")
    with RUN_REPORT_PATH.open("a", encoding="utf-8") as f:
        f.write(
            f"\nExplainer released from the queue: `{dest.name}` "
            f"({left} left). Written ahead of time, not from a news source.\n"
        )


if __name__ == "__main__":
    main()
