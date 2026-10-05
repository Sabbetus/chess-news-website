"""Finds a real, embeddable Lichess board for a specific game a drafted
article centers on -- e.g. Erigaisi's Round 1 loss to Laohawirapap at the
46th Olympiad. Only called when draft.py's model output actually names two
players for a specific game (see @@GAME_LOOKUP@@ in NEWS_SYSTEM_PROMPT);
most articles don't name one and this is never invoked for them, since a
web_search call costs real money and most stories -- calendar aggregates,
team-score pieces, multi-game trend pieces -- have no single game to show.

Two paths, tried in order:
  0. KNOWN_BROADCAST_TOURNAMENTS fast path (find_round_via_known_tournament,
     below) -- for an event this pipeline already covers regularly, query
     Lichess's own broadcast API directly by tournament id and check each
     round's real PGN for the named players. Deterministic, free, and
     doesn't depend on a web search having indexed the right page recently.
     Added after a real miss: the Women's Olympiad section's Koneru-
     Dzagnidze game was never embedded because the web-search finder below
     ran out of its search budget before confirming a URL -- even though
     the exact same game was trivially findable via this API in under a
     minute by hand (Lichess's own round list for a known tournament id is
     a single deterministic HTTP call, not a search-engine guess). The
     wrong-game-picked bug fixed elsewhere in this file was a real,
     separate issue, but fixing it alone wouldn't have helped here: the
     "correct" game would have hit the exact same search-budget wall.
  1. If the event isn't in the registry (a one-off tournament this
     pipeline doesn't track by id), fall back to the original two-step
     process, deliberately split so the risky step (is this really the
     right game) is a plain string comparison against real data, not a
     model guess:
       a. Ask Claude (with the web_search tool) to find the Lichess
          broadcast round covering this game.
       b. Fetch that round's PGN from Lichess's own broadcast API
          (structured, official data, not scraped) and look for the one
          game whose White/Black tags match both players by surname. Only
          an unambiguous single match gets embedded -- zero or multiple
          matches means no embed, not a guess.
"""

import re
import sys

import requests

USER_AGENT = "Chess-Herald-GameFinder/1.0 (https://chessherald.com; contact: sabbe.the.technomage@gmail.com)"
REQUEST_TIMEOUT = 15

# Lichess broadcast tournament ids for events this pipeline covers on a
# recurring, ongoing basis -- update by hand as new majors start, the same
# maintenance model as chess_results_standings.py's KNOWN_TOURNAMENTS.
# Matched against the drafted event string via plain substring containment
# (see find_round_via_known_tournament), so "46th Chess Olympiad" and "the
# Olympiad" both hit the "olympiad" entry.
#
# A single event can map to several tournament ids because large events
# split into parallel broadcasts by match-number range (top boards get
# their own dedicated broadcast; everything else is split into further
# brackets) -- which bracket a specific team/player falls into isn't
# knowable in advance, so every candidate for the event gets tried. This
# list is deliberately not exhaustive (lower-board brackets beyond what's
# listed here exist too) -- it only needs to cover the boards a "headline
# game" article is realistically going to name, and the web-search finder
# remains the fallback for anything this list doesn't catch.
KNOWN_BROADCAST_TOURNAMENTS: dict[str, list[str]] = {
    "olympiad": [
        "n1pPI5Q0",  # 46th FIDE Chess Olympiad Samarkand 2026 | Open | Matches 1-12
        "MSQXIzkK",  # 46th FIDE Chess Olympiad Samarkand 2026 | Open | Matches 13-37
        "HtMn014k",  # 46th FIDE Chess Olympiad Samarkand 2026 | Women | Matches 1-25
        "UjEVXNHv",  # 46th FIDE Chess Olympiad Samarkand 2026 | Women | Matches 26-50
        "oQuU2arG",  # 46th FIDE Chess Olympiad Samarkand 2026 | Women | Matches 76+
    ],
}

