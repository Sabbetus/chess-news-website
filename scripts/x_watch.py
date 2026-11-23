"""Reactions on X to the day's stories, from a followed list of accounts.

User's call, 2026-11-22: the chief arbiter's open letter answering FIDE's
Total Chess statement was found by hand on X, not by the pipeline. Big
reactions get reposted or quoted by the chess news accounts, so following a
few dozen accounts (data/x-accounts.json) surfaces them even when the person
who posted is otherwise unknown.

How it works:
- fxtwitter (a free third-party X mirror; no paid X API) lists each followed
  account's recent posts. Best effort: a failed account is skipped, and if
  the service is down the drafts simply go without.
- Quotable posts: those by a followed "person", and originals reached
  through a repost or quote (the unknown poster case). Relay and official
  accounts' own posts are leads only -- a relay's paraphrase is not the
  person's words, and an organisation's statement is already a source.
- For each draft, a model keeps up to MAX_ADDS quotable posts that respond to
  the story and writes one attributed sentence for each; the sentence goes in
  as its own paragraph, and the post is quoted right after it
  (inline-tweets.mjs). Relevant leads are listed in the PR report.
- followups() lists new reactions to the last two days' controversy pieces
  in the PR report, for the morning review to judge whether a follow-up
  piece is due (user's call: a separate piece, not additions).
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from tweets import MAX_TEXT_CHARS, MIN_TEXT_CHARS, is_org_handle

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = ROOT / "data" / "x-accounts.json"
ARTICLES_DIR = ROOT / "src" / "content" / "articles"
STATUSES_URL = "https://api.fxtwitter.com/2/profile/{handle}/statuses"
USER_AGENT = "chess-herald-ingest/0.1 (+https://github.com/Sabbetus/chess-news-website)"
REQUEST_TIMEOUT = 20
WINDOW_HOURS = 48
MAX_ADDS = 2
MAX_CANDIDATES = 25
PAUSE_SECONDS = 3  # between accounts: fxtwitter answers bursts with 404s

_cache: dict[str, list[dict]] | None = None


def load_accounts() -> list[dict]:
    try:
        return json.loads(ACCOUNTS_PATH.read_text())["accounts"]
    except (OSError, ValueError, KeyError):
        return []


def _fetch(handle: str) -> list[dict]:
    for attempt in range(2):
        try:
            resp = requests.get(
                STATUSES_URL.format(handle=handle), headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json().get("results") or []
        except (requests.RequestException, ValueError):
            pass
        time.sleep(8 * (attempt + 1))
    return []


def blocked() -> tuple[set[str], list[str]]:
    """Handles and names that get no visibility at all (data/x-accounts.json
    "blocked"; user's call, 2026-11-23)."""
    try:
        b = json.loads(ACCOUNTS_PATH.read_text()).get("blocked") or {}
    except (OSError, ValueError):
        b = {}
    return {h.lower() for h in b.get("handles", [])}, [n.lower() for n in b.get("names", [])]


def is_blocked(handle: str, name: str, text: str) -> bool:
    handles, names = blocked()
    hay = f"{handle} {name} {text}".lower()
    return handle.lower() in handles or any(n in hay for n in names)


def _post(raw: dict, quotable: bool, via: str | None) -> dict | None:
    author = raw.get("author") or {}
    handle = author.get("screen_name") or ""
    text = (raw.get("text") or "").strip()
    if not handle or not raw.get("id") or len(text) < MIN_TEXT_CHARS:
        return None
    if is_blocked(handle, author.get("name") or "", text):
        return None
    ts = raw.get("created_timestamp") or 0
    return {
        "id": str(raw["id"]),
        "url": f"https://x.com/{handle}/status/{raw['id']}",
        "handle": handle,
        "name": author.get("name") or handle,
        "text": text,
        "ts": int(ts),
        "quotable": quotable and not is_org_handle(handle),
        "via": via,
    }


def normalize(results: list[dict], account: dict) -> list[dict]:
    """Posts from one account's list: its own posts, reposted originals and
    quoted originals, each marked quotable or not (see module notes)."""
    kinds = {a["handle"].lower(): a.get("kind") for a in load_accounts()}
    me = account["handle"]
    out = []
    for raw in results:
        quote = raw.get("quote")
        if isinstance(quote, dict) and is_blocked(
            (quote.get("author") or {}).get("screen_name") or "",
            (quote.get("author") or {}).get("name") or "",
            quote.get("text") or "",
        ):
            continue  # a post quoting a blocked author is dropped whole
        author = ((raw.get("author") or {}).get("screen_name") or "").lower()
        own_kind = kinds.get(author)
        # A repost shows the original author: quotable unless that author is
        # a relay/official we follow.
        if author != me.lower():
            p = _post(raw, own_kind in (None, "person"), via=me)
        else:
            p = _post(raw, account.get("kind") == "person", via=None)
        if p:
            out.append(p)
        quote = raw.get("quote")
        if isinstance(quote, dict):
            q_author = ((quote.get("author") or {}).get("screen_name") or "").lower()
            q = _post(quote, kinds.get(q_author) in (None, "person"), via=raw.get("author", {}).get("screen_name"))
            if q:
                out.append(q)
    return out


def all_recent_posts(now: datetime | None = None) -> list[dict]:
    """Every followed account's posts from the last WINDOW_HOURS, fetched once
    per run, deduplicated (a quotable copy wins over a lead copy)."""
    global _cache
    if _cache is None:
        _cache = {}
        for i, account in enumerate(load_accounts()):
            if i:
                time.sleep(PAUSE_SECONDS)
            _cache[account["handle"]] = normalize(_fetch(account["handle"]), account)
        fetched = sum(1 for v in _cache.values() if v)
        print(f"  x watch: posts from {fetched}/{len(_cache)} followed account(s)", file=sys.stderr)
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(hours=WINDOW_HOURS)).timestamp()
    best: dict[str, dict] = {}
    for posts in _cache.values():
        for p in posts:
            if p["ts"] < cutoff:
                continue
            if p["id"] not in best or (p["quotable"] and not best[p["id"]]["quotable"]):
                best[p["id"]] = p
    return sorted(best.values(), key=lambda p: -p["ts"])


