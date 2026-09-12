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
from images import localize_image, pick_image_for_item

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SELECTED_PATH = DATA_DIR / "selected.json"
ARTICLES_DIR = ROOT / "src" / "content" / "articles"

MODEL = "claude-sonnet-5"

# Only offered on news-item drafting calls (see draft_one) -- the prompt
# restricts actual use to the community-pulse lens. $10/1,000 searches plus
# normal token cost for result content; at this volume (at most one
# community-pulse piece a day) the added cost is negligible.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}

CALENDAR_KINDS = {"calendar-biggest", "calendar-comingup"}

# Instructions for the two calendar aggregate kinds -- keyed by candidate
# "kind" rather than "lens", since both use the tournament-db lens but need
# very different framing (retrospective ranking vs. forward-looking list).
# Shared caveat for both aggregate kinds: when player counts/prize funds are
# missing from the data, that's a gap in what chesstournamentcalendar.com
# tracks, not a fact about the tournaments themselves -- plenty of them
# genuinely do report this information, just not to that source. Phrasing
# like "no player counts were reported for any of these events" reads as a
# claim about the tournaments/organizers, which is neither true nor ours to
# assert; frame it as our data's limitation instead (e.g. "we don't have
# player counts for most of these" / "not tracked here").
# Only North America and Oceania have a genuine, continent-wide player-count
# reporting gap (the US and Australia specifically don't report much through
# chess-results, which is where most of this data comes from). Everywhere
# else, the vast majority of countries do report through chess-results, so a
# sweeping "we don't have numbers for a lot of these" caveat is simply
# inaccurate there -- it happened on a South America piece where it wasn't
# true. A country here or there with thin data (e.g. Norway/Denmark within
# Europe) is normal noise, not a pattern worth a caveat paragraph about.
_CONTINENTS_WITH_REPORTING_GAP = {"NA", "OC"}


def aggregate_data_gap_note(continent_code: str) -> str:
    if continent_code in _CONTINENTS_WITH_REPORTING_GAP:
        return (
            "This continent has a genuine, known gap: some countries here (notably the US and "
            "Australia) don't report through chess-results, the main source for this data, so "
            "plenty of real tournaments from those countries are likely missing player counts "
            "or missing from this data entirely. It's fine, and often worth a line, to caveat "
            "the ranking on that basis. When player counts or other data points are missing for "
            "some tournaments, frame that as a gap in what this data covers, not as something "
            "the tournaments or their organizers failed to do (never write \"no player counts "
            "were reported for any of these events\" or similar -- write \"we don't have player "
            "counts for most of these\" or \"not tracked in this data\" instead)."
        )
    return (
        "Most countries on this continent report reliably through chess-results, the main "
        "source for this data, so do NOT add a general caveat suggesting player counts are "
        "widely missing or that the ranking might be unrepresentative -- that would be "
        "inaccurate here. If a specific tournament or country in the data you were given is "
        "genuinely missing a player count, it's fine to note that one specific gap, but don't "
        "generalize it into a claim about the continent's data coverage as a whole."
    )

AGGREGATE_INSTRUCTIONS = {
    "calendar-biggest": (
        "Write an original retrospective piece ranking the biggest tournaments "
        "in this continent last month, grounded entirely in the tournament data "
        "provided (a JSON list, already sorted by players registered, largest "
        "first). This is original reporting, not commentary on someone else's "
        "article. Cover the top entries by name, player count, location, and "
        "anything else notable (format, rating requirement) given in the data "
        "-- do not invent details not present in the data. Every tournament you "
        "mention by name MUST be a Markdown link using its \"url\" field from "
        "the data -- link the tournament's own name text, not generic text like "
        "\"here\". Whether to caveat the gap between the total tracked count "
        "and the number actually ranked is entirely covered by the data-gap "
        "guidance below -- don't add your own version of that caveat on top of "
        "it, and don't reach for one at all on a continent that guidance says "
        "not to."
    ),
    "calendar-comingup": (
        "Write an original preview piece highlighting notable tournaments "
        "coming up next month in this continent, grounded entirely in the "
        "tournament data provided (a JSON list of highlights, some ranked by "
        "player count, others -- where player counts aren't reliably reported "
        "-- selected as notable by name/format/rating requirement). This is "
        "original reporting, not commentary on someone else's article. Cover a "
        "handful of the most interesting entries by name, date, location, and "
        "any other notable detail given in the data -- do not invent details "
        "not present in the data. Every tournament you mention by name MUST be "
        "a Markdown link using its \"url\" field from the data -- link the "
        "tournament's own name text, not generic text like \"here\". Mention "
        "the overall count of tracked tournaments in the continent that month "
        "for context."
    ),
}