# 3 (the original value) wasn't enough -- caught live: a real lookup for a
# non-registry event found the right tournament within its budget but ran
# out of searches before it could narrow down to the specific round
# ("Given the tool limit for web searches has been exhausted for this
# session, I'm unable to verify the specific round slug/URL with certainty
# beyond the tournament-level broadcast page I found"). This fallback is
# still the only path for any event not in KNOWN_BROADCAST_TOURNAMENTS
# above, so it needs enough room for a realistic multi-step search
# (tournament, then round, then a confirming query) without hitting the
# same wall.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}

FINDER_MODEL = "claude-sonnet-5-5"

FINDER_SYSTEM_PROMPT = """You find the Lichess broadcast round covering one specific chess game.

You'll be given an event name and two player names. Search the web for a \
Lichess broadcast of that event and identify the round containing the game \
between those two players (searching something like "<event> <player1> \
lichess broadcast" usually works -- FIDE-relayed events are almost always \
on Lichess).

Respond with ONLY a Lichess broadcast round URL in the form \
https://lichess.org/broadcast/<tournament-slug>/<round-slug>/<roundId> (the \
roundId is the 8-character code in the path; a URL that also has a specific \
game/chapter id after the roundId is fine too, it'll be ignored). If you \
cannot find a real Lichess broadcast covering this specific event with \
reasonable confidence, respond with exactly NONE and nothing else. Never \
guess a plausible-looking URL -- an absent embed is fine, a broken or wrong \
one is not."""

# Matches a Lichess broadcast URL's tournament/round-slug/roundId segments --
# tolerant of an optional trailing /chapterId, which is ignored: the actual
# game gets found deterministically in find_game_in_round below, not trusted
# from the model's own URL pick.
BROADCAST_URL_RE = re.compile(r"lichess\.org/broadcast/([^/\s]+)/([^/\s]+)/(\w{8})(?:/\w{8})?")


def _surname(full_name: str) -> str:
    return full_name.strip().split()[-1].lower() if full_name.strip() else ""


def _tag_tokens(tag_value: str) -> set[str]:
    """Lichess's broadcast PGNs give player names in whatever format the
    organizer's FIDE feed used -- "Surname, Firstname" and "Surname
    Firstname" (no comma) both show up in the same round's data. Returning
    every individual word (comma stripped) rather than picking one
    position as "the surname" is what makes the caller's match tolerant of
    both without needing to know which format a given game used."""
    return {t.strip(",").lower() for t in tag_value.replace(",", " ").split()}


def find_broadcast_round(client, event: str, player1: str, player2: str) -> tuple[str, str, str] | None:
    """Returns (tournamentSlug, roundSlug, roundId) or None."""
    user_prompt = f"Event: {event}\nPlayer 1: {player1}\nPlayer 2: {player2}"
    # 1024 with no effort cap and no explicit budget for tool-result content
    # feeding back into later turns is the exact failure mode caught live
    # in production (2026-09-25's Wei Yi/Gumularz lookup: stop_reason
    # "max_tokens" with zero text content) -- the same shape of bug as
    # verify_claims/add_embed_scroll_link/fix_long_paragraphs, just not yet
    # caught here since this call had never been stress-tested. "low"
    # effort is enough for "read search results, pick a URL" -- it's a
    # lookup task, not one that benefits from deep reasoning -- but the
    # budget still needs real room for the web_search tool's own result
    # content flowing back into context across up to 4 total turns.
    create_kwargs = dict(
        model=FINDER_MODEL,
        max_tokens=4096,
        output_config={"effort": "low"},
        system=FINDER_SYSTEM_PROMPT,
        tools=[WEB_SEARCH_TOOL],
    )
    response = client.messages.create(messages=[{"role": "user", "content": user_prompt}], **create_kwargs)

    for _ in range(3):
        if response.stop_reason != "pause_turn":
            break
        response = client.messages.create(
            messages=[
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": response.content},
            ],
            **create_kwargs,
        )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks or response.stop_reason == "max_tokens":
        print(
            f"    lichess lookup: find_broadcast_round got no usable text content "
            f"(stop_reason={response.stop_reason!r}) for event={event!r} "
            f"player1={player1!r} player2={player2!r}",
            file=sys.stderr,
        )
        return None

    reply = text_blocks[-1].strip()
    match = BROADCAST_URL_RE.search(reply)
    if match is None:
        print(
            f"    lichess lookup: finder model returned no usable URL for "
            f"event={event!r} player1={player1!r} player2={player2!r} "
            f"-- reply was {reply[:200]!r}",
            file=sys.stderr,
        )
        return None
    print(
        f"    lichess lookup: finder model matched round "
        f"{match.group(1)}/{match.group(2)} ({match.group(3)}) for "
        f"event={event!r} player1={player1!r} player2={player2!r}",
        file=sys.stderr,
    )
    return (match.group(1), match.group(2), match.group(3))