_NAME_RE = re.compile(r"\b[A-Z][a-zà-ÿ'-]+(?:[ -][A-Z][a-zà-ÿ'-]+)+")
_COMMON = {"The", "This", "That", "World", "Championship", "Chess", "Round", "Total", "Tour", "Open", "Cup"}


def key_terms(title: str, body: str) -> set[str]:
    """Names in the story: full names and their surnames (lowercase)."""
    terms = set()
    for name in _NAME_RE.findall(f"{title}\n{body}"):
        parts = [w for w in re.split(r"[ ]", name) if w not in _COMMON]
        if len(parts) >= 2:
            terms.add(" ".join(parts).lower())
        if parts and len(parts[-1]) >= 4:
            terms.add(parts[-1].lower())
    return terms


# Top names whose considered opinion on a story may be added even when they
# are not a party to it (user's call, 2026-11-22: "if some of the top names
# comment on it ... it might still be interesting"): the current FIDE top 20
# plus world champions, past and present. Decided here, not by the model.
WORLD_CHAMPIONS = [
    "Magnus Carlsen", "Viswanathan Anand", "Garry Kasparov", "Vladimir Kramnik", "Veselin Topalov",
    "Ruslan Ponomariov", "Rustam Kasimdzhanov", "Ding Liren", "Gukesh", "Anatoly Karpov",
    "Ju Wenjun", "Hou Yifan", "Tan Zhongyi", "Mariya Muzychuk", "Anna Ushenina", "Antoaneta Stefanova",
    "Xie Jun", "Zhu Chen", "Maia Chiburdanidze", "Susan Polgar", "Alexandra Kosteniuk",
]


def _name_tokens(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text) if len(w) >= 3}


def top_names() -> list[set[str]]:
    names = list(WORLD_CHAMPIONS)
    try:
        data = json.loads((ROOT / "data" / "fide-top100.json").read_text())
        names += [pl["name"] for pl in data.get("players", []) if pl.get("rank", 999) <= 20]
    except (OSError, ValueError):
        pass
    return [_name_tokens(n) for n in names]


def is_top_name(post: dict, tops: list[set[str]] | None = None) -> bool:
    """Display name or handle ("DGukesh", "Vachier_Lagrave") matches a top name:
    both words of a two-word name, or the one word of a one-word name."""
    handle = re.sub(r"([a-z])([A-Z])", r"\1 \2", post.get("handle", "")).replace("_", " ")
    mine = _name_tokens(post.get("name", "")) | _name_tokens(handle)
    return any(len(t & mine) >= min(2, len(t)) for t in (tops if tops is not None else top_names()) if t)