# The four lenses a news item can be drafted through -- the model picks
# whichever fits the specific story best (see NEWS_SYSTEM_PROMPT).
LENS_OPTIONS = {
    "drama": (
        "Drama angle: lean into any scandal, controversy, or genuine "
        "interpersonal conflict in the story -- add color and reasonable "
        "speculation about motives, stakes, and fallout, the way a sharp "
        "opinion columnist would. Only pick this lens when there's a real "
        "scandal, dispute, grievance, or falling-out to work with -- someone "
        "objecting to something, a rules or conduct controversy, a rivalry "
        "with real tension behind it. A team simply winning or losing a "
        "match, even in an upset or unusual format, is competition, not "
        "drama -- that's historical-parallel (if there's a genuine echo of "
        "the past) or community-pulse (if the story is really about how "
        "people are reacting) territory instead. Don't reach for this lens "
        "just because a result was surprising."
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
        "opinion splits, what's getting argued about. Use the web_search tool "
        "to find real, current discussion of this story (forums, social "
        "media commentary, other chess sites' coverage, comment sections) and "
        "ground the piece in what you actually find. If search turns up "
        "little or nothing relevant, fall back to characterizing the likely "
        "reaction in general terms based on how chess fandom has responded to "
        "comparable stories before -- but never invent specific quotes, "
        "usernames, or claim a specific post/comment exists when you're "
        "actually extrapolating."
    ),
}

CONTINENT_OPTIONS = "europe, asia, north-america, south-america, africa, oceania, global"

# Shared prose-style guidance -- aimed squarely at the tells that make AI-drafted
# text read as AI-drafted, independent of what the piece is arguing.
STYLE_GUIDE = """Writing style: write like an experienced human beat writer, not an \
AI assistant. Concretely:
- Do not use em dashes (--) or en dashes as a substitute for commas, periods, or \
parentheses. Use a period, comma, or colon instead, or just write two sentences.
- Avoid AI-tell stock phrases and constructions: "it's not just X, it's Y", \
"the real story is/isn't", "at the end of the day", "in a world where", \
"underscores", "highlights the fact that", "serves as a reminder", "speaks to", \
"paints a picture of". If a sentence would fit unchanged into any other article on \
any other topic, rewrite or cut it.
- Vary sentence length and structure. Do not open consecutive paragraphs with the \
same grammatical pattern (e.g. "X is Y." / "X's Z is W." / "X's A is B."). Do not \
default to three-item lists.
- No false triads ("informs, entertains, and connects"). Say the specific thing.
- Prefer plain, direct verbs and concrete nouns over hedge-y abstractions.
- Keep paragraphs short: 2-4 sentences each, one idea per paragraph, hard cap at 4 \
sentences with no exceptions, AND a target of roughly 60 words per paragraph \
(70 as a hard ceiling). Tracking a running word count while you write is not \
reliable -- don't try. Use this concrete rule instead, checked sentence by \
sentence as you write it, not after the fact: the moment a sentence names a \
SECOND person's individual result, a second direct quote, or a second distinct \
outcome, joined by "and," a comma, or a semicolon, stop -- that fact starts a \
new sentence, and if the paragraph is already at 3-4 sentences, a new paragraph. \
"X beat Y in N moves, A beat B, and C also won" is three facts stapled into one \
sentence with commas; it must be two or three sentences, and likely two \
paragraphs, not one. This is the actual, observed failure mode: a paragraph \
that stays at 3-4 sentences by fusing several separate results or quotes \
together with commas reads as dense and cluttered no matter how short the \
sentence count makes it look, and it still blows past the word ceiling even \
though nothing here "counted" as too many sentences. This is a paragraph-length \
rule, not an article-length one -- add more short paragraphs to fit everything \
in, don't cut content to keep the piece itself short. When you have another \
fact to add to a paragraph that already has 2+ sentences (a format detail, a \
prize tier, a second player's result, a piece of context), that is the signal \
to start a new paragraph, not to fold it into the current sentence with "and" \
or a comma.
- Vary how the piece ENDS. The default failure mode here is closing every \
article by zooming out to a summarising pronouncement about what it all means \
("...and that's exactly the point", "...says something about where chess is \
heading next", "...in this corner of chess, the story is the product"). One of \
those reads fine; every article ending that way reads as a template, which is \
exactly what a returning reader notices. Only reach for the zoom-out ending when \
this specific piece has genuinely earned a broader claim. Otherwise end on \
something concrete: the next fixture or what happens next, a specific number, a \
quote, an unresolved question, or simply the last relevant fact -- and let it \
stand without a closing line explaining its significance."""

