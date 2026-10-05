"""Regression tests for the pipeline bugs that reset the review streak.

Each test names the live incident it pins down (see the streak tracker in
CLAUDE.md). Model calls are replaced with stand-in clients, so this suite
runs offline and costs nothing.
"""
import types

import coverage
import draft
import images
import ingest
import selection


def news(title, summary="", source="ChessBase", url=None):
    return {
        "kind": "news",
        "title": title,
        "summary": summary,
        "sourceName": source,
        "sourceUrl": url or f"https://example.com/{abs(hash(title))}",
        "selectionScore": 1,
    }


class StubClient:
    """Stands in for anthropic.Anthropic(); returns a fixed text reply."""

    def __init__(self, reply):
        self.calls = 0
        outer = self

        class _Messages:
            @staticmethod
            def create(**kwargs):
                outer.calls += 1
                text = reply(kwargs) if callable(reply) else reply
                return types.SimpleNamespace(
                    content=[types.SimpleNamespace(type="text", text=text)], stop_reason="end_turn"
                )

        self.messages = _Messages()


# --- Story merging (2026-09-30, 10-01, 10-02) ---


def test_sentence_start_words_are_not_names():
    # 10-01: Turlov interview merged with a schools report on "What"/"They".
    names = selection._single_names(news("x", "What a day. They played well. Argentina, seeded 28th, beat Ukraine."))
    assert "what" not in names and "they" not in names
    assert {"argentina", "ukraine"} <= names


def test_grandmaster_is_not_a_name():
    # 09-30: Titled Tuesday merged with the London Classic on "Grandmasters".
    assert "grandmaster" not in selection._single_names(news("x", "The Grandmaster documentary."))


def test_merge_requires_model_confirmation():
    # 10-02: U.S. Championship merged with Freestyle Friday on "Anna", "Women"...
    a = news("Saint Louis to host America's chess elite",
             "Watch on YouTube and Twitch. The Women field has Jennifer Yu. Anna Sargsyan plays. Germany sends Kosteniuk. Central Time.")
    b = news("Freestyle Friday is back",
             "Watch on YouTube and Twitch. The Women field has Jennifer Shahade. Anna Muzychuk plays. Germany hosts Kosteniuk. Central Europe.", source="FIDE")
    assert selection._is_same_story(a, b)  # the name heuristic alone would merge them
    selection._merge_verdicts.clear()
    merged = selection.merge_duplicate_stories([a, b], StubClient("NO"))
    assert len(merged) == 2 and not merged[0].get("additionalSources")


def test_no_client_means_no_merge():
    selection._merge_verdicts.clear()
    a = news("FIDE Ratings - October 2026", "Nodirbek Abdusattorov Zhu Jiner Savitha Shri Lu Miaoyi Mariam Mkrtchyan")
    b = news("FIDE October 2026 rating list published", "Nodirbek Abdusattorov Zhu Jiner Savitha Shri Lu Miaoyi Mariam Mkrtchyan", source="FIDE")
    assert len(selection.merge_duplicate_stories([a, b], None)) == 2


def test_confirmed_merge_happens():
    selection._merge_verdicts.clear()
    a = news("FIDE Ratings - October 2026", "Nodirbek Abdusattorov Zhu Jiner Savitha Shri Lu Miaoyi Mariam Mkrtchyan")
    b = news("FIDE October 2026 rating list published", "Nodirbek Abdusattorov Zhu Jiner Savitha Shri Lu Miaoyi Mariam Mkrtchyan", source="FIDE")
    merged = selection.merge_duplicate_stories([a, b], StubClient("YES"))
    assert len(merged) == 1 and merged[0]["additionalSources"][0]["sourceName"] == "FIDE"


# --- Rating-list cap (2026-10-02) ---


def test_rating_list_headlines_are_recognised():
    for title in ["FIDE Ratings - October 2026", "FIDE October 2026 rating list published", "Stars Climb On October FIDE Rating List"]:
        assert selection.is_rating_list_story(news(title)), title
    assert not selection.is_rating_list_story(news("Turlov wins FIDE vote"))


# --- Duplicates and stale stories (2026-09-29, 09-30, 10-03) ---


def test_same_url_already_published_is_dropped():
    # 09-30: the Uzbekistan interview came back a day after we published it.
    url = "https://en.chessbase.com/post/uzbekistan-winners-interview-olympiad-2026"
    published = [{"title": "The Anti-Motivator", "date": "2026-09-29", "summary": "", "urls": {coverage._norm_url(url)}}]
    kept = coverage.drop_same_url([news("Interview with the Olympic winners", url=url + "?ref=x"), news("Other")], published)
    assert [i["title"] for i in kept] == ["Other"]


def test_same_batch_stale_preview_is_dropped():
    # 10-03: "Freestyle Friday Returns October 2" drafted next to its result.
    items = [news("Bluebaum Takes First Freestyle Friday"), news("Freestyle Friday Returns October 2")]
    client = StubClient('{"stale_previews": [{"candidate": 2, "result_candidate": 1, "reason": "x"}]}')
    assert [i["title"] for i in coverage.drop_superseded_previews(client, items)] == ["Bluebaum Takes First Freestyle Friday"]


def test_stale_preview_check_fails_open():
    items = [news("A"), news("B")]
    assert coverage.drop_superseded_previews(StubClient("not json"), items) == items
    assert coverage.drop_superseded_previews(None, items) == items


