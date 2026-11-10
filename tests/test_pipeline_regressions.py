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


def test_game_links_only_link_mainline_moves():
    """2026-10-06: quoted moves link to the board only when they match the
    game's main line at that number and side."""
    import game_links

    pgn = '[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0\n'
    body = "After 2.Nf3 Nc6 and 3.Bb5! Black chose 3...a6, not 3...Nf6. A typo: 2...Nf3."
    out, unmatched = game_links.link_moves(body, pgn)
    assert "[2.Nf3](#ply-3)" in out
    assert "[3.Bb5!](#ply-5)" in out
    assert "[3...a6](#ply-6)" in out
    assert unmatched == ["3...Nf6", "2...Nf3"]
    again, _ = game_links.link_moves(out, pgn)
    assert again == out  # already-linked moves are left alone


def test_game_pgn_picks_and_cleans_the_right_game():
    """2026-10-06: a source PGN with several games is only used when the
    game can be picked unambiguously; annotations never survive."""
    import game_pgn

    two = (
        '[Event "Olympiad"]\n[White "Rapport, Richard"]\n[Black "Demchenko, Anton"]\n[Result "0-1"]\n\n'
        "1. c4 {note} e5 (1... c5) 2. d3 $1 Nf6 0-1\n\n"
        '[Event "Olympiad"]\n[White "Kovalenko, Igor"]\n[Black "Mwadzura, Roy"]\n[Result "1-0"]\n\n'
        "1. c4 e6 2. g3?! Nf6 1-0\n"
    )
    games = game_pgn.split_games(two)
    assert len(games) == 2
    picked = game_pgn.pick_game(games, "", "Igor Kovalenko", "Roy Mwadzura")
    assert "Kovalenko" in picked
    assert game_pgn.pick_game(games, "Nothing about either game.") is None
    assert game_pgn.pick_game(games, "Rapport beat... no, Demchenko won.") == games[0]
    cleaned = game_pgn.clean_game(games[0])
    assert cleaned.endswith("1. c4 e5 2. d3 Nf6 0-1\n")
    assert "{" not in cleaned and "(" not in cleaned


def test_lichess_search_queries_drop_words_the_search_cannot_match():
    """2026-10-06: Lichess's broadcast search needs every word to match, so
    'Fagernes International Autumn Tournament 2026' found nothing."""
    import lichess_game

    q = lichess_game._search_queries("Fagernes International Autumn Tournament 2026")
    assert q[0] == "Fagernes International Autumn 2026"
    assert "Fagernes 2026" in q and "Fagernes" in q
    q = lichess_game._search_queries("46th Chess Olympiad Samarkand 2026")
    assert q[0] == "Olympiad Samarkand 2026" and "Olympiad 2026" in q


def test_calendar_small_field_penalty_only_for_known_counts():
    from ingest import _notability_score

    base = {"name": "Open X", "timeControl": "classical", "startDate": "2026-09-01", "endDate": "2026-09-05"}
    assert _notability_score({**base, "playersRegistered": 6}) < _notability_score(base)
    assert _notability_score({**base, "playersRegistered": 0}) == _notability_score(base)


def test_calendar_sections_merge_and_youth_words():
    from ingest import MINOR_NAME_PATTERNS, _merge_sections

    assert MINOR_NAME_PATTERNS.search("Campeonato Intercolegiado 2026")
    common = {"countryCode": "AR", "city": "Rosario", "startDate": "2026-09-11"}
    pool = [
        {**common, "name": "Abierto Rosario - Grupo A", "playersRegistered": 40},
        {**common, "name": "Abierto Rosario - Grupo B", "playersRegistered": 30},
    ]
    merged = _merge_sections(pool)
    # One entry, keeping its own count: never the sections' sum.
    assert len(merged) == 1 and merged[0]["playersRegistered"] == 40


def test_aggregate_facts_lists_event_lengths():
    from draft import aggregate_facts

    facts = aggregate_facts([
        {"name": "Tigre", "startDate": "2026-09-04", "endDate": "2026-09-12"},
        {"name": "Rosario", "startDate": "2026-09-11", "endDate": "2026-09-20"},
    ])
    assert "Longest event: 10 days (Rosario)" in facts


def test_aggregate_facts_gives_whole_month_formats():
    from draft import aggregate_facts

    facts = aggregate_facts([{"name": "A", "timeControl": "classical"}], {"rapid": 514, "classical": 123}, 640)
    assert "All 640 tracked events this month, by format: rapid 514, classical 123" in facts


def test_social_copy_never_contains_chess_com_domain():
    from social_text import delink

    assert delink("Chess.com's Titled Tuesday on chess.com") == "Chesscom's Titled Tuesday on chesscom"


def test_person_caption_only_for_people():
    from images import person_caption

    url = "https://commons.wikimedia.org/wiki/File%3A"
    assert person_caption(url + "Rinat_Jumabayev_3rd_Uzchess_cup.jpg", ["Christian Gloeckler", "Rinat Jumabayev"]) == "Rinat Jumabayev"
    assert person_caption(url + "2021-Matthias-Bluebaum.JPG", ["Matthias Blübaum"]) == "Matthias Blübaum"
    assert person_caption(url + "FIDE_text_on_white.svg", ["FIDE"]) is None
    assert person_caption(url + "Jack_visits_Mamaia_again_in_the_World_Youth_Chess_Championships_2022.jpg", ["World Youth"]) is None