def find_game_in_round(round_id: str, player1: str, player2: str) -> str | None:
    """Fetches the round's PGN from Lichess's broadcast API and returns the
    matched game's own GameURL tag if exactly one game's White/Black pair
    matches both players by surname -- None otherwise (no game found, or
    more than one candidate, which means the match isn't confident enough
    to trust)."""
    url = f"https://lichess.org/api/broadcast/round/{round_id}.pgn"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"    lichess lookup: round PGN fetch failed for round {round_id!r}: {exc}", file=sys.stderr)
        return None

    surname1, surname2 = _surname(player1), _surname(player2)
    if not surname1 or not surname2:
        print(
            f"    lichess lookup: empty surname from player1={player1!r} player2={player2!r}, skipping match",
            file=sys.stderr,
        )
        return None

    matches = []
    games_seen = 0
    for game_pgn in re.split(r"\n\n\n+", response.text.strip()):
        white = re.search(r'\[White\s+"([^"]+)"\]', game_pgn)
        black = re.search(r'\[Black\s+"([^"]+)"\]', game_pgn)
        game_url = re.search(r'\[GameURL\s+"([^"]+)"\]', game_pgn)
        if not (white and black and game_url):
            continue
        games_seen += 1
        white_tokens, black_tokens = _tag_tokens(white.group(1)), _tag_tokens(black.group(1))
        matched = (surname1 in white_tokens and surname2 in black_tokens) or (
            surname2 in white_tokens and surname1 in black_tokens
        )
        if matched:
            matches.append(game_url.group(1))

    if len(matches) == 1:
        print(f"    lichess lookup: matched exactly 1 game of {games_seen} in round {round_id!r}", file=sys.stderr)
        return matches[0]
    print(
        f"    lichess lookup: {len(matches)} game(s) matched surnames "
        f"{surname1!r}/{surname2!r} out of {games_seen} in round {round_id!r} "
        f"-- need exactly 1 to trust it, giving up",
        file=sys.stderr,
    )
    return None


# How many of a candidate tournament's most recent finished rounds to
# check before moving on to the next candidate. A "headline game" article
# is realistically about recent news, not an early round from weeks ago,
# so this bounds the worst case (an event with several irrelevant
# candidate tournaments, e.g. a Women's player checked against the Open
# brackets first) to a handful of fetches per candidate instead of
# exhaustively walking all 11 rounds of each one before moving on --
# caught live: without this cap, a real lookup for a Women's-section game
# spent over two minutes walking all 22 rounds across both Open brackets,
# which will never match a Women's player, before it ever reached the
# Women's brackets where the real match was.
_RECENT_ROUNDS_TO_CHECK = 3


