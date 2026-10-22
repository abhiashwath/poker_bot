"""State abstraction: maps a (TableState, seat) to a compact information-set key.

Card abstraction
  preflop : 169 canonical starting hands (lossless)
  postflop: equity bucket (0..N_BUCKETS-1) from Monte Carlo equity against the number
            of opponents still in the hand (capped at MAX_EQ_OPPS), rolling out the board.
Betting abstraction (full 9-player no-limit histories are far too sparse, so they are
summarised): position class, players in hand, raises this street, price to call
(to_call / pot), stack-to-pot ratio, previous-street aggressor, and pot size in BB.
Because the key uses ratios rather than exact bet sizes, bots handle any bet size a
human makes.
"""

import random

from cards import evaluate, preflop_index

N_BUCKETS = 10
EQ_SAMPLES = 32
MAX_EQ_OPPS = 3

_rng = random.Random()


def seed(s):
    _rng.seed(s)


def equity(hole, board, n_opps=1, samples=EQ_SAMPLES, rng=None):
    rng = rng or _rng
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    draw_n = need + 2 * n_opps
    total = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, draw_n)
        full = board + draw[:need]
        mine = evaluate(hole + full)
        opps = [evaluate(draw[need + 2 * k:need + 2 * k + 2] + full) for k in range(n_opps)]
        best_opp = max(opps)
        if mine > best_opp:
            total += 1.0
        elif mine == best_opp:
            total += 1.0 / (1 + opps.count(mine))
    return total / samples


def card_bucket(st, seat):
    if st.street == 0:
        return preflop_index(st.hole[seat])
    n_opps = min(st.num_in_hand() - 1, MAX_EQ_OPPS)
    key = (seat, st.street, n_opps)
    b = st.cache.get(key)
    if b is None:
        eq = equity(st.hole[seat], st.visible_board(), max(n_opps, 1))
        b = min(N_BUCKETS - 1, int(eq * N_BUCKETS))
        st.cache[key] = b
    return b


def position_class(st, seat):
    """Preflop: 0 SB, 1 BB, 2 early, 3 middle, 4 late, 5 button.
    Postflop: order among players still able to act (0 first, 1 middle, 2 last)."""
    n = st.n
    if st.street == 0:
        off = (seat - st.button) % n
        if off == 0:
            return 5
        if off == 1:
            return 0
        if off == 2:
            return 1
        frac = (off - 3) / max(1, n - 3)  # 0 = UTG ... <1 = cutoff
        return 2 if frac < 1 / 3 else (3 if frac < 2 / 3 else 4)
    order = [(st.button + k) % n for k in range(1, n + 1)]
    live = [i for i in order if not st.folded[i] and not st.allin[i]]
    idx = live.index(seat) if seat in live else 0
    if idx == len(live) - 1:
        return 2
    return 0 if idx == 0 else 1


def _bucket(x, limits):
    for i, lim in enumerate(limits):
        if x < lim:
            return i
    return len(limits)


def infoset_key(st, seat):
    pot = st.pot()
    tc = st.to_call(seat)
    # price: amount to call relative to the pot (0 = nothing to call)
    price = 0 if tc == 0 else 1 + _bucket(tc / pot, (0.2, 0.4, 0.7, 1.1, 2.0))
    # stack-to-pot ratio using the effective stack vs the deepest live opponent
    opp_left = max((st.left(j) for j in range(st.n) if j != seat and not st.folded[j]), default=0)
    spr = _bucket(min(st.left(seat), opp_left) / pot, (0.5, 1.5, 3, 6, 12))
    if st.prev_aggr is None:
        aggr = 0
    else:
        aggr = 1 if st.prev_aggr == seat else 2
    return (
        st.street,
        card_bucket(st, seat),
        position_class(st, seat),
        min(st.num_in_hand(), 5),
        min(st.raises, 3),
        price,
        spr,
        aggr,
        _bucket(pot / st.cfg["bb"], (4, 8, 16, 32, 64, 128)),
    )