NEWS_SYSTEM_PROMPT = f"""You are writing for a small, curated chess news site. Every \
piece is a companion analysis to a linked source article -- never a reworded \
summary of the source. Add genuine analysis and context a casual reader wouldn't \
get from the source alone. Be accurate: never invent facts, quotes, or statistics \
not present in the source material given to you. If you are not confident about a \
detail, omit it rather than guess.

Do not trade away the source's own concrete details to make room for your added \
context -- include the specific facts the source gives alongside your analysis, \
not instead of it. A reader should come away knowing both what actually happened \
and why it matters; losing the former to make room for the latter is a failure, \
not a stylistic choice. It's fine, expected even, for the piece to run longer to \
fit both in -- do not compress by cutting real source detail. Never satisfy this \
by cramming more into each paragraph, though -- a longer piece means MORE short \
paragraphs, never fewer, longer ones. This matters most on exactly the stories \
where it's easiest to forget: a stat-heavy or multi-quote source is precisely \
when paragraphs need to split more often, not when the paragraph-length rule \
below quietly stops applying.

Before finalizing, check the source material against each of these categories and \
include whatever it actually gives you -- do not stop at the single headline \
figure or result if the source has more:
- Full numeric breakdowns, not just the top line: every prize-money tier given \
(not only 1st place), all named standings/scores given (not only the winner), \
every score/streak/count in the piece, not a representative one or two.
- Format/structure specifics: bracket or match format, time control, schedule/dates, \
qualification path -- anything the source says about how the event was actually run.
- The specific turning point: a notable move, tactic, quote, or moment the source \
describes, not just the final result stripped of how it happened.
- Series/scheduling context: what this event is part of, what's next, prior \
meetings/history the source mentions.
Omit a category only if the source genuinely doesn't cover it -- never because \
including it would make the piece longer.

The piece must stand alone for a reader who has never seen the source. Never refer \
back to the source by form ("the interview", "the piece", "his comments", "the \
article") unless you first establish, in your own words, that that form of source \
exists (e.g. "In a recent interview with Chess.com, Praggnanandhaa said...") -- a \
bare "the interview's mention of X" with no earlier sentence establishing an \
interview took place is confusing and reads as broken.

{STYLE_GUIDE}

LINKS IN THE BODY. Every piece must carry links in its own text, not just in \
the byline the site adds automatically:

1. Link the source article exactly once, early on, at the point where you first \
report what actually happened. Use the "Source URL" you were given, as a normal \
Markdown link, with the anchor text being the fact or result itself (e.g. \
"[picked up his 65th career Bullet Brawl title](url)"). Never use bare "here", \
"this article", "according to Chess.com" as the whole anchor, or the raw URL as \
the visible text. Once is enough; the site prints the source again at the foot of \
every piece.

2. Where the user turn lists previously published The Chess Herald articles, link one or \
two of them from a phrase in your own text that genuinely refers to what that \
article covers -- a player, event, tournament or theme you are already \
mentioning. Use the "/articles/<slug>/" path exactly as given, and make the \
anchor a natural noun phrase already in the sentence rather than bolting on \
"as we reported" or "read more about". If you mention that The Chess Herald has \
covered something before, that mention MUST itself be the Markdown link -- \
never describe or gesture at a previous piece in prose ("as covered in \
The Chess Herald's look at...") without the "[...](/articles/<slug>/)" markup actually \
wrapped around it; an unlinked reference to a specific past article reads as a \
broken or fabricated citation. Do not reword a sentence just to create a link, \
do not link the same article twice, and if none of the listed pieces is \
genuinely relevant to this story, link none of them -- a forced link is worse \
than no link. Note these are companion pieces, not news reports: never describe \
one as having "broken" or "first reported" anything.

Before linking a name, confirm it's the same real person or entity the \
listed article is actually about, not just matching text -- a shared surname, \
club, or federation is not enough. Chess federations are small worlds: two \
different people can share a last name (a federation official and an unrelated \
grandmaster), and a listed title mentioning a name is only about that specific \
person, not everyone who shares it. If you cannot confirm from what you actually \
know that it's the same person, don't link it -- a wrong link that misidentifies \
someone is worse than a missed one (caught live: a piece mentioning "Komil \
Sindarov," a federation vice president, was linked to an unrelated article about \
"Javokhir Sindarov," a grandmaster -- same surname, different, unrelated people).

First, pick the single best-fitting lens for THIS story from these options:
{chr(10).join(f"- {name}: {desc}" for name, desc in LENS_OPTIONS.items())}

Then pick the single most relevant continent for this story from: {CONTINENT_OPTIONS}. \
Use "global" only when no single continent genuinely fits (e.g. a story about \
international chess governance or an online-only event with no regional angle) -- \
prefer picking a real continent whenever the story has any regional anchor \
(a player's federation, a tournament's location, etc.).

You have a web_search tool available. Only use it if you choose the \
community-pulse lens (see its description above for how) -- for every other \
lens, do not search, just write from the source material given to you.

Don't carry over raw citation markup like <cite index="...">...</cite> \
from search results into your output -- that markup is for your own \
internal reference only, and \
must never appear anywhere in your final answer. Paraphrase and attribute in \
plain prose instead (e.g. "according to the tour's recap...").

Your FINAL message must consist ONLY of the fields below, each introduced by \
its marker line exactly as shown (@@NAME@@ alone on its own line, nothing \
else on that line) -- no markdown fences, no JSON, no commentary before, \
between, or after them. Any searching or reasoning happens before this \
final message, never mixed into it. Write each field's actual content on \
the line(s) that follow its marker; the text under BODY_MARKDOWN can \
freely contain quotes, apostrophes, or any other character -- there is no \
escaping to worry about, just write normal prose:

@@LENS@@
one of: {', '.join(LENS_OPTIONS.keys())}
@@CONTINENT@@
one of: {CONTINENT_OPTIONS}
@@TITLE@@
a clear, specific headline for this companion piece (not the source's title verbatim). Aim for 45-65 characters -- tight and punchy, not a full sentence restating every detail. Cut qualifying clauses and filler ("What This Means For...", "Here's Why...", "And That's the Point") rather than reaching for them; a shorter headline that names the one real hook beats a longer one that hedges. Only go past 65 when the story genuinely can't be named any shorter -- never as the default. If the title has two parts split by a colon or comma, the second part must build on or resolve the first, not restate it in weaker words or bolt on a vague tag like "anyway", "and more", or "explained" -- read the whole title aloud as one phrase before settling on it, and if the second half sounds like a shrug rather than a payoff, replace it with the actual concrete result (a name, a score, a place).
@@SOCIAL_COPY@@
a single short social post (under 260 characters) teasing the piece, no hashtags spam, at most one relevant hashtag -- never leave this empty
@@IMAGE_SUBJECTS@@
up to 3 real-world subjects mentioned in this piece, one per line, ordered by how central each is to THIS piece -- the actual protagonist or headline figure always first, whoever the piece is actually about, even when a more famous person who appears only in passing would be easier to find a photo of. The first name here gets tried first and wins if it finds any usable photo, so ranking by findability instead of centrality can hand the piece's photo to the wrong person entirely (caught live: a piece about Javokhir Sindarov's decisive result also mentioned Magnus Carlsen in an unrelated secondary match, and Carlsen -- more photographed, not more relevant -- ended up as the article's photo). Findability is still a real, secondary reason to include a name at all: a piece comparing player X to more famous player Y should still list Y as a fallback after X, since Y often has better photo coverage -- just never ahead of the piece's actual subject. Each a specific person's full name (e.g. "Magnus Carlsen", not just "Carlsen") or a specific organization/event name (e.g. "FIDE", "Chess Olympiad", "Titled Tuesday"). Leave this field's content empty if truly nothing fits.
@@BODY_MARKDOWN@@
the full article body in Markdown, 400-800 words -- long enough to fit both the source's own concrete details and your added analysis, never shortened by dropping one for the other. That length comes from MORE short paragraphs, not fewer, longer ones -- the ~60-word/70-ceiling paragraph rule above applies to every single paragraph here, with no exception for length or source density."""