def find_round_via_known_tournament(event: str, player1: str, player2: str) -> str | None:
    """Fast path for KNOWN_BROADCAST_TOURNAMENTS: returns a matched game's
    GameURL, or None if the event doesn't match a known entry (not an
    error -- most events aren't in the registry, and the caller falls back
    to the web-search finder for those)."""
    event_key = event.strip().lower()
    tour_ids = next((ids for key, ids in KNOWN_BROADCAST_TOURNAMENTS.items() if key in event_key), None)
    if not tour_ids:
        return None

    # Two passes: the most recent rounds of every bracket first (fast, and
    # where news reports usually are), then the older rounds. A recap or
    # column can single out a game from round 1 or 3 -- caught live
    # 2026-10-05: Speelman's Samarkand miniatures column (Rapport-Demchenko,
    # round 3) got no embed because only the last 3 rounds were ever checked.
    rounds_by_tour: dict[str, list[dict]] = {}
    for tour_id in tour_ids:
        try:
            response = requests.get(
                f"https://lichess.org/api/broadcast/{tour_id}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            rounds = response.json().get("rounds", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"    lichess lookup: known-tournament fetch failed for {tour_id!r}: {exc}", file=sys.stderr)
            continue
        rounds_by_tour[tour_id] = [r for r in reversed(rounds) if r.get("finished")]

    passes = (slice(0, _RECENT_ROUNDS_TO_CHECK), slice(_RECENT_ROUNDS_TO_CHECK, None))
    for window in passes:
        for tour_id, finished in rounds_by_tour.items():
            for round_ in finished[window]:
                game_url = find_game_in_round(round_["id"], player1, player2)
                if game_url:
                    print(
                        f"    lichess lookup: known-tournament fast path matched "
                        f"{round_['name']!r} in {tour_id!r} for player1={player1!r} player2={player2!r}",
                        file=sys.stderr,
                    )
                    return game_url
    return None


def embed_url_from_game_url(game_url: str) -> str:
    """https://lichess.org/broadcast/<ts>/<rs>/<roundId>/<gameId> ->
    https://lichess.org/embed/broadcast/<ts>/<rs>/<roundId>/<gameId>, the
    exact embeddable form (verified against Lichess's own route table)."""
    return game_url.replace("lichess.org/broadcast/", "lichess.org/embed/broadcast/", 1)


def find_game_embed(client, event: str, player1: str, player2: str) -> dict | None:
    """Top-level entry point: returns {"url": <embed url>} or None. Never
    raises for a "just didn't find it" outcome -- only network/programming
    errors propagate, since a missing embed is an expected, normal result
    for most calls (only invoked when draft.py's model named two players
    for one specific game in the first place).

    Logs the exact event/player1/player2 it was called with, plus each
    stage's outcome, to stderr -- caught live: draft.py's own per-article
    log line said only "requested" / "embed not found", with no visibility
    into which of the two lookup stages actually failed or what values the
    model's self-report had produced, making a real miss (Wei Yi's game
    against Indjic, round 4) undiagnosable from the CI log alone.

    Tries the free, deterministic KNOWN_BROADCAST_TOURNAMENTS path first --
    see its own docstring for why the web-search finder alone isn't
    reliable enough on its own for events this pipeline tracks regularly."""
    print(f"    lichess lookup: event={event!r} player1={player1!r} player2={player2!r}", file=sys.stderr)

    game_url = find_round_via_known_tournament(event, player1, player2)
    if game_url:
        return {"url": embed_url_from_game_url(game_url)}

    round_ref = find_broadcast_round(client, event, player1, player2)
    if round_ref is None:
        return None
    _, _, round_id = round_ref

    game_url = find_game_in_round(round_id, player1, player2)
    if game_url is None:
        return None

    return {"url": embed_url_from_game_url(game_url)}


# Matches a numbered SAN move (e.g. "37.Ng6", "50...Qg7", "38.Bg8+",
# "22...O-O"), the same shape the model writes into a body's prose whenever
# it quotes a specific game's moves. Not used to gate the recheck below --
# it can't catch every qualifying case (a title-clinching paragraph that
# just names winners by board, with no moves quoted, qualifies just as
# much -- see GAME_LOOKUP_CRITERIA) -- kept only as a diagnostic signal in
# draft.py's per-article log line, so a miss where the body plainly quotes
# moves but still got skipped is easy to spot in CI logs at a glance.
SAN_MOVE_RE = re.compile(
    r"\b\d{1,3}\.(?:\.\.)?\s?(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#!?]*\b"
)

# Single source of truth for what counts as embed-worthy -- imported into
# both NEWS_SYSTEM_PROMPT's own @@GAME_LOOKUP@@ field (the model's first,
# inline self-report while it's writing the piece) and RECHECK_SYSTEM_PROMPT
# below (an independent second pass over the finished body). Keeping one
# copy of the criteria means the recheck can't silently drift from what the
# model was originally told to look for.
GAME_LOOKUP_CRITERIA = """Fill this in whenever the piece gives ONE specific game real, headline-level treatment -- named players, and either a notable moment (a blunder, a sacrifice, a specific rating/seed gap) or enough of the game's shape to be worth seeing on a real board. This is NOT limited to pieces that are about nothing else: a round-recap piece that covers several results but still singles out one specific game by name, with real detail, qualifies just as much as a piece built entirely around one game -- Erigaisi's blunder-loss to Laohawirapap qualified even though that piece also covered the ceremony and other results, and a round recap that leads with "Liang's Shock Loss" and gives it a real paragraph (the 258-point rating gap, the opening, the result) qualifies on exactly the same basis, even though the same piece also covers Montenegro's draw and other matches. This also covers a title-clinching or decisive-match paragraph that names individual winners and their opponents, even without describing how any single game actually played out move-by-move -- the named result itself (who beat whom, on which board, to seal a title or a match) is the headline-level detail; a real board to show alongside it is worth more than the prose describing it (caught live: "Poland's Rollercoaster Ends in Gold at Samarkand" named three individual winners who clinched the title match against the Philippines by name and board, with no separate move-level description, and shipped with no embed -- any one of those three games qualified). What does NOT qualify: a bare team score with no players named at all ("India beat Thailand 3-1"), or a trend with no specific game attached ("the standings flipped again"). If more than one game in the piece would qualify on its own, pick the one the piece treats as its actual headline (usually whichever is named in the title) -- not whichever game happens to have the flashiest tactics or the most vivid description, if that game is a secondary mention rather than the result the title itself is about (caught live: "Madaminov's Unbeaten 5.5/7 Seals Uzbekistan's Second Gold" named Madaminov's game as the actual title-clinching result, but the self-report instead picked a sharper-sounding tactical game from deep in the Women's section -- Humpy Koneru's queen sacrifice against Dzagnidze -- which wasn't even the game the headline was about). Check the title first, then confirm the named player(s) in it actually have a game described in the body before picking anything else. For a multi-winner clinching paragraph with no other basis to rank them, pick the highest-rated or highest-titled player among them. When genuinely unsure whether a mention has enough detail to count, err toward filling this in rather than leaving it empty -- a lookup that finds nothing costs little, but skipping a piece that deserved a real embed is the worse failure mode."""

RECHECK_MODEL = "claude-sonnet-5-5"

RECHECK_SYSTEM_PROMPT = f"""You are given the finished Markdown body of a chess news article. A separate pass already decided this piece has no game worth embedding -- your job is to independently re-check that call against the same criteria, since that first pass has missed real qualifying pieces before. Read the body fresh, as if grading someone else's judgment call, not your own.

{GAME_LOOKUP_CRITERIA}

If the body qualifies under these criteria, respond with exactly these three lines and nothing else:
event: <tournament/event name>
player1: <first player's full name>
player2: <second player's full name>

If it genuinely does not qualify, respond with exactly NONE and nothing else."""


def recheck_game_lookup(client, body_markdown: str) -> dict | None:
    """Independent second pass over a finished body, run whenever the
    model's own inline @@GAME_LOOKUP@@ self-report came back empty --
    unconditionally, not gated on SAN_MOVE_RE or any other heuristic, since
    the qualifying criteria cover cases (a named clinching-match winner
    with no moves quoted) that no regex over the text can reliably detect.
    Splitting "write the piece" and "does this piece qualify" into two
    separate calls is the actual fix: asking the model to notice its own
    body qualifies in the same generation that wrote it has missed real
    cases in practice (Liang's shock loss, Yu Yangyi's forced mate vs.
    Georgiev, and Poland's title-clinching wins over the Philippines all
    shipped with no embed despite clearly qualifying) -- a fresh read with
    no drafting task competing for the model's attention catches what the
    inline self-report doesn't. Returns the same {"event", "player1",
    "player2"} shape parse_game_lookup produces, or None."""
    response = client.messages.create(
        model=RECHECK_MODEL,
        # Same audit as find_broadcast_round just above: no effort cap and
        # a floor (256) sized for the 3-line output alone left no room for
        # any thinking at all before hitting max_tokens. This one runs
        # unconditionally on every non-aggregate article, so an unnoticed
        # failure here silently loses the embed for pieces that would have
        # qualified -- exactly the failure mode this recheck exists to
        # catch in the first place, just one level removed.
        max_tokens=1024,
        output_config={"effort": "low"},
        system=RECHECK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": body_markdown}],
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks or response.stop_reason == "max_tokens":
        return None
    text = text_blocks[-1]

    event = re.search(r"^event:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    player1 = re.search(r"^player1:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    player2 = re.search(r"^player2:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if not (event and player1 and player2):
        return None
    return {
        "event": event.group(1).strip(),
        "player1": player1.group(1).strip(),
        "player2": player2.group(1).strip(),
    }


_EMBED_LINK_SYSTEM_PROMPT = """You are given the finished Markdown body of a chess news article. An interactive board for one specific game -- between {player1} and {player2} -- is embedded on the same page, right after this body's text ends, at the in-page anchor "#game-embed".

Find the single spot in the body that most directly describes this specific game (a quoted move like "26...Bd3!!", a phrase like "resigned soon after", or if no move is quoted, the moment the game was decided) and wrap that short existing phrase in a Markdown link to "#game-embed" -- e.g. turn `26...Bd3!!` into `[26...Bd3!!](#game-embed)` -- so a reader can jump straight to the board.

Rules:
- Change nothing else in the body -- same words, same punctuation, same paragraph breaks, everywhere except this one added link.
- Wrap the SHORTEST natural phrase that makes sense as a link -- a few words at most, ideally a quoted move or a short result phrase. Never wrap a whole sentence, and never wrap a phrase that's already inside a different Markdown link.
- Add exactly one such link, in whichever paragraph most directly describes this specific game.
- Respond with the ENTIRE body Markdown, verbatim except for that one added link, and nothing else -- no preamble, no explanation, no code fence."""


def add_embed_scroll_link(client, body_markdown: str, player1: str, player2: str) -> str:
    """Wrap one short, already-existing phrase describing the embedded game
    in a Markdown link to "#game-embed", so a reader can jump straight to
    the board from the prose that mentions it -- the embed itself always
    renders well after the body (see the article page layout), so without
    this a reader has no way to jump to it from wherever the game is
    actually discussed.

    A small, surgical model call (same pattern as fix_long_paragraphs in
    draft.py) rather than a regex over quoted moves: the qualifying
    criteria for an embed explicitly include games described with no
    moves quoted at all (a named clinching-match winner), which no regex
    can reliably find an anchor phrase for.

    Falls back to the original body, unmodified, if the response doesn't
    look like a safe edit (missing the expected link, or a suspiciously
    different length) -- a missing scroll-link costs nothing; a mangled
    body would ship a broken article.
    """
    response = client.messages.create(
        model=RECHECK_MODEL,
        # len(body_markdown) as a token count, not len // 2 -- this call
        # always echoes back the ENTIRE body (one added link aside), so
        # shrinking the floor to half the body's character count already
        # leaves a real gap even before accounting for any thinking tokens
        # "low" effort still uses. See verify_claims in draft.py for the
        # concrete failure mode this shape of bug caused once already this
        # session (fix_long_paragraphs, a floor sized the same way).
        max_tokens=max(8192, len(body_markdown)),
        system=_EMBED_LINK_SYSTEM_PROMPT.format(player1=player1, player2=player2),
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": body_markdown}],
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        return body_markdown
    # A max_tokens stop is a truncation failure even when some text came
    # back -- see verify_claims in draft.py for why this needs its own
    # explicit check rather than relying on the length-diff guard below to
    # catch it incidentally.
    if response.stop_reason == "max_tokens":
        return body_markdown
    edited = text_blocks[-1].strip()

    if "(#game-embed)" not in edited:
        return body_markdown
    # A real edit only adds a few characters ("[", "](#game-embed)") --
    # anything wildly different in length means the model rewrote or
    # truncated the body instead of making the one surgical edit asked for.
    if abs(len(edited) - len(body_markdown)) > 200:
        return body_markdown

    return edited
