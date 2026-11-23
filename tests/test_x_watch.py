

def test_blocked_author_and_mentions_are_dropped():
    import x_watch
    acct = {"handle": "chesscom", "kind": "relay"}
    long = " lorem ipsum dolor sit amet consectetur" * 3
    raws = [
        {"id": "1", "text": "Carlsen does not come" + long, "author": {"screen_name": "SergeyKaryakin", "name": "Sergey Karjakin"}},
        {"id": "2", "text": "Karjakin says" + long, "author": {"screen_name": "chesscom"}},
        {"id": "3", "text": "Look at this" + long, "author": {"screen_name": "chesscom"},
         "quote": {"id": "4", "text": "anything" + long, "author": {"screen_name": "SergeyKaryakin"}}},
        {"id": "5", "text": "Firouzja wins" + long, "author": {"screen_name": "chesscom"}},
    ]
    assert [p["id"] for p in x_watch.normalize(raws, acct)] == ["5"]