def build_aggregate_system_prompt(continent_code: str) -> str:
    return f"""You are writing for a small, curated chess news site. \
This piece is original reporting on tournament data, not commentary on someone \
else's article. Be accurate: never invent facts or figures not present in the \
tournament data given to you. If you are not confident about a detail, omit it \
rather than guess.

{aggregate_data_gap_note(continent_code)}

Don't manufacture a caveat about fields the data happens not to have for any \
given tournament -- prize pool, currency, or rating requirement in particular. \
Mention one of these when a tournament in the data actually has it (a real, \
concrete detail worth reporting), but its absence is not itself a finding: \
never write a sentence like "none of the tournaments listed a prize pool, so \
no format-based cut existed" -- that both invents a narrative frame nobody \
asked for and, like the player-count case above, misattributes an ordinary \
gap in what this data covers to the tournaments themselves.

{STYLE_GUIDE}

LINKING TO THE COMPANION PIECE. Where the user turn lists earlier The Chess Herald \
calendar pieces for this same continent, link the most recent one exactly once, \
using the "/articles/<slug>/" path exactly as given. Each is labelled \
(retrospective) or (preview) -- these pieces come in pairs, one of each per \
continent per month, so the other one is genuinely the next thing a reader of \
this piece would want, and its label tells you which direction to phrase the \
anchor in. Put the link wherever you naturally refer to the neighbouring \
month, and make the anchor a noun phrase describing what that piece covers, \
matching its own tense to its label -- never "read more" or "our previous \
article":
- Linking to a (retrospective): past tense, it already happened, e.g. "how \
[the same tournaments actually turned out](/articles/slug/)".
- Linking to a (preview): future tense, nothing has happened yet, e.g. "a \
first look at [what's coming up this month](/articles/slug/)" -- THIS month, \
not next: the preview was published the month before, when the month it \
covers genuinely was "next month," but a retrospective always publishes \
during the very month the paired preview covers, so by the time a reader \
sees this link that month is the current one, not the next one (caught \
live: a retrospective published Sept. 9 said "next month" about a preview \
that was already covering September). Never use turned-out/already-happened \
phrasing for one of these -- the tournaments it covers haven't been played \
yet.
One link only, and none at all if the list is empty. This is separate from, \
and additional to, the tournament links required above.

Respond with ONLY the fields below, each introduced by its marker line \
exactly as shown (@@NAME@@ alone on its own line) -- no markdown fences, no \
JSON, no commentary before, between, or after them. The text under \
BODY_MARKDOWN can freely contain quotes, apostrophes, or any other \
character -- there is no escaping to worry about, just write normal prose:

@@TITLE@@
a clear, specific headline for this piece (not a generic restatement). Aim for 45-65 characters -- name the one real hook, don't restate every detail in the headline.
@@SOCIAL_COPY@@
a single short social post (under 260 characters) teasing the piece, no hashtags spam, at most one relevant hashtag
@@BODY_MARKDOWN@@
the full article body in Markdown, 300-600 words"""


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80].rstrip("-")


