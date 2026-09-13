"""
Fetches last-7-days pageview counts from Google Analytics 4 for
last-7-days-published articles, ranks them, and writes the top few to
data/popular.json for the homepage's "Most Popular" panel (see
src/pages/index.astro).

Eligibility window matches the traffic window deliberately: an article
published outside the last 7 days can never appear here, even if it
somehow has more lifetime views than everything currently eligible.

Best-effort like images.py's photo search: any failure (missing
credentials, a network error, GA4 down) leaves data/popular.json exactly
as it was -- the homepage keeps showing the last successfully-fetched
list rather than going blank. Only a genuinely successful fetch that
finds zero qualifying views (real, current data) writes an empty list,
which the homepage then correctly shows as "Coming soon."
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
ARTICLES_DIR = ROOT / "src" / "content" / "articles"
POPULAR_PATH = ROOT / "data" / "popular.json"

WINDOW_DAYS = 7
MAX_ENTRIES = 4

GA4_API_URL = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def eligible_articles() -> dict[str, str]:
    """slug -> title for every non-recap article published in the last
    WINDOW_DAYS days."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=WINDOW_DAYS)
    out = {}
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
        out[path.stem] = title.group(1)
    return out


def _get_access_token() -> str:
    # Imported here, not at module level: only needed on the real-auth
    # path, so a dev/test run with no GCP auth set up never needs it.
    #
    # No service-account JSON key involved -- the org's policy blocks
    # creating those entirely. Instead, deploy.yml's "Authenticate to
    # Google Cloud" step (google-github-actions/auth) exchanges GitHub's
    # own OIDC token for short-lived Google credentials via Workload
    # Identity Federation and writes them to Application Default
    # Credentials, which google.auth.default() picks up automatically
    # here -- nothing GCP-secret-shaped ever touches disk or a GitHub
    # secret except a provider path and a service account email, neither
    # of which is itself a usable credential on its own.
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=GA4_SCOPES)
    credentials.refresh(Request())
    return credentials.token


_SLUG_FROM_PATH = re.compile(r"^/articles/([^/?]+)/?")


def fetch_pageviews(property_id: str, token: str) -> dict[str, int]:
    """slug -> pageviews in the last WINDOW_DAYS days, for every
    /articles/ path GA4 reports traffic for -- not yet filtered to this
    site's current eligibility list, the caller does that."""
    payload = {
        "dateRanges": [{"startDate": f"{WINDOW_DAYS}daysAgo", "endDate": "today"}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": "screenPageViews"}],
        "dimensionFilter": {
            "filter": {
                "fieldName": "pagePath",
                "stringFilter": {"matchType": "BEGINS_WITH", "value": "/articles/"},
            }
        },
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 100,
    }
    response = requests.post(
        GA4_API_URL.format(property_id=property_id),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    views_by_slug: dict[str, int] = {}
    for row in data.get("rows", []):
        path = row["dimensionValues"][0]["value"]
        match = _SLUG_FROM_PATH.match(path)
        if not match:
            continue
        views = int(row["metricValues"][0]["value"])
        slug = match.group(1)
        # A slug can appear as more than one GA4 row (trailing-slash or
        # query-string variants) -- sum rather than overwrite, so a
        # split doesn't quietly undercount an article's real traffic.
        views_by_slug[slug] = views_by_slug.get(slug, 0) + views
    return views_by_slug


def main() -> None:
    property_id = os.environ.get("GA4_PROPERTY_ID")
    if not property_id:
        print("GA4_PROPERTY_ID not configured -- leaving data/popular.json untouched.", file=sys.stderr)
        return

    try:
        token = _get_access_token()
        views_by_slug = fetch_pageviews(property_id, token)
    except Exception as exc:  # noqa: BLE001 -- any failure here must leave the last known-good list in place, never wipe it
        print(f"GA4 fetch failed, leaving data/popular.json untouched: {type(exc).__name__}: {exc}", file=sys.stderr)
        return

    eligible = eligible_articles()
    ranked = sorted(
        (
            {"slug": slug, "title": eligible[slug], "views": views}
            for slug, views in views_by_slug.items()
            if slug in eligible
        ),
        key=lambda e: e["views"],
        reverse=True,
    )[:MAX_ENTRIES]

    POPULAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    POPULAR_PATH.write_text(json.dumps(ranked, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(ranked)} popular article(s) to {POPULAR_PATH.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