def test_us_championship_preview_beats_product_review():
    from selection import is_promotional, score_item

    preview = {"sourceName": "ChessBase", "sourceTier": "tier2", "kind": "news",
               "title": "Fabiano Caruana targets fifth consecutive US title",
               "summary": "When Fabiano Caruana begins his title defence at the 2026 US Championship in Saint Louis..."}
    review = {"sourceName": "ChessBase", "title": "Review: Robert Ris' FritzTrainers on openings",
              "summary": "Scandinavian Defence repertoire"}
    assert is_promotional(review)
    assert score_item(preview)[1]["majorTournament"] > 0
    assert "nordic" not in score_item(review)[1]


def test_player_title_is_not_a_major_event():
    from selection import score_major_tournament

    assert score_major_tournament("Dubov, the former world rapid chess champion, accepts a bullet challenge") == 0
    assert score_major_tournament("Caruana begins his title defence at the US Championship") > 0


def test_background_links_always_offered_and_event_links_checked():
    from draft import background_link_targets, check_article_links

    urls = {t["url"] for t in background_link_targets()}
    assert "/articles/chess-titles/" in urls
    assert "/events/chess-olympiad/#how-it-works" in urls
    assert not any("weekly-recap" in u for u in urls)
    body = "[a GM norm](/articles/chess-titles/) and [the format](/events/made-up-event/#how-it-works)"
    assert check_article_links(body) == ["/events/made-up-event/"]


def test_short_surname_must_match_photo():
    from images import _title_matches_query

    assert not _title_matches_query("File:Wesley_moraes_ferreira_da_silva-1556197874.jpg", "Wesley So", True)
    assert _title_matches_query("File:Wesley_So_Tata_2023_-_63.jpg", "Wesley So", True)


def test_passing_olympiad_mention_is_not_a_major_event_story():
    from selection import score_item

    freestyle = {"sourceName": "Chess.com", "title": "Maghsoodloo Wins Star-Studded Freestyle Friday",
                 "summary": "GM Parham Maghsoodloo took a step closer to qualifying for the 2027 FIDE Freestyle "
                            "Chess World Championship by taking out the latest edition of Freestyle Friday. He "
                            "scored 9/11, losing only to one of Uzbekistan's Olympiad heroes."}
    report = {"sourceName": "ChessBase", "title": "US Championships: So and Liang remain perfect",
              "summary": "Two players remain perfect after the second round of the US Chess Championship, 2-0."}
    assert score_item(freestyle)[1]["majorTournament"] == 0
    assert score_item(report)[1]["majorTournament"] > 0


def test_earlier_round_report_dropped_when_later_round_in_batch():
    from selection import drop_superseded_rounds

    r1 = {"sourceName": "Chess.com", "title": "So Starts U.S. Championship With Win",
          "summary": "So won in the first round of the 2026 U.S. Chess Championship."}
    r2 = {"sourceName": "Chess.com", "title": "So, Liang Lead",
          "summary": "So and Liang won again in round two of the 2026 U.S. Chess Championship."}
    assert drop_superseded_rounds([r1, r2]) == [r2]


def test_round_report_picks_the_lead_game():
    from game_pgn import pick_game

    g1 = '[Event "x"]\n[White "Sevian, Samuel"]\n[Black "Liang, Awonder"]\n\n1. e4 e5 1-0'
    g2 = '[Event "x"]\n[White "So, Wesley"]\n[Black "Xiong, Jeffery"]\n\n1. d4 d5 1-0'
    body = "Liang beat Sevian in a King's Indian Attack. Later, So beat Xiong."
    assert pick_game([g2, g1], body) == g1


def test_social_copy_fits_on_x():
    from social_text import X_COPY_LIMIT, fit_for_x

    long = ("Two perfect records, one tiebreak. Viernheim and Baden-Baden both have 6 match points in the "
            "Bundesliga, but Viernheim's 17½ board points, four more than Baden-Baden's, put the defending "
            "champions on top. Bayern sit third on 5, and 18-year-old Matic Lavrencic is 3/3.")
    copy, ok = fit_for_x(long)
    assert ok and len(copy) <= X_COPY_LIMIT and copy.endswith(".")


def test_novelty_marker_does_not_shift_move_links():
    from game_links import link_moves
    from game_pgn import clean_game

    pgn = clean_game('[Event "x"]\n[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Nf3 Nc6 N 3. Bb5 a6 1-0')
    body, unmatched = link_moves("After 3.Bb5 Black played 3...a6.", pgn)
    assert not unmatched and "(#ply-5)" in body and "(#ply-6)" in body


def test_follow_up_bonus_only_for_followed_events():
    from selection import score_follow_up

    words = {"fagernes"}
    assert score_follow_up({"title": "Fagernes: Jumabayev takes title"}, words) > 0
    assert score_follow_up({"title": "Fagernes: round 8 report"}, words) == 0
    assert score_follow_up({"title": "Yu Yangyi wins Shenzhen Masters"}, words) == 0