# How many previously-published pieces to offer the model as internal-link
# candidates. Newest first: recent stories are far likelier to share a
# subject with today's news than something from months back, and a list long
# enough to cover the whole archive would be mostly noise the model has to
# read past on every call.
INTERNAL_LINK_CANDIDATES = 40


def published_articles(exclude_slug: str | None = None) -> list[dict]:
    """Title + slug for every published article on disk, newest first, for
    the model to link from a new piece. Read from the files rather than
    tracked separately so a manually-added or hand-edited article is a
    link candidate too."""
    entries = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        if 'reviewStatus: "published"' not in text:
            continue
        title = re.search(r'^title:\s*"(.*?)"\s*$', text, re.M)
        date = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"\s*$', text, re.M)
        if not title or not date or path.stem == exclude_slug:
            continue
        continent = re.search(r'^continent:\s*"?([a-z-]+)"?\s*$', text, re.M)
        lens = re.search(r'^lens:\s*"?([a-z-]+)"?\s*$', text, re.M)
        aggregate_kind = re.search(r'^aggregateKind:\s*"?([a-z-]+)"?\s*$', text, re.M)
        entries.append(
            {
                "slug": path.stem,
                "title": title.group(1),
                "date": date.group(1),
                "continent": continent.group(1) if continent else "",
                "lens": lens.group(1) if lens else "",
                "aggregateKind": aggregate_kind.group(1) if aggregate_kind else "",
            }
        )

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:INTERNAL_LINK_CANDIDATES]


def calendar_pieces_for_continent(continent_slug: str) -> list[dict]:
    """Previously published calendar aggregates for one continent, newest
    first. Each continent gets two of these a month -- a retrospective on
    last month and a preview of next -- so its counterpart is reliably the
    one other article a reader of either would actually want. Matched on
    frontmatter rather than by asking the model to infer it from titles,
    which are written for readers and don't name the continent
    consistently ("Barcelona's Sants Open and a Romanian Rapid Lead
    Europe's August Field")."""
    return [
        entry
        for entry in published_articles()
        if entry["lens"] == "tournament-db" and entry["continent"] == continent_slug
    ]


def build_user_prompt(item: dict) -> str:
    if item["kind"] in CALENDAR_KINDS:
        # Each tournament gets its own chesstournamentcalendar.com page at
        # /tournament/<slug>/ -- add that as a "url" field so the model can
        # link each tournament's name directly to its own page rather than
        # just the continent-level overview.
        tournament_data = [
            {**t, "url": f"https://chesstournamentcalendar.com/tournament/{t['slug']}/"}
            for t in item["tournamentData"]
        ]
        parts = [
            AGGREGATE_INSTRUCTIONS[item["kind"]],
            "",
            f"Continent: {item['continentName']}",
            f"Month: {item['monthLabel']}",
            f"Total tournaments tracked in this continent this month: {item['totalTracked']}",
            f"Continent page URL (for reference, not required in the body): {item['sourceUrl']}",
            f"Tournament data (JSON list): {json.dumps(tournament_data)}",
        ]

        companions = calendar_pieces_for_continent(CONTINENT_SLUGS[item["continentCode"]])
        if companions:
            parts.append("")
            parts.append(
                "Earlier The Chess Herald calendar pieces covering this same continent, newest "
                "first. Link the most recent one once, per the linking rule in your "
                "instructions:"
            )
            for entry in companions:
                kind_label = "preview" if entry["aggregateKind"] == "calendar-comingup" else "retrospective"
                parts.append(f"- \"{entry['title']}\" ({entry['date']}, {kind_label}) -> /articles/{entry['slug']}/")
        return "\n".join(parts)

    parts = [
        f"Source title: {item['title']}",
        f"Source URL: {item['sourceUrl']}",
        f"Source name: {item['sourceName']}",
    ]
    if item.get("summary"):
        parts.append(f"Source summary/excerpt: {item['summary']}")

    # Internal-link candidates. Supplied as data rather than baked into the
    # system prompt because the list changes with every published batch.
    previous = published_articles()
    if previous:
        parts.append("")
        parts.append(
            "Previously published The Chess Herald articles you may link to (see the linking "
            "rules in your instructions). Link one only where it genuinely helps the "
            "reader; skip them all if nothing here is actually related:"
        )
        for entry in previous:
            parts.append(f"- \"{entry['title']}\" -> /articles/{entry['slug']}/")
    return "\n".join(parts)


# Maps each @@NAME@@ marker to its dict key. Field order in the prompts
# always ends with BODY_MARKDOWN, so its content can safely run to the end
# of the message without a closing marker.
_FIELD_MARKERS = {
    "LENS": "lens",
    "CONTINENT": "continent",
    "TITLE": "title",
    "SOCIAL_COPY": "socialCopy",
    "IMAGE_SUBJECTS": "imageSubjects",
    "BODY_MARKDOWN": "bodyMarkdown",
}
_FIELD_MARKER_RE = re.compile(r"^@@([A-Z_]+)@@[ \t]*\r?\n", re.MULTILINE)