def candidates_for(title: str, body: str, posts: list[dict], skip_urls: set[str] = frozenset()) -> list[dict]:
    terms = key_terms(title, body)
    if not terms:
        return []
    scored = []
    for p in posts:
        if p["url"] in skip_urls:
            continue
        hay = f"{p['text']} {p['name']}".lower()
        hits = sum(1 for t in terms if t in hay)
        if hits:
            scored.append((hits, p))
    # Quotable posts first: an organiser's congratulations must not crowd
    # out a person's statement.
    scored.sort(key=lambda hp: (not hp[1]["quotable"], -hp[0], -hp[1]["ts"]))
    return [p for _, p in scored[:MAX_CANDIDATES]]


def paragraphs(body: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]


# User's call, 2026-11-22: not every opinion on a topic belongs in the
# article. Only a party to the story giving their side, or a new fact or
# decision, is added; everyone else's opinion is listed for the review.
_PICK_PROMPT = """You choose posts on X to add to a chess news article. The bar is \
high: an added post must move the story, not just comment on it.

You get the article (numbered paragraphs) and recent posts from X. A post may be \
ADDED only if all of these hold:
- it is QUOTABLE;
- its author is a PARTY to this story: a player, official, arbiter, organiser or \
body the article is about, someone whose decision or conduct the article reports, \
or someone the article says was accused or criticised;
- it is substantive: it answers an accusation, gives that party's own side or \
explanation, or announces a decision or a new fact the article lacks.
One exception: you may also add at most ONE opinion by a post marked TOP NAME \
(a world champion or a current top-20 player) who is not a party, but only if it \
is a considered position on this story -- an argument, a proposal, or a clear \
stance with a reason. A jab, a one-liner, sarcasm or a vague reaction does not \
count. Its sentence must present it as that person's view.
Never add an opinion by anyone else, however well known; never add \
congratulations, promotion or live commentary. Add at most {max_adds} in all. \
Adding nothing is the normal answer.

For each addition write ONE sentence for the article, in its style, that \
attributes the post to its author ("X answered on X that ...") and says only what \
the post says -- no guesses about motives. Give the paragraph number it should \
follow and, in "why", which party they are and what the post adds.

Separately, for the editor (nothing from these goes in the article):
- LEADS: relevant posts that are not quotable (a news account's report of what \
someone said) and report a development the article lacks;
- OPINIONS: the few most notable opinions by non-parties (top players, \
commentators), one line each, so the editor can decide.

Answer with JSON only:
{{"add": [{{"id": "...", "sentence": "...", "after_paragraph": 3, "why": "..."}}], \
"leads": [{{"id": "...", "why": "..."}}], "opinions": [{{"id": "...", "why": "..."}}]}}"""


def _ask(client, model: str, system: str, user: str) -> dict:
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0)) if match else {}


def _post_lines(posts: list[dict]) -> str:
    return "\n".join(
        f"[{p['id']}] {'QUOTABLE' if p['quotable'] else 'LEAD ONLY'}{' TOP NAME' if p.get('top') else ''}"
        f" @{p['handle']} ({p['name']})"
        f"{' via @' + p['via'] if p['via'] else ''}: {p['text'][:700]}"
        for p in posts
    )


def _embed(p: dict, after: str) -> dict:
    text = p["text"] if len(p["text"]) <= MAX_TEXT_CHARS else p["text"][: MAX_TEXT_CHARS - 1].rstrip() + "…"
    # draft.py writes the value inside double quotes and escapes only quote
    # marks: keep paragraph breaks as YAML "\n" escapes, nothing else.
    text = re.sub(r"\n\s*\n", lambda _: "\\n\\n", text.replace("\\", "")).replace("\n", " ")
    date = datetime.fromtimestamp(p["ts"], timezone.utc).strftime("%Y-%m-%d") if p["ts"] else ""
    return {"url": p["url"], "author": p["name"], "handle": p["handle"], "after": after, "text": text, "date": date}


def apply_adds(body: str, adds: list[dict], posts: list[dict]) -> tuple[str, list[dict]]:
    """Insert each sentence as its own paragraph after the paragraph named,
    and return the embeds anchored to those sentences."""
    by_id = {p["id"]: p for p in posts if p["quotable"]}
    paras = paragraphs(body)
    inserts: dict[int, list[str]] = {}
    embeds = []
    for add in adds[:MAX_ADDS]:
        p = by_id.get(str(add.get("id")))
        sentence = re.sub(r"\s+", " ", str(add.get("sentence") or "")).strip()
        if not p or len(sentence) < 20 or len(sentence) > 320:
            continue
        idx = add.get("after_paragraph")
        idx = idx - 1 if isinstance(idx, int) and 1 <= idx <= len(paras) else len(paras) - 1
        inserts.setdefault(idx, []).append(sentence)
        embeds.append(_embed(p, " ".join(sentence.split()[:7])))
    if not inserts:
        return body, []
    out = []
    for i, para in enumerate(paras):
        out.append(para)
        out.extend(inserts.get(i, []))
    return "\n\n".join(out) + "\n", embeds