def test_same_event_round_reports_reach_the_merge_check():
    # 2026-10-20: a player-led Club Cup round 3 headline never got a merge check.
    erdogmus = {"title": "15-Year-Old Erdogmus Climbs To World No. 15",
                "summary": "GM Yagiz Kaan Erdogmus is now world number-15 after winning on his 2026 European Chess Club Cup debut."}
    chessbase = {"title": "European Club Cup: Favourites set for direct encounters",
                 "summary": "Eleven teams remain tied for first place after three rounds."}
    other = {"title": "Rookie Rachael Li Leads Women", "summary": "Round nine of the U.S. Chess Championship."}
    assert selection._same_major_event(erdogmus, chessbase)
    assert not selection._same_major_event(erdogmus, other)


def test_fan_side_event_notices_are_skipped():
    assert selection.is_promotional({"title": "Where chess meets its fans: Join side activities of the Salesforce FIDE World Championship Match", "sourceName": "FIDE"})
    assert selection.is_promotional({"title": "Meet the legends in Geneva", "sourceName": "FIDE",
                                     "summary": "Registration details at: https://tickets.fide.com/en/events"})
    assert not selection.is_promotional({"title": "So, Li Lead By Full Point Ahead Of Final Round", "sourceName": "Chess.com"})


def test_photo_cooldown_matches_front_page():
    import re as _re
    page = open("src/pages/index.astro").read()
    secondary = int(_re.search(r"rest\.slice\(0,\s*(\d+)\)", page).group(1))
    assert draft.FRONT_PAGE_SIZE == 1 + secondary
    assert draft.RECENT_IMAGE_COOLDOWN == draft.FRONT_PAGE_SIZE


def test_fact_check_gets_who_is_who_rule_and_title_holders():
    # 2026-10-22: "defending champion" (Caruana in the source) was given to So.
    assert "Who each description belongs to" in draft._CLAIM_VERIFICATION_PROMPT
    note = draft.title_holders_note()
    assert "U.S. Chess Championship: Wesley So won the 2026 edition" in note
    assert "World Chess Championship: Gukesh Dommaraju" in note

    sent = {}

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                sent.update(kwargs)
                raise RuntimeError("stop")

    parsed = {"title": "T", "socialCopy": "S", "metaDescription": "M", "bodyMarkdown": "B"}
    item = {"kind": "news", "title": "T", "sourceName": "Chess.com", "summary": "text"}
    draft.verify_claims(FakeClient(), parsed, item)
    assert "OUR RECORDS" in sent["messages"][0]["content"]


def test_opening_paragraph_names_the_event():
    # 2026-10-22: four U.S. Championship round reports never named the event
    # in their body, so the build-time event link had nothing to attach to.
    assert "Naming the event" in draft.NEWS_SYSTEM_PROMPT
    assert "Event name: if the piece is about a tournament" in draft._CLAIM_VERIFICATION_PROMPT


def test_published_final_results_match_event_pages():
    import glob, json as _json, re as _re
    import event_results
    for path in glob.glob("src/content/articles/*.md"):
        text = open(path).read()
        if 'reviewStatus: "published"' not in text:
            continue
        m = _re.search(r'^eventResult: \{ event: "(.*?)", year: (\d{4}), winners: (\[.*?\]) \}$', text, _re.MULTILINE)
        if not m:
            continue
        listed = event_results.page_winners(m.group(1))
        assert listed.get(int(m.group(2))) == _json.loads(m.group(3)), path


def test_event_result_updates_the_page(tmp_path, monkeypatch):
    import event_results
    page = tmp_path / "demo-open.md"
    page.write_text(
        '---\nname: "Demo Open"\nnextEdition:\n  label: "Demo Open 2026"\n  start: "2026-10-08"\n'
        '  end: "2026-10-23"\nwinners:\n  - { year: 2025, names: ["A B"] }\n'
        'reviewStatus: "published"\nupdatedDate: "2026-01-01"\n---\n'
    )
    monkeypatch.setattr(event_results, "EVENTS_DIR", tmp_path)
    result = event_results.parse("demo-open | 2026 | C D")
    assert result == {"event": "demo-open", "year": 2026, "winners": ["C D"]}
    assert "added" in event_results.apply(result, "2026-10-23")
    assert event_results.page_winners("demo-open") == {2026: ["C D"], 2025: ["A B"]}
    text = page.read_text()
    assert "nextEdition" not in text and 'updatedDate: "2026-10-23"' in text
    assert event_results.parse("unknown-event | 2026 | C D") is None
    assert event_results.parse("") is None


def test_final_result_updates_the_winners_player_page(tmp_path, monkeypatch):
    import types as _types
    import event_results
    events, players = tmp_path / "events", tmp_path / "players"
    events.mkdir(); players.mkdir()
    (events / "demo-open.md").write_text('---\nname: "Demo Open"\nreviewStatus: "published"\n---\n')
    (players / "c-d.md").write_text(
        '---\nname: "C D"\naliases:\n  - "C D"\nhighlights:\n  - "Two-time Demo Open winner"\n'
        'reviewStatus: "published"\nupdatedDate: "2026-01-01"\n---\n\nC D has won the Demo Open twice.\n'
    )
    monkeypatch.setattr(event_results, "EVENTS_DIR", events)
    monkeypatch.setattr(event_results, "PLAYERS_DIR", players)
    reply = "@@HIGHLIGHTS@@\nThree-time Demo Open winner\n@@BODY@@\nC D has won the Demo Open three times."

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                return _types.SimpleNamespace(content=[_types.SimpleNamespace(type="text", text=reply)])

    notes = event_results.update_player_pages(
        FakeClient(), "m", {"event": "demo-open", "year": 2026, "winners": ["C D", "No Page"]}, "T", "B", "2026-10-23"
    )
    assert len(notes) == 1 and "updated" in notes[0]
    text = (players / "c-d.md").read_text()
    assert '- "Three-time Demo Open winner"' in text and "three times" in text
    assert 'updatedDate: "2026-10-23"' in text and 'name: "C D"' in text