def parse_response(text: str) -> dict:
    text = text.strip()
    # Defensive: strip accidental code fences even though the prompt asks for none.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Sentinel-marker format instead of JSON: the model writes each field's
    # content as plain text after its own @@NAME@@ line, so nothing needs
    # escaping (a stray unescaped quote in dialogue used to break json.loads
    # and lose the whole article -- this format has no such failure mode).
    segments = _FIELD_MARKER_RE.split(text)
    if len(segments) < 3:
        raise ValueError(f"No @@FIELD@@ markers found in model response: {text[:200]!r}")

    parsed: dict = {}
    # segments alternates [preamble, marker, content, marker, content, ...]
    for marker, content in zip(segments[1::2], segments[2::2]):
        key = _FIELD_MARKERS.get(marker)
        if key is None:
            continue
        content = content.strip()
        if key == "imageSubjects":
            parsed[key] = [line.strip() for line in content.splitlines() if line.strip()]
        else:
            parsed[key] = content

    if "title" not in parsed or "bodyMarkdown" not in parsed:
        raise ValueError(f"Missing required field(s) in model response, got: {sorted(parsed)}")

    # Defensive backstop for the community-pulse (web_search) lens: despite
    # the prompt telling the model not to, it has carried raw <cite
    # index="...">...</cite> markup from search results straight into
    # bodyMarkdown in practice. Strip the tags but keep the inner text so a
    # slip here doesn't cost an otherwise-good draft.
    for key in ("title", "bodyMarkdown", "socialCopy"):
        if isinstance(parsed.get(key), str):
            parsed[key] = re.sub(r"</?cite[^>]*>", "", parsed[key])

    return parsed


# How many of the most recently published articles count as "recently
# used" for image-reuse purposes -- covers the homepage's lead + featured
# grid (see index.astro) so the same photo can't appear twice on the front
# page at once, without banning a photo outright forever. The Commons pool
# for a lot of chess subjects is small enough that a permanent ban would
# eventually starve the picker of any real photo at all; a cooldown lets a
# photo come back into rotation once enough new articles have gone out.
RECENT_IMAGE_COOLDOWN = 10


# Same-run siblings (e.g. two backfill items drafted a few seconds apart)
# need to see each other's image choice regardless of what publishDate ends
# up in their frontmatter -- see used_image_source_urls() below for why
# neither publishDate nor file mtime alone can carry that signal reliably.
# Populated by draft_one() as it goes; a plain module-level set is fine
# since backfill.py calls draft_one() in a simple loop, not concurrently.
_session_used_urls: set[str] = set()


def used_image_source_urls() -> set[str]:
    """Commons page URLs to treat as recently used -- not a permanent,
    site-wide ban, just a cooldown so the same photo can't appear twice
    close together (e.g. both on the homepage at once).

    Two signals, combined, because neither alone is reliable in every
    context this runs in:

    - The RECENT_IMAGE_COOLDOWN most recently *published* articles on disk,
      ranked by publishDate. This is what actually reflects real-world
      recency for articles from earlier runs/days -- but backfill runs
      backdate publishDate into the past, so a batch of backfilled articles
      drafted seconds apart can carry publishDates far apart from each
      other (and from "today"), which previously let siblings fall outside
      this window entirely (the original bug here).

    - _session_used_urls: every image picked so far in *this* process
      (see draft_one()). This is what actually catches same-run siblings
      regardless of their backdated publishDate -- ranking by file mtime
      instead was tried and reverted: a fresh CI checkout resets every
      pre-existing file's mtime to checkout time, so "most recent by
      mtime" degrades to an arbitrary tie-break across runs and silently
      stopped catching articles from a *previous day's* run (the bug that
      prompted this fix -- two live articles from the day before shared an
      image with a new draft because neither made an essentially-random
      mtime cutoff).

    Read from disk each call rather than cached, so the on-disk half can't
    go stale within a batch as draft_one writes new files. The image's
    sourceUrl is written with a 2-space indent (nested under "image:"); the
    top-level article sourceUrl has none, so matching just the indented
    form can't collide with it."""
    dated_urls: list[tuple[str, str]] = []
    for path in ARTICLES_DIR.glob("*.md"):
        text = path.read_text()
        date_match = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"\s*$', text, re.MULTILINE)
        image_match = re.search(r'^  sourceUrl:\s*"(.*?)"\s*$', text, re.MULTILINE)
        if date_match and image_match:
            dated_urls.append((date_match.group(1), image_match.group(1)))

    dated_urls.sort(key=lambda pair: pair[0], reverse=True)
    recent_on_disk = {url for _, url in dated_urls[:RECENT_IMAGE_COOLDOWN]}
    return recent_on_disk | _session_used_urls


# Matches the "70 as a hard ceiling" language in STYLE_GUIDE. A separate
# constant rather than parsing it back out of that prose: measured against
# real published output, paragraph-length compliance turned out to depend on
# the model reliably self-tracking a running word count while generating
# linearly, which it does not do well (the same class of limitation as
# asking for an exact word or letter count) -- verifying it after the fact
# and surfacing violations to the human reviewer is the actual backstop,
# not a substitute for the prompt wording but a check on whether it worked.
PARAGRAPH_WORD_CEILING = 70


