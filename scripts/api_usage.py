"""Record Claude API token usage per pipeline run, for the PR description.

`track(client)` wraps a client's messages.create so every call appends its
model and usage to the JSONL file named by the API_USAGE_LOG environment
variable (set by the workflows to a per-run temp file; unset locally, in
which case nothing is recorded). `python scripts/api_usage.py` prints a
Markdown summary of that file for the PR body.
"""

import json
import os
import sys
from collections import defaultdict

# USD per million tokens: input, output, cache write (5 min), cache read.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
}
DEFAULT_PRICE = PRICES["claude-sonnet-5-5"]


def _log_path() -> str | None:
    return os.environ.get("API_USAGE_LOG") or None


def _record(response) -> None:
    path = _log_path()
    usage = getattr(response, "usage", None)
    if not path or usage is None:
        return
    row = {
        "model": getattr(response, "model", ""),
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "script": os.path.basename(sys.argv[0]),
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # usage tracking must never break a run


def track(client):
    """Wrap client.messages.create in place; returns the same client."""
    original = client.messages.create

    def create(*args, **kwargs):
        response = original(*args, **kwargs)
        _record(response)
        return response

    client.messages.create = create
    return client


def _cost(row: dict) -> float:
    model = row["model"]
    price = next((p for m, p in PRICES.items() if model.startswith(m)), DEFAULT_PRICE)
    return (
        row["input"] * price[0]
        + row["output"] * price[1]
        + row["cache_write"] * price[2]
        + row["cache_read"] * price[3]
    ) / 1_000_000


def summary(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
    except OSError:
        return ""
    if not rows:
        return ""
    by_script = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cost": 0.0})
    for r in rows:
        s = by_script[r.get("script", "?")]
        s["calls"] += 1
        s["input"] += r["input"] + r["cache_write"] + r["cache_read"]
        s["output"] += r["output"]
        s["cost"] += _cost(r)
    lines = [
        "**API usage this run**",
        "",
        "| Step | Calls | Input tokens | Output tokens | Cost |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, s in sorted(by_script.items()):
        lines.append(f"| {name} | {s['calls']} | {s['input']:,} | {s['output']:,} | ${s['cost']:.3f} |")
    total = sum(s["cost"] for s in by_script.values())
    calls = sum(s["calls"] for s in by_script.values())
    lines.append(f"| **Total** | {calls} | | | **${total:.2f}** |")
    lines.append("")
    lines.append("Output tokens include thinking. Prices: Sonnet 5.5 list rates, see scripts/api_usage.py.")
    return "\n".join(lines)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else _log_path()
    if path:
        print(summary(path))