def test_paragraph_split_never_breaks_a_quote():
    assert draft._quotes_balanced('He said "Kudos to Sam. He had a tough tournament."')
    assert not draft._quotes_balanced('He said "Kudos to Sam. He had a tough tournament.')


def test_pipeline_commits_event_and_player_page_edits():
    # 2026-10-23: the event and player page updates were made on the runner
    # but never committed (git add covered only src/content/articles/).
    workflow = open(".github/workflows/pipeline.yml").read()
    assert "git add data/ src/content/\n" in workflow


def test_finnish_section_only_for_club_cup_headlines():
    import club_cup
    assert club_cup.is_club_cup({"title": "Leaders Caught As 3 Teams Tie For Top Before Euro Club Cup Final Round"})
    assert club_cup.is_club_cup({"title": "European Club Cup: Novy Bor and SuperChess remain perfect"})
    assert not club_cup.is_club_cup({"title": "Bodhana, 11, Breaks Judit Polgar's Record To Become Youngest Female IM",
                                     "summary": "securing her third norm at the European Club Cup in Budva"})


def test_milestone_without_subject_photo_uses_next_person(monkeypatch):
    # 2026-10-24: Bodhana's IM record got a generic board; Polgar was next.
    calls = []

    def fake_search(query, *args):
        calls.append(query)
        return {"url": "u", "sourceUrl": "s"} if "Polgar" in query else None

    monkeypatch.setattr(images, "search_image", fake_search)
    monkeypatch.setattr(images, "fallback_image", lambda *a, **k: {"src": "pool"})
    item = {"kind": "news", "sourceName": "Chess.com", "title": "Bodhana, 11, Breaks Polgar's Record", "lens": "results", "summary": ""}
    got = images.pick_image_for_item(item, item["title"], ["Bodhana Sivanandan", "Judit Polgar"], set(), prefer_neutral=True)
    assert got == {"url": "u", "sourceUrl": "s"}
    assert any("Bodhana" in q for q in calls)


def test_old_top_hits_fall_back_to_newest_uploads(monkeypatch):
    # 2026-10-25: Nakamura's top Commons hits were all 2008-2016, dropped by
    # the recency rule, so the piece got a pool photo; newer ones exist.
    calls = []

    def fake_titles(query, limit=5, newest=False):
        calls.append(newest)
        return ["File:New.jpg"] if newest else ["File:Old.jpg"]

    def fake_fetch(titles, *a, **k):
        return {"sourceUrl": "new"} if titles == ["File:New.jpg"] else None

    monkeypatch.setattr(images, "_search_titles", fake_titles)
    monkeypatch.setattr(images, "_fetch_first_licensed_file", fake_fetch)
    assert images.search_image("Hikaru Nakamura") == {"sourceUrl": "new"}
    assert calls == [False, True]
    calls.clear()
    assert images.search_image("Hikaru Nakamura", historical=True) is None
    assert calls == [False]


def test_old_game_on_a_current_story_gets_a_caption():
    # 2026-10-26: the Clutch Chess preview showed a 2025 game unexplained.
    old = '[Event "Clutch Chess Champions Showdown 2025"]\n[Date "2025.10.27"]\n'
    assert draft.game_caption(old, "money-angle", 2026) == "From the Clutch Chess Champions Showdown 2025"
    assert draft.game_caption(old.replace(" 2025\"", "\""), "news", 2026) == "From the Clutch Chess Champions Showdown, 2025"
    assert draft.game_caption(old, "historical-parallel", 2026) is None
    assert draft.game_caption(old.replace("2025.", "2026."), "news", 2026) is None


def test_organisation_bylines_and_signup_pitches_are_skipped():
    # 2026-10-27: "by Kasparov Chess Foundation", a 2027 sign-up pitch.
    import article_text
    assert article_text.is_press_release_page('<span class="blog-author-line">by Kasparov Chess Foundation</span>')
    assert article_text.is_press_release_page('<span class="blog-author-line">by Press release</span>')
    assert not article_text.is_press_release_page('<span class="blog-author-line">by Johannes Fischer</span>')
    assert selection.is_promotional({"title": "KCF Academy: Third Season Highlights",
                                     "summary": "For more information and to join, visit kcfacademy.org"})


def test_club_prefix_is_not_an_organisation_logo():
    # 2026-10-27: "SK Weisse Dame Hamburg" searched for an "SK" logo.
    assert not images._is_organisation("SK Weisse Dame Hamburg")
    assert images._organisation_name("FIDE Council") == "FIDE"


def test_finnish_section_only_on_club_cup_results():
    # 2026-10-27: an amateur's post-event diary repeated the final's section.
    import club_cup
    assert not club_cup.is_club_cup({"title": "European Club Cup: Amateurs rub shoulders with the pros"})
    assert club_cup.is_club_cup({"title": "European Club Cup 2026: Round 3"})
    assert club_cup.is_club_cup({"title": "Bayegan Pendik and Monte-Carlo are 2026 European Club Cup champions"})