def check_paragraph_lengths(body_markdown: str) -> list[tuple[int, int]]:
    """(paragraph number, word count) for every paragraph over the style
    guide's hard ceiling -- heading lines are skipped since they're not
    prose paragraphs and aren't subject to the rule. Best-effort like image
    sourcing: this never blocks or fails a draft, only flags it for review."""
    paragraphs = [p.strip() for p in body_markdown.split("\n\n") if p.strip() and not p.strip().startswith("#")]
    return [
        (i, word_count)
        for i, para in enumerate(paragraphs, 1)
        if (word_count := len(para.split())) > PARAGRAPH_WORD_CEILING
    ]


_PARAGRAPH_FIX_PROMPT = """You will be given one or more numbered paragraphs from an \
already-written chess article. Each one runs over a 70-word style-guide ceiling. Your \
only job is to split each into 2 or more shorter paragraphs at natural sentence or \
topic boundaries -- do not reword, cut, add, fact-check, or otherwise change a single \
word. Preserve every word, number, quote, and Markdown link exactly as given, byte for \
byte; only insert paragraph breaks (a blank line) between existing sentences. Split \
generously enough that every resulting paragraph is genuinely under 70 words, not just \
barely under.

Respond with ONLY the fixed paragraphs, each introduced by its own @@PARA_N@@ marker \
matching the input numbering exactly (e.g. @@PARA_1@@), with no commentary before, \
between, or after them. Within each @@PARA_N@@ section, separate the resulting \
paragraphs with a single blank line, same as normal Markdown."""


def fix_long_paragraphs(
    client: anthropic.Anthropic, body_markdown: str, offenders: list[tuple[int, int]]
) -> str:
    """Targeted follow-up pass: send back only the paragraphs check_paragraph_lengths
    flagged, ask the model to split each at natural boundaries with no other changes,
    and splice the results back in place.

    Deliberately narrower than re-drafting the whole piece: generation already
    proved unreliable at self-tracking paragraph length while juggling a dozen
    other simultaneous instructions (accuracy, links, quotes, lens, style) --
    "find a good place to break this one paragraph" is a much easier, isolated
    task, and the blast radius of a bad split is a paragraph break in the wrong
    place, not a reworded fact or a dropped link. Falls back to the original
    text on any failure (missing markers, wrong count) -- a still-flagged
    paragraph for human review beats a silently mangled one."""
    if not offenders:
        return body_markdown

    paragraphs = body_markdown.split("\n\n")
    # Mirrors check_paragraph_lengths' own enumeration (skips heading lines) so
    # offender indices line up with the same paragraphs it flagged.
    prose_indices = [i for i, p in enumerate(paragraphs) if p.strip() and not p.strip().startswith("#")]
    offender_numbers = {n for n, _ in offenders}

    request_parts = []
    for n, para_idx in enumerate(prose_indices, 1):
        if n in offender_numbers:
            request_parts.append(f"@@PARA_{n}@@\n{paragraphs[para_idx].strip()}")
    user_prompt = "\n\n".join(request_parts)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=_PARAGRAPH_FIX_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not text_blocks:
            print("  paragraph fix-up: no text content in response, falling back", file=sys.stderr)
            return body_markdown

        segments = re.split(r"^@@PARA_(\d+)@@[ \t]*\r?\n", text_blocks[-1].strip(), flags=re.MULTILINE)
        fixed = {int(n): content.strip() for n, content in zip(segments[1::2], segments[2::2])}

        if set(fixed) != offender_numbers:
            # Visibility for next time: this used to fail completely silently,
            # indistinguishable from "the fix-up never ran at all" in the
            # draft-report -- log what we actually got back so a format
            # mismatch (stray commentary, wrong marker style) is diagnosable
            # instead of a mystery.
            print(
                f"  paragraph fix-up: expected paragraphs {sorted(offender_numbers)}, "
                f"got {sorted(fixed)}, falling back. Raw response (first 500 chars): "
                f"{text_blocks[-1][:500]!r}",
                file=sys.stderr,
            )
            return body_markdown  # partial/malformed response -- don't risk a half-applied fix

        for n, para_idx in enumerate(prose_indices, 1):
            if n in fixed:
                paragraphs[para_idx] = fixed[n]

        return "\n\n".join(paragraphs)
    except Exception as exc:  # noqa: BLE001 -- best-effort like image sourcing; never fail the whole draft over this
        print(f"  paragraph fix-up: {type(exc).__name__}: {exc}, falling back", file=sys.stderr)
        return body_markdown


