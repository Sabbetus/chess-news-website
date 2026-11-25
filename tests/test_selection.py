

def test_calendar_item_survives_zero_score(tmp_path, monkeypatch):
    import json, selection
    item = {"kind": "calendar-comingup", "continentCode": "AF", "sourceName": "Chess Tournament Calendar",
            "title": "What's coming up in Africa chess: December 2026", "summary": "", "url": "https://x/af"}
    p = tmp_path / "c.json"; p.write_text(json.dumps([item]))
    monkeypatch.setattr(selection, "CANDIDATES_PATH", p)
    out = tmp_path / "s.json"
    monkeypatch.setattr(selection, "SELECTED_PATH", out, raising=False)
    monkeypatch.setattr(selection, "load_trend_titles", lambda: [])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    selection.main()
    assert "Africa" in out.read_text()


def test_test_listings_are_skipped():
    import ingest
    assert ingest.is_test_listing({"name": "TEST 1"})
    assert not ingest.is_test_listing({"name": "Testa Open"})
    assert not ingest.is_test_listing({"name": "Premier Bet Rwabushenyi Memorial"})


def test_latest_round_named():
    import lichess_game
    assert lichess_game.latest_round_named("After round 6 of the event, and the sixth round") == 6
    assert lichess_game.latest_round_named("Following the eighth round, ...") == 8
    assert lichess_game.latest_round_named("No rounds here") == 0