def test_reports_naming_the_same_event_reach_the_merge_check():
    # 2026-10-28: both Clutch Chess day-one reports were drafted.
    a = {"title": "Clutch Chess: Nakamura leads after lively first day of action",
         "summary": "Hikaru Nakamura took the early lead at the Clutch Chess: Champions Showdown tournament"}
    b = {"title": "Nakamura Leads After Wins Vs. Caruana & Praggnanandhaa",
         "summary": "GM Hikaru Nakamura leads by half a point after day one of Clutch Chess: Champions Showdown 2026."}
    assert selection._same_major_event(a, b)


def test_board_link_only_on_a_move_of_the_embedded_game():
    # 2026-10-28: 58...hxg5 (game 1) was linked to the embedded game 2.
    import game_links
    pgn = '[Event "x"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *'
    body = "First [2...d6](#game-embed) in another game, then 3...a6 here."
    assert game_links.fix_embed_link(body, pgn) == "First 2...d6 in another game, then [3...a6](#game-embed) here."


def test_editor_notes_are_stripped_from_the_body():
    # 2026-10-28: "The leads and format text are unchanged below, with one link added."
    body = "The leads and format text are unchanged below, with one link added.\n\nNakamura leads."
    assert draft.strip_editor_notes(body) == "Nakamura leads."


def test_quoted_moves_pick_the_game_among_a_pairs_games():
    # 2026-10-28: Clutch Chess pairs two players twice per round.
    import lichess_game
    game1 = '[Event "x"]\n\n1. e4 e5 2. Nf3 Nc6 *'
    game2 = '[Event "x"]\n\n1. d4 d5 2. c4 e6 *'
    body = "After 1.e4 e5 2.Nf3 the game was level."
    assert lichess_game._quoted_moves_in(game1, body) == 2
    assert lichess_game._quoted_moves_in(game2, body) == 0


def test_ongoing_event_gets_the_follow_up_bonus():
    # 2026-10-29: Clutch Chess day two scored 40 the day after day one ran.
    item = {"title": "Praggnanandhaa Jumps From Last To 1st With Hat Trick",
            "summary": "GM Praggnanandhaa Rameshbabu is at the top of Clutch Chess: Champions Showdown 2026 after day two."}
    assert selection.score_follow_up(item, recent_events={"clutch champions showdown"}) == selection.FOLLOW_UP_ONGOING_BONUS
    assert selection.score_follow_up(item, recent_events={"tata steel masters"}) == 0


def test_chessbase_shop_columns_are_promotional():
    # 2026-10-29: "Dragons of the Olympiad 2026 - The Monthly Dragon".
    assert selection.is_promotional({"title": "Dragons of the Olympiad 2026 - The Monthly Dragon", "sourceName": "ChessBase"})
    assert selection.is_promotional({"title": "Some column", "summary": "his three FritzTrainers in our ChessBase shop"})


def test_business_named_files_are_not_person_photos():
    # 2026-10-29: "Chris Ward Autos in Tangier Road - geograph.org.uk".
    assert images._BUSINESS_OR_STREET_RE.search("File:Chris Ward Autos in Tangier Road - geograph.org.uk - 859647.jpg")
    assert not images._BUSINESS_OR_STREET_RE.search("File:Rameshbabu Praggnanandhaa in 2023 (52638384854).jpg")


def test_lichess_lookup_gets_the_body_that_exists():
    # 2026-10-29: find_game_embed was passed body_markdown before it existed.
    import inspect
    source = inspect.getsource(draft)
    call = source[source.index("embed = find_game_embed("):][:300]
    assert "body_for_recheck" in call and "body_markdown" not in call


def test_event_headlines_with_a_colon_are_not_profiles():
    # 2026-10-29: "KazChess Masters: ..." got the +40 feature bonus.
    assert not selection.is_feature_story({"sourceName": "ChessBase", "title": "KazChess Masters: Mamedov and Makhnev set the pace in Almaty"})
    assert not selection.is_feature_story({"sourceName": "ChessBase", "title": "Clutch Chess: Nakamura leads after lively first day of action"})


def test_elite_field_outscores_a_regular_masters():
    # 2026-10-29: Clutch Chess (Caruana, Nakamura, Pragg, Sindarov) scored
    # below the KazChess Masters.
    item = {"title": "Praggnanandhaa Jumps From Last To 1st With Hat Trick",
            "summary": "Praggnanandhaa won twice against Hikaru Nakamura and once against Fabiano Caruana. Javokhir Sindarov is second."}
    assert selection.score_elite_field(item) == selection.ELITE_FIELD_BONUS[3]
    assert selection.score_elite_field({"title": "Mamedov and Makhnev lead in Almaty", "summary": "Dubov is half a point back."}) == 0


def test_player_page_photo_is_used_for_a_named_player():
    # 2026-10-29: KazChess got a generic photo though Dubov has a page photo.
    photo = images.player_page_photo("Daniil Dubov", set())
    assert photo and photo["src"].startswith("./_images/")
    assert images.player_page_photo("Daniil Dubov", {photo["sourceUrl"]}) is None


