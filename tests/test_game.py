import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import coach  # noqa: E402
import server  # noqa: E402
from cards import parse_cards  # noqa: E402
from game_session import HUMAN, GameError, GameSession  # noqa: E402


def test_draws_and_made_hands():
    d = coach.draws(parse_cards("Ah 5h"), parse_cards("Kh 9h 2c"))
    assert "Nut flush draw" in d["names"] and d["outs"] == 9
    d = coach.draws(parse_cards("9c 8d"), parse_cards("7h 6s 2c"))
    assert "Open-ended straight draw" in d["names"] and d["outs"] == 8
    assert coach.describe_made_hand(parse_cards("Qs Qd"), parse_cards("9h 5c 2d"))[0].startswith("Overpair")
    assert coach.describe_made_hand(parse_cards("Ks Jd"), parse_cards("Kh 5c 2d"))[0].startswith("Top pair")
    assert coach.describe_made_hand(parse_cards("5s 5d"), parse_cards("Kh 5c 2d"))[0].startswith("Set")


def test_nuts():
    n = coach.nuts_analysis(parse_cards("Ah Kh"), parse_cards("Qh Jh Th 2c 3d"))
    assert n["has_nuts"] and n["percentile"] > 0.99
    n = coach.nuts_analysis(parse_cards("2s 7d"), parse_cards("Qh Jh 9h 2c 3d"))
    assert not n["has_nuts"] and n["nut_hand"] == "Straight flush"


def test_full_session_chips_conserved():
    g = GameSession(seed=4)
    rng = random.Random(1)
    for _ in range(40):
        if g.session_info()["busted"]:
            g.rebuy()
        g.new_hand()
        while g.in_hand:
            opts = g._options()
            choice = rng.choice(["fold", "call", "raise"])
            if choice == "raise" and not opts["can_raise"]:
                choice = "call"
            events, fb = g.act(choice, opts.get("pot_to"))
            assert fb["verdict"] in ("Great", "Good", "Okay", "Mistake")
            assert fb["reasons"]
        assert events[-1]["kind"] == "result"
    # your profit is always stack minus total bought in
    assert g.session_info()["profit"] == g.stacks[HUMAN] - g.total_bought


def test_not_your_turn():
    g = GameSession(seed=5)
    try:
        g.act("call")
        assert False
    except GameError:
        pass


def test_api_roundtrip():
    client = server.app.test_client()
    assert client.post("/api/new_session").status_code == 200
    r = client.post("/api/next_hand").get_json()
    assert r["events"]
    snap = r["events"][-1]
    if snap["options"]:
        assert client.get("/api/hint").status_code == 200
        r = client.post("/api/action", json={"action": "fold"}).get_json()
        assert r["feedback"]["verdict"]
    assert client.get("/api/history").status_code == 200
