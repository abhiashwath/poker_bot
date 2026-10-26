import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mccfr  # noqa: E402
from agents import BASELINES, RandomAgent  # noqa: E402
from cards import evaluate, parse_cards, preflop_index  # noqa: E402
from dealer import (ALLIN, CALL, FOLD, RAISE_HALF, RAISE_POT, Dealer,  # noqa: E402
                    TableState)


def score(s):
    return evaluate(parse_cards(s))


def test_hand_ranking_order():
    hands = [
        "2c 5d 8h Js Kd 3c 4h",   # high card
        "2c 2d 8h Js Kd 3c 4h",   # pair
        "2c 2d 8h 8s Kd 3c 4h",   # two pair
        "2c 2d 2h 8s Kd 3c 4h",   # trips
        "Ah 2d 3c 4s 5h 9d Kc",   # wheel straight
        "6h 2d 3c 4s 5h 9d Kc",   # six-high straight
        "2h 7h 9h Jh Kh 3c 4d",   # flush
        "2c 2d 2h 8s 8d 3c 4h",   # full house
        "2c 2d 2h 2s Kd 3c 4h",   # quads
        "As Ks Qs Js Ts 2d 3c",   # royal flush
    ]
    scores = [score(h) for h in hands]
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores)


def test_kickers_and_ties():
    assert score("Ah Ad Kc 7s 5d 3c 2h") > score("As Ac Qc 7d 5s 3d 2c")
    assert score("Ah Kd 9c 7s 5d 3c 2h") == score("As Kc 9d 7d 5s 3d 2c")
    assert score("9h 9d 9c 4s 4d 4c 2h") == score("9h 9d 9c 4s 4d 2c 2h")  # best full house


def test_preflop_index_is_169_classes():
    idx = {preflop_index([a, b]) for a in range(52) for b in range(52) if a != b}
    assert idx == set(range(169))


def deck(seed=0):
    d = list(range(52))
    random.Random(seed).shuffle(d)
    return d


def test_blinds_and_first_to_act():
    st = TableState.new_hand(9, 4, [200] * 9, deck())
    assert st.contrib[5] == 1 and st.contrib[6] == 2
    assert st.cur == 7                      # UTG acts first preflop
    assert st.legal() == [FOLD, CALL, RAISE_HALF, RAISE_POT, ALLIN]
    # everyone calls to the BB, who then checks: flop starts left of the button
    for _ in range(8):
        st = st.apply(CALL)
    assert st.street == 0 and st.cur == 6   # BB option
    st = st.apply(CALL)
    assert st.street == 1 and st.cur == 5 and st.pot() == 18


def test_pot_sized_raise_amount():
    st = TableState.new_hand(9, 0, [200] * 9, deck())
    # UTG pot raise: call 2 then raise by pot (1 + 2 + 2) -> raise to 7
    assert st.raise_target(RAISE_POT) == 7
    st = st.apply(RAISE_POT)
    assert st.max_bet() == 7 and st.last_raise == 5
    assert st.min_raise_to() == 12


def test_dealer_button_rotates_and_chips_conserved():
    rng = random.Random(3)
    dealer = Dealer(9, stack=200, rng=rng)
    agents = [RandomAgent(rng) for _ in range(9)]
    for _ in range(500):
        b = dealer.button
        net = dealer.play_hand(agents)
        assert sum(net) == 0
        assert dealer.button == (b + 1) % 9


def test_side_pots():
    # seat 0 short-stacked (20), seats 1 and 2 deep; everyone all-in preflop
    top = parse_cards("Ah Ad Kh Kd Qh Qd 2c 7s 9d Jc 3h")  # 3 hands, then the board
    d = top + [c for c in range(52) if c not in top]
    st = TableState.new_hand(3, 2, [20, 100, 100], d)
    while not st.done:
        st = st.apply(ALLIN if ALLIN in st.legal() else CALL)
    net = st.payoffs()
    assert sum(net) == 0
    # AA wins main pot 60 (net +40); KK wins side pot 160 (net +60); QQ loses 100
    assert net == [40, 60, -100]


def test_baselines_play_legal_moves():
    rng = random.Random(5)
    dealer = Dealer(9, rng=rng)
    agents = [cls() for cls in BASELINES.values()] * 2 + [RandomAgent(rng)]
    for _ in range(200):
        assert sum(dealer.play_hand(agents)) == 0


def test_mccfr_smoke():
    mccfr.TABLE.clear()
    rng = random.Random(0)
    for t in range(1, 301):
        mccfr.run_iteration(t, rng)
    assert len(mccfr.TABLE) > 100
    for e in mccfr.TABLE.values():
        assert all(r >= 0 for r in e[:mccfr.A])  # regret matching+
    mccfr.TABLE.clear()