def test_pair_lookup_prefers_the_last_decisive_game(monkeypatch):
    # 2026-10-30: the Clutch final's King's Indian win (game 17) lost to the
    # game-18 draw between the same pair.
    import lichess_game

    pgn = (
        '[White "Nakamura, Hikaru"]\n[Black "Sindarov, Javokhir"]\n[Result "0-1"]\n[GameURL "u/win"]\n\n1. d4 Nf6 0-1\n\n\n'
        '[White "Sindarov, Javokhir"]\n[Black "Nakamura, Hikaru"]\n[Result "1/2-1/2"]\n[GameURL "u/draw"]\n\n1. e4 e5 1/2-1/2'
    )

    class R:
        text = pgn
        def raise_for_status(self):
            pass

    monkeypatch.setattr(lichess_game.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(lichess_game, "_article_body", "")
    assert lichess_game.find_game_in_round("r", "Hikaru Nakamura", "Javokhir Sindarov") == "u/win"


def test_single_game_needs_its_players_named():
    # 2026-10-31: the only game read (the page's first file) was used though
    # the article never names Papapostolou.
    import game_pgn
    game = '[White "Papapostolou, Christos"]\n[Black "Myagmarsuren, Lhamsuren"]\n\n1. e4 c5 0-1'
    assert game_pgn.pick_game([game], "Fischer beat Myagmarsuren at Sousse.") is None
    fischer = game.replace("Papapostolou, Christos", "Fischer, Robert James")
    assert game_pgn.pick_game([game, fischer], "Fischer beat Myagmarsuren at Sousse.") == fischer
    pragg = '[White "Praggnanandhaa R"]\n[Black "Sindarov, Javokhir"]\n\n1. e4 0-1'
    assert game_pgn.pick_game([pragg], "Sindarov beat Praggnanandhaa.") == pragg


def test_chess960_games_keep_their_start_position():
    # 2026-10-31: the cleaner dropped a Freestyle Friday game's FEN, and the
    # board couldn't replay "O-O". The start position now stays with the game.
    import game_pgn
    g960 = ('[White "Movahed, Sina"]\n[Black "Yakubboev, Nodirbek"]\n[Variant "Chess960"]\n[SetUp "1"]\n'
            '[FEN "brqnnkrb/pppppppp/8/8/8/8/PPPPPPPP/BRQNNKRB w GBgb - 0 1"]\n\n1. d4 b5 1-0')
    cleaned = game_pgn.clean_game(g960)
    assert '[Variant "Chess960"]' in cleaned and '[FEN "brqnnkrb/' in cleaned


def test_headline_names_the_person_in_the_photo():
    # 2026-10-31: runner-up Yakubboev's photo under "Movahed Wins Freestyle
    # Friday After Starting 1.5/3".
    class Block:
        type = "text"
        def __init__(self, text):
            self.text = text

    class Client:
        def __init__(self, reply):
            self.messages = self
            self.reply = reply
        def create(self, **kwargs):
            return type("R", (), {"content": [Block(self.reply)]})()

    old = "Movahed Wins Freestyle Friday After Starting 1.5/3"
    new = "Movahed Beats Leader Yakubboev to Win Freestyle Friday"
    assert draft.match_title_to_photo(Client(new), old, "body", "Nodirbek Yakubboev") == new
    # Already named, or a reply that doesn't name him: the headline stays.
    assert draft.match_title_to_photo(Client(new), new, "body", "Nodirbek Yakubboev") == new
    assert draft.match_title_to_photo(Client("Movahed Wins Again"), old, "body", "Nodirbek Yakubboev") == old


def test_photo_cooldown_leaves_room_for_this_runs_drafts(monkeypatch):
    # 2026-11-01: a photo on a piece four new drafts would push off the
    # front page still blocked Dubov's player-page photo.
    monkeypatch.setattr(draft, "_session_used_urls", set())
    monkeypatch.setattr(draft, "_batch_size", 0)
    full = draft.used_image_source_urls()
    monkeypatch.setattr(draft, "_batch_size", 4)
    shorter = draft.used_image_source_urls()
    assert shorter <= full and len(shorter) < len(full)


def test_titles_never_use_semicolons():
    assert draft.no_semicolons("So and Liang Lead Open at 2/2; Bottom Seeds Top the Women") == \
        "So and Liang Lead Open at 2/2, Bottom Seeds Top the Women"
    import glob
    for path in glob.glob("src/content/articles/*.md"):
        title = next(line for line in open(path) if line.startswith("title:"))
        assert ";" not in title, path


def test_sentence_counter_handles_moves_and_abbreviations():
    from draft import count_sentences

    assert count_sentences("White's 17.f5? was a mistake. After 17...Nb4! 18.Rg1? Wei won.") == 2
    assert count_sentences("She played 37.Qxf2 rather than the engine's 37.Qg1. Sargsyan then erred.") == 2
    assert count_sentences("The U.S. Championship resumes at 1 p.m. ET. Dr. Seven agreed.") == 2


def test_published_articles_respect_paragraph_limits():
    """Every article published from 2026-10-19 on (when the 350-character /
    3-sentence limits came in) -- this also covers hand edits made during
    review, which never pass through draft.py's own check."""
    import re
    from pathlib import Path

    from draft import check_paragraph_lengths

    articles = Path(__file__).resolve().parent.parent / "src" / "content" / "articles"
    problems = []
    for path in articles.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        date = re.search(r'^publishDate:\s*"(\d{4}-\d{2}-\d{2})"', text, re.MULTILINE)
        if 'reviewStatus: "published"' not in text or not date or date.group(1) < "2026-10-19":
            continue
        offenders = check_paragraph_lengths(text.split("---", 2)[2])
        if offenders:
            problems.append(f"{path.stem}: {offenders}")
    assert not problems, "\n".join(problems)


def test_rating_list_story_gets_score_bonus():
    total, breakdown = selection.score_item(news("Sindarov Leads On November FIDE Rating List"))
    assert breakdown["ratingList"] == selection.RATING_LIST_BONUS
    _, other = selection.score_item(news("Carlsen and Abdusattorov prepare for Total Chess"))
    assert other["ratingList"] == 0


# --- 2026-11-02: Chess.com body cut at a table; illegal written lines ---


def test_chesscom_text_reads_past_nested_divs():
    from article_text import extract_chesscom_text

    page = (
        '<div class="post-view-content"><p>Firouzja won on 170.</p>'
        '<div class="table-content-responsive"><table><tr><td>1</td><td>Firouzja</td></tr></table></div>'
        '<div class="chess-viewer"><script>x()</script></div>'
        "<p>Carlsen also played, from Spain.</p></div><div><p>Footer</p></div>"
    )
    text = extract_chesscom_text(page)
    assert "Carlsen also played" in text and "1 | Firouzja" in text
    assert "Footer" not in text and "x()" not in text


def test_written_line_is_linked_only_if_every_move_is_the_games():
    import game_links

    pgn = '[Event "?"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *'
    body, unmatched = game_links.link_moves("Caro-Kann: 1.e4 c6 2.d4 d5. Here 1.e4 e5 2.Nf3 came.", pgn)
    assert "Caro-Kann: 1.e4 c6 2.d4" in body and "[2.Nf3](#ply-3)" in body
    assert unmatched == ["1.e4", "2.d4"]


def test_illegal_written_lines_are_reported():
    from game_links import illegal_lines

    assert illegal_lines("Panov: 1.e4 c6 2.d4 d5 3.cxd5 cxd5 4.c4.") == ["1.e4 c6 2.d4 d5 3.cxd5"]
    assert illegal_lines("Panov: 1.e4 c6 2.d4 d5 3.exd5 cxd5 4.c4, and 1.d4 Nf6.") == []


def test_arena_game_picked_by_quoted_moves():
    from game_pgn import pick_game

    first = '[White "Alireza Firouzja"]\n[Black "Hikaru Nakamura"]\n[Result "0-1"]\n\n1. e4 e5 2. Nc3 Nc6 0-1'
    decider = '[White "Hikaru Nakamura"]\n[Black "Alireza Firouzja"]\n[Result "0-1"]\n\n1. e4 c6 2. Nc3 d6 0-1'
    body = "Firouzja beat Nakamura with the Caro-Kann, answering with 2...d6."
    assert pick_game([first, decider], body) == decider



def test_bot_promotions_are_skipped():
    assert selection.is_promotional(news("Challenge the Grand Chess Auto Bots"))
    assert selection.is_promotional(news("Meet Our New Halloween Bots"))



def test_lichess_name_tokens_drop_region_tags():
    import lichess_game
    assert "tong" in lichess_game._tag_tokens("Xiao, Tong(QD)")


def test_knockout_board_takes_last_decisive_game():
    from game_pgn import pick_game
    g = lambda w, b, r: f'[White "{w}"]\n[Black "{b}"]\n[Result "{r}"]\n\n1. e4 e5 {r}'
    games = [g("Xiao, Tong", "Ding, Liren", "1/2-1/2"), g("Ding, Liren", "Xiao, Tong", "1/2-1/2"), g("Xiao, Tong", "Ding, Liren", "1-0")]
    assert pick_game(games, "Ding Liren lost to Xiao Tong in blitz.")[-30:].endswith("1-0")


def test_retitle_keeps_headline_lead_name():
    assert draft._headline_lead_name("Besou, 15, Beats Peter Acs", "Hussain Besou beat Acs.") == "Besou"
    assert draft._headline_lead_name("Five Players Start 3/3", "Five players lead.") == ""


def test_event_page_bonus_for_events_with_a_page():
    assert selection.score_event_page("Bavarian Championship: 15-year-old Besou joins the leaders") == selection.EVENT_PAGE_BONUS
    assert selection.score_event_page("Rilton Cup: Xu Xiangyu wins") == selection.EVENT_PAGE_BONUS
    assert selection.score_event_page("Firouzja wins Titled Tuesday") == 0


def test_anniversary_features_get_the_smaller_bonus():
    assert selection.is_anniversary_story(news("Eugenio Torre: Asia's first grandmaster turns 75"))
    assert selection.is_anniversary_story(news("Vasily Panov", "Born on 1 November 1906, Vasily Panov was..."))
    assert not selection.is_anniversary_story(news("Hou Yifan opens up about her return"))


def test_place_named_after_a_person_is_not_their_photo():
    url = "https://commons.wikimedia.org/wiki/File%3A2024-07-20_Entrance_to_Nona_Gaprindashvili_Chess_Palace.jpg"
    assert images.person_caption(url, ["Nona Gaprindashvili"]) is None
    assert images.person_caption("https://commons.wikimedia.org/wiki/File%3APeter_Leko_2025.jpg", ["Peter Leko"]) == "Peter Leko"


def test_photo_year_takes_the_earlier_of_date_and_file_name():
    assert images.photo_year({"photoDate": "2019-04-01", "sourceUrl": "https://x/File%3APia_Cramling_2016.jpg"}) == "2016"
    assert images.photo_year({"photoDate": "0000-00-00", "sourceUrl": "https://x/File%3ACramling.jpg"}) == ""


def test_logo_word_alone_does_not_match_unrelated_logo():
    # 2026-11-07: "Facebook f logo (2019).svg" was picked for a Bavarian
    # Championship piece on the word "logo" alone.
    import images
    assert not images._title_matches_query(
        "File:Facebook f logo (2019).svg", "Bavarian Chess Championship logo", False
    )
    assert images._title_matches_query("File:FIDE text on white.svg", "FIDE logo", False)


def test_event_scoring_weekly_online_vs_live_events():
    # 2026-11-07 (user's call): Freestyle Friday (115) topped the batch and
    # an Esports World Cup 2027 announcement (91) beat a live Bavarian
    # Championship round (70).
    import selection as s
    assert s.is_weekly_online("Yakubboev Continues Freestyle Friday Championship Push")
    assert not s._mentions_major_event("chess returns to esports world cup in 2027")
    assert s._mentions_major_event("the fide world cup final")
    weekly, _ = s.score_item({"title": "Yakubboev Wins Freestyle Friday", "summary": "GM Nodirbek Yakubboev won Freestyle Friday.", "sourceTier": "major"})
    bavarian, b = s.score_item({"title": "Bavarian Championship: Gopal emerges as sole leader", "summary": "Gopal leads after round six.", "sourceTier": "major"})
    assert b["liveEvent"] == s.LIVE_EVENT_BONUS
    assert bavarian > weekly


def test_repeated_headline_phrase():
    import draft
    body = "Gopal leads. Twelve players are half a point back, among them Piorun."
    assert draft.repeated_headline_phrase(
        "Gopal Leads, Piorun Among 12 Half a Point Back", body, ["Gaprindashvili Half a Point Back in the Women 65+"]
    ) == "Half a Point Back"
    assert draft.repeated_headline_phrase(
        "Gopal Leads, Piorun Among 12 Half a Point Behind", body, ["Gaprindashvili Half a Point Back in the Women 65+"]
    ) is None


def test_quality_floor_and_headline_window():
    import draft
    import selection
    assert selection.MIN_PUBLISH_SCORE == 50
    assert draft.RECENT_HEADLINE_DAYS == 14


def test_social_copy_phrase_check_ignores_scores():
    import draft
    body = "Begmuratov won on 7.5/9. Twelve players are half a point back."
    assert draft.repeated_headline_phrase("Begmuratov won on 7.5/9 without a loss.", body, ["Svane scored 6/9 without a loss."]) is None
    assert draft.repeated_headline_phrase(
        "Twelve players sit half a point back.", body, ["Gaprindashvili is half a point back in the 65+."]
    ) == "half a point back"


def test_social_queue_withdraws_removed_and_refreshes_pending():
    # 2026-11-07: a removed article was still posted, and a pending post
    # used its old copy.
    import social_post as sp
    queue = [
        {"slug": "gone", "title": "Gone", "socialCopy": "x", "publishDate": "2026-11-07", "selectionScore": 91,
         "postedFacebookAt": None, "postedThreadsAt": None},
        {"slug": "kept", "title": "Old", "socialCopy": "half a point back", "publishDate": "2026-11-07",
         "selectionScore": 70, "postedFacebookAt": None, "postedThreadsAt": None},
    ]
    articles = [{"slug": "kept", "title": "New", "socialCopy": "half a point behind", "publishDate": "2026-11-07",
                 "selectionScore": 125}]
    out = sp.refresh_pending(queue, articles)
    assert out[0]["withdrawn"] is True
    assert out[1]["socialCopy"] == "half a point behind" and out[1]["selectionScore"] == 125


def test_press_release_credit_line_in_story():
    import article_text
    assert article_text.is_press_release_page('<div class="full-story"><p style="text-align: right;"><em>Press release by FIDE</em></p>')
    assert not article_text.is_press_release_page("<p>FIDE issued a press release on Monday.</p>")


def test_headline_game_number():
    import game_pgn
    assert game_pgn.headline_game_number("Bullet Grandpa Wins Game 28 and Spoils Dubov's 100-0 Sweep") == 28
    assert game_pgn.headline_game_number("Carlsen Wins the Final") is None


def test_strip_russia_labels():
    import draft
    assert draft.strip_russia_labels("Russia's Valeria Kleymenova won. Veronika Iudina of Russia was third.") == "Valeria Kleymenova won. Veronika Iudina was third."
    assert draft.strip_russia_labels("GM Evgeny Vorobiov (Russia) scored 8") == "GM Evgeny Vorobiov scored 8"
    assert draft.strip_russia_labels("He left Russia in 2022.") == "He left Russia in 2022."


def test_craft_object_not_a_person_photo_and_rating_list_needs_lead():
    import re
    import images
    import selection
    title = "Mikhail Botvinnik - Mikhail Tal - World Championship 23th Moscovo (6), 1960-03-26 - wood handicraft chess board.JPG"
    assert images._BUSINESS_OR_STREET_RE.search(re.sub(r"[_\W\d]+", " ", title))
    assert not selection.is_rating_list_story({"title": "Gukesh Heads to Geneva", "summary": "x " * 200 + "26th on the FIDE rating list"})
    assert selection.is_rating_list_story({"title": "FIDE Ratings - November 2026", "summary": ""})