def test_truncated_teasers_are_detected():
    # 09-29: Chess.com's 250-char teaser ("GM Oleksa...") was drafted from.
    assert ingest.summary_is_truncated("GM Oleksa...")
    assert ingest.summary_is_truncated("Something …")
    assert not ingest.summary_is_truncated("A full sentence.")


def test_year_range_is_not_a_scoreline():
    # 09-27: "the 2024-2026 Olympiad cycle" read as a match score.
    assert not selection._SCORELINE_RE.search("the 2024-2026 Olympiad cycle")
    assert selection._SCORELINE_RE.search("Uzbekistan beat Ukraine 2.5-1.5")


# --- Photos (2026-10-01, 10-02, 10-03) ---


def test_run_together_names_match_and_short_first_names_count():
    # 10-03: "JonSpeelman24.jpg" skipped; "Speelman en Speelman" must not match.
    assert images._title_matches_query("File:JonSpeelman24.jpg", "Jon Speelman", True)
    assert images._title_matches_query("File:Jon_Speelman.jpg", "Jon Speelman", True)
    assert not images._title_matches_query("File:Speelman en Speelman 2024.jpg", "Jon Speelman", True)


def test_people_pieces_only_search_their_subject():
    # 10-03: the Speelman profile got a photo of Nigel Short.
    item = {"kind": "news", "sourceName": "ChessBase"}
    queries = [q[0] for q in images.build_query_cascade(item, "Jon Speelman at 70", ["Jon Speelman", "Nigel Short"], prefer_neutral=True)]
    assert not any("Short" in q for q in queries)


def test_calendar_photos_only_try_tournament_names():
    # 10-01: Europe's calendar piece got a Romanian arbiter's portrait.
    item = {"kind": "calendar-biggest", "continentCode": "EU", "continentName": "Europe",
            "tournamentData": [{"name": "Craiova Grand Prix Rapid 2026", "country": "Romania"}]}
    queries = [q[0] for q in images.build_query_cascade(item, "x")]
    assert queries == ["Craiova Grand Prix Rapid 2026"]


def test_neutral_fallback_skips_photos_already_in_use():
    # 10-01: two neighbouring articles got the same chess-pieces photo.
    first = images.fallback_image("some headline")
    second = images.fallback_image("some headline", {first["sourceUrl"]})
    assert second["sourceUrl"] != first["sourceUrl"]


# --- Drafting helpers (2026-10-01, 10-02, 10-03) ---


def test_calendar_counts_are_precomputed():
    data = [{"name": "A", "timeControl": "Rapid"}] * 3 + [{"name": "B", "timeControl": "Classical"}]
    facts = draft.aggregate_facts(data)
    assert "Entries in this list: 4" in facts and "rapid 3" in facts and "classical 1" in facts


def test_cut_off_tournament_names_end_on_a_whole_word():
    assert draft.clean_tournament_name("CHENNAI District - CM TROPHY 2026 - School Boys Ca") == "CHENNAI District - CM TROPHY 2026 - School Boys"
    assert draft.clean_tournament_name("Short Open 2026") == "Short Open 2026"


def test_verifier_round_trips_headline_and_body():
    # 10-01: headlines were never fact-checked ("Kasparov Named in...").
    parsed = {"title": "Kasparov Named in Plot", "socialCopy": "S", "metaDescription": "M" * 60, "bodyMarkdown": "Body. " * 40}

    def reply(kwargs):
        article = kwargs["messages"][0]["content"].split("ARTICLE TO FACT-CHECK:\n\n", 1)[1]
        return article.replace("Kasparov Named in Plot", "Kasparov Reportedly Warned")

    out = draft.verify_claims(StubClient(reply), parsed, news("x", "source text"))
    assert out["title"] == "Kasparov Reportedly Warned"


def test_rating_list_prompt_asks_for_rankings_links():
    prompt = draft.build_user_prompt({"kind": "news", "title": "FIDE Ratings - October 2026", "sourceUrl": "x", "sourceName": "ChessBase", "summary": "s"})
    assert "/rankings/" in prompt and "/rankings/women/" in prompt


def test_calendar_ranking_prefers_notable_over_big():
    """2026-10-05: calendar pieces rank by notability, not field size, and no
    country fills the list."""
    import ingest

    open_ = {"name": "Toronto Open", "countryCode": "CA", "timeControl": "Classical",
             "startDate": "2026-09-05", "endDate": "2026-09-07", "playersRegistered": 40}
    school = {"name": "Encuentro Escolar Rapid", "countryCode": "DO", "timeControl": "Rapid",
              "startDate": "2026-09-29", "endDate": "2026-09-29", "playersRegistered": 160}
    us = {"name": "61st American Open Chess Championship", "countryCode": "US",
          "timeControl": "Classical", "startDate": "2026-11-25", "endDate": "2026-11-30"}
    capped = {"name": "Labour Day Open 2026 Under Section", "countryCode": "CA",
              "timeControl": "Classical", "startDate": "2026-09-05", "endDate": "2026-09-07"}
    assert ingest._notability_score(open_) > ingest._notability_score(school)
    assert ingest._notability_score(us) > ingest._notability_score(school)
    assert ingest._notability_score(capped) < ingest._notability_score(open_)
    many_mx = [dict(open_, name=f"Copa {i}", countryCode="MX") for i in range(15)]
    ranked = ingest._rank_notable(many_mx + [school])
    assert sum(t["countryCode"] == "MX" for t in ranked[: ingest.MAX_PER_COUNTRY + 1]) == ingest.MAX_PER_COUNTRY