def reactions(client, model: str, title: str, body: str, existing: list[dict]) -> tuple[str, list[dict], list[str]]:
    """(new body, embeds to add, PR-report notes) for one draft. Never raises."""
    try:
        posts = all_recent_posts()
        cands = candidates_for(title, body, posts, {e.get("url") for e in existing})
        if not cands:
            return body, [], []
        tops = top_names()
        for p in cands:
            p["top"] = is_top_name(p, tops)
        numbered = "\n\n".join(f"({i}) {p}" for i, p in enumerate(paragraphs(body), 1))
        answer = _ask(
            client,
            model,
            _PICK_PROMPT.format(max_adds=MAX_ADDS),
            f"ARTICLE: {title}\n\n{numbered}\n\nPOSTS:\n{_post_lines(cands)}",
        )
        new_body, embeds = apply_adds(body, answer.get("add") or [], cands)
        by_id = {p["id"]: p for p in cands}
        why = {str(a.get("id")): a.get("why", "") for a in answer.get("add") or []}
        added_urls = {e["url"] for e in embeds}
        notes = [
            f"ADDED @{p['handle']}: {why.get(p['id'], '')} -- {p['url']}"
            for p in cands
            if p["url"] in added_urls
        ]
        for key, label in (("leads", "lead, not quoted"), ("opinions", "opinion, not added")):
            for entry in answer.get(key) or []:
                p = by_id.get(str(entry.get("id")))
                if p:
                    notes.append(f"{label} @{p['handle']}: {entry.get('why', '')} -- {p['url']}")
        return new_body, embeds, notes
    except Exception as exc:  # noqa: BLE001 -- best effort, like the other lookups
        print(f"  x watch failed for '{title}': {exc}", file=sys.stderr)
        return body, [], []


_FOLLOWUP_PROMPT = """You check whether a published chess controversy story has new \
developments on X. You get the article and recent posts. List posts reporting a \
real new development (a reply, a statement, a new person taking a side, an \
official decision) that the article does not contain. Ignore opinions from \
random fans. Answer with JSON only: {"new": [{"id": "...", "why": "one line"}]}"""


def _recent_controversies(days: int = 2) -> list[tuple[str, str, str]]:
    today = datetime.now(timezone.utc).date()
    out = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text()
        if 'reviewStatus: "published"' not in text or 'lens: "drama"' not in text:
            continue
        m = re.search(r'^publishDate: "(\d{4}-\d{2}-\d{2})"', text, re.M)
        if not m or (today - datetime.strptime(m.group(1), "%Y-%m-%d").date()).days > days:
            continue
        title = re.search(r'^title: "(.*)"', text, re.M)
        body = text.split("\n---\n", 1)[1] if "\n---\n" in text else ""
        out.append((path.stem, title.group(1) if title else path.stem, body))
    return out


def followups(client, model: str) -> list[str]:
    """PR-report lines: new reactions to the last two days' controversy pieces."""
    lines = []
    try:
        stories = _recent_controversies()
        if not stories:
            return []
        posts = all_recent_posts()
        for slug, title, body in stories:
            cands = candidates_for(title, body, posts, set(re.findall(r'url: "([^"]+)"', body)))
            if not cands:
                continue
            answer = _ask(client, model, _FOLLOWUP_PROMPT, f"ARTICLE: {title}\n\n{body}\n\nPOSTS:\n{_post_lines(cands)}")
            by_id = {p["id"]: p for p in cands}
            for new in answer.get("new") or []:
                p = by_id.get(str(new.get("id")))
                if p:
                    lines.append(f"{slug} -- @{p['handle']}: {new.get('why', '')} {p['url']}")
    except Exception as exc:  # noqa: BLE001
        print(f"  x watch follow-ups failed: {exc}", file=sys.stderr)
    return lines


if __name__ == "__main__":
    for p in all_recent_posts()[:40]:
        print(("Q " if p["quotable"] else "L ") + f"@{p['handle']} {p['url']}\n   {p['text'][:140]}")
