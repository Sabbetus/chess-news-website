"""Refresh the Threads long-lived access token before it expires.

Threads long-lived tokens last 60 days and don't auto-renew; Meta allows
refreshing a still-valid one for another 60 days at any point (recommended:
well before expiry, not just before the deadline). Run monthly via
.github/workflows/social-token-refresh.yml -- comfortably inside the
60-day window even if a run or two is missed.

The refreshed token is written back to the THREADS_ACCESS_TOKEN repo
secret via the GitHub CLI, using a separate fine-grained PAT
(SECRETS_ADMIN_TOKEN) -- the default GITHUB_TOKEN used by our other
workflows cannot write repo secrets, by GitHub's own design.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request


def refresh_token(current_token: str) -> str:
    url = "https://graph.threads.net/refresh_access_token?" + urllib.parse.urlencode(
        {"grant_type": "th_refresh_token", "access_token": current_token}
    )
    with urllib.request.urlopen(url) as response:
        payload = json.loads(response.read())
    return payload["access_token"]


def write_github_secret(repo: str, name: str, value: str) -> None:
    subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo, "--body", value],
        check=True,
    )


def main() -> None:
    current_token = os.environ["THREADS_ACCESS_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]

    new_token = refresh_token(current_token)
    write_github_secret(repo, "THREADS_ACCESS_TOKEN", new_token)
    print("Threads access token refreshed and written back to repo secrets.")


if __name__ == "__main__":
    main()