def draft_one(
    client: anthropic.Anthropic, item: dict, publish_date: str | None = None
) -> tuple[Path, list[tuple[int, int]]]:
    is_aggregate = item["kind"] in CALENDAR_KINDS
    system_prompt = build_aggregate_system_prompt(item["continentCode"]) if is_aggregate else NEWS_SYSTEM_PROMPT
    user_prompt = build_user_prompt(item)

    create_kwargs = dict(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        output_config={"effort": "medium"},
    )
    if not is_aggregate:
        # Available for every news item regardless of which lens gets picked --
        # the prompt restricts actual use to community-pulse; the tool call
        # itself is free to include, only real uses are billed.
        create_kwargs["tools"] = [WEB_SEARCH_TOOL]

    messages = [{"role": "user", "content": user_prompt}]
    response = client.messages.create(messages=messages, **create_kwargs)

    # A web search turn can pause on long-running searches (stop_reason
    # "pause_turn"); resume by sending the paused assistant turn back
    # unchanged, per Anthropic's docs. Capped so a stuck loop can't hang the
    # whole batch.
    for _ in range(3):
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
        response = client.messages.create(messages=messages, **create_kwargs)

    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError(f"No text content returned for: {item['title']}")

    # With web search enabled, earlier text blocks can be the model's own
    # "I'll search for..." narration -- only the final block is the
    # structured answer the prompt asked for.
    parsed = parse_response(text_blocks[-1])

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
        "publishDate": publish_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sourceName": item["sourceName"],
        "sourceUrl": item["sourceUrl"],
        "lens": lens,
        "continent": continent,
        "selectionScore": item["selectionScore"],
        "reviewStatus": "draft",
        # Fall back to the title itself if the model ever returns an empty
        # string despite the prompt -- happened once in practice (a
        # calendar aggregate with a blank socialCopy), and a blank social
        # teaser is a worse failure mode than a slightly generic one.
        "socialCopy": (parsed.get("socialCopy") or "").strip() or parsed["title"],
    }
    if is_aggregate:
        # Extra context for reviewers -- not part of the content schema (unknown
        # frontmatter keys are stripped at build time), but visible in the raw
        # file/PR diff, which is where a reviewer actually looks.
        frontmatter["aggregateKind"] = item["kind"]
        frontmatter["continentName"] = item["continentName"]
        frontmatter["monthLabel"] = item["monthLabel"]
        frontmatter["totalTracked"] = item["totalTracked"]

    image = pick_image_for_item(
        item, parsed["title"], parsed.get("imageSubjects", []), exclude_source_urls=used_image_source_urls()
    )
    if image:
        # Mark the Commons source as used regardless of what localize_image
        # does next -- a photo we already downloaded (even if the download
        # then failed to decode/save) shouldn't be offered to the very next
        # sibling article in this same run.
        _session_used_urls.add(image["sourceUrl"])
        localized = localize_image(image)
        if localized:
            frontmatter["image"] = localized

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
    return out_path, offenders


# The SDK already retries 408/409/429 and every 5xx (so 529 overloaded is
# covered) with exponential backoff, plus connection errors and timeouts --
# its default is 2. That default is tuned for interactive apps, where failing
# fast beats making a user wait. This is an unattended daily batch: a draft
# lost to a transient overload is simply gone until someone notices, and the
# run has all day, so it is worth waiting out a longer wobble.
BATCH_MAX_RETRIES = 5

# Written for the workflow to fold into the review PR's body. Without it a
# failed article is a line on a CI log nobody reads: the PR still opens, the
# remaining drafts still look fine, and the piece that never got written
# leaves no trace in front of the person deciding what to merge.
RUN_REPORT_PATH = DATA_DIR / "draft-report.md"


def write_run_report(written: list, failed: list, selected_count: int, long_paragraphs: list) -> None:
    lines = [f"Drafted {len(written)} of {selected_count} selected item(s)."]
    if failed:
        lines += ["", f"**{len(failed)} failed and are not in this PR:**", ""]
        lines += [f"- {title} — `{error}`" for title, error in failed]
        lines += ["", "Re-run the workflow to retry them, or draft them by hand."]
    if long_paragraphs:
        # The style guide's paragraph-length rule depends on the model
        # tracking its own running word count while writing, which isn't
        # reliable -- this is the actual backstop, not just a restatement
        # of the prompt rule, so it's worth a reviewer's attention even
        # though it never blocks the draft itself.
        lines += ["", f"**{len(long_paragraphs)} article(s) have a paragraph over the {PARAGRAPH_WORD_CEILING}-word style-guide ceiling:**", ""]
        for path, offenders in long_paragraphs:
            spots = ", ".join(f"#{i} ({n} words)" for i, n in offenders)
            lines.append(f"- {path.stem} — paragraph {spots}")
    RUN_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not SELECTED_PATH.exists():
        print("No selected.json found -- run selection.py first.")
        sys.exit(1)

    selected = json.loads(SELECTED_PATH.read_text())
    if not selected:
        print("No items selected -- nothing to draft.")
        return

    client = anthropic.Anthropic(max_retries=BATCH_MAX_RETRIES)

    written, failed, long_paragraphs = [], [], []
    for item in selected:
        try:
            path, offenders = draft_one(client, item)
            written.append(path)
            print(f"Drafted: {path.relative_to(ROOT)}")
            if offenders:
                long_paragraphs.append((path, offenders))
                print(f"  NOTE: {len(offenders)} paragraph(s) over {PARAGRAPH_WORD_CEILING} words", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 -- one bad draft shouldn't kill the run
            failed.append((item["title"], f"{type(exc).__name__}: {exc}"))
            print(f"FAILED to draft '{item['title']}': {exc}", file=sys.stderr)

    write_run_report(written, failed, len(selected), long_paragraphs)
    print(f"Wrote {len(written)}/{len(selected)} draft(s).")


if __name__ == "__main__":
    main()
