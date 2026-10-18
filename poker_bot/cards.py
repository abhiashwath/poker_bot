"""Cards and a fast 5-7 card hand evaluator.

Cards are ints 0..51: rank = c >> 2 (0 = deuce .. 12 = ace), suit = c & 3.
evaluate() returns an int; a higher value is a better hand.
"""

RANKS = "23456789TJQKA"
SUITS = "cdhs"
SUIT_SYMBOLS = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}

CATEGORY_NAMES = [
    "High card", "Pair", "Two pair", "Three of a kind", "Straight",
    "Flush", "Full house", "Four of a kind", "Straight flush",
]


def card_str(c, pretty=False):
    s = SUITS[c & 3]
    return RANKS[c >> 2] + (SUIT_SYMBOLS[s] if pretty else s)


def cards_str(cards, pretty=False):
    return " ".join(card_str(c, pretty) for c in cards)


def parse_card(s):
    return (RANKS.index(s[0].upper()) << 2) | SUITS.index(s[1].lower())


def parse_cards(s):
    return [parse_card(t) for t in s.split()]


def _straight_high(mask):
    """Rank of the top card of the best straight in a 13-bit rank mask, or -1."""
    m = (mask << 1) | ((mask >> 12) & 1)  # bit 0 = ace-low
    for h in range(13, 3, -1):
        if (m >> (h - 4)) & 31 == 31:
            return h - 1
    return -1


def _pack(ranks):
    v = 0
    for r in ranks:
        v = (v << 4) | r
    return v


def evaluate(cards):
    rc = [0] * 13
    sc = [0] * 4
    mask = 0
    for c in cards:
        r = c >> 2
        rc[r] += 1
        sc[c & 3] += 1
        mask |= 1 << r

    for s in range(4):
        if sc[s] >= 5:
            fmask = 0
            for c in cards:
                if c & 3 == s:
                    fmask |= 1 << (c >> 2)
            sf = _straight_high(fmask)
            if sf >= 0:
                return (8 << 20) | sf
            top = [r for r in range(12, -1, -1) if fmask >> r & 1][:5]
            return (5 << 20) | _pack(top)

    quads, trips, pairs, singles = [], [], [], []
    for r in range(12, -1, -1):
        n = rc[r]
        if n == 4:
            quads.append(r)
        elif n == 3:
            trips.append(r)
        elif n == 2:
            pairs.append(r)
        elif n == 1:
            singles.append(r)

    if quads:
        q = quads[0]
        kicker = max([r for r in range(13) if rc[r] and r != q], default=0)
        return (7 << 20) | (q << 4) | kicker
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(trips[1] if len(trips) > 1 else -1, pairs[0] if pairs else -1)
        return (6 << 20) | (t << 4) | p
    st = _straight_high(mask)
    if st >= 0:
        return (4 << 20) | st
    if trips:
        return (3 << 20) | (trips[0] << 8) | _pack(singles[:2])
    if len(pairs) >= 2:
        rest = sorted(singles + pairs[2:], reverse=True)
        return (2 << 20) | (pairs[0] << 8) | (pairs[1] << 4) | (rest[0] if rest else 0)
    if pairs:
        return (1 << 20) | (pairs[0] << 12) | _pack(singles[:3])
    return _pack(singles[:5])


def hand_category(score):
    return CATEGORY_NAMES[score >> 20]


def preflop_index(hole):
    """Canonical 169-class index: 0-12 pairs, 13-90 suited, 91-168 offsuit."""
    a, b = hole
    r1, r2 = a >> 2, b >> 2
    if r1 < r2:
        r1, r2 = r2, r1
    if r1 == r2:
        return r1
    tri = r1 * (r1 - 1) // 2 + r2
    return 13 + tri if (a & 3) == (b & 3) else 91 + tri


def preflop_label(hole):
    a, b = hole
    r1, r2 = sorted((a >> 2, b >> 2), reverse=True)
    if r1 == r2:
        return RANKS[r1] * 2
    return RANKS[r1] + RANKS[r2] + ("s" if (a & 3) == (b & 3) else "o")


def chen_score(hole):
    """Bill Chen's preflop hand-strength formula (used by the heuristic baseline)."""
    a, b = hole
    r1, r2 = sorted((a >> 2, b >> 2), reverse=True)
    val = {12: 10, 11: 8, 10: 7, 9: 6}
    score = val.get(r1, (r1 + 2) / 2)
    if r1 == r2:
        return max(5, score * 2)
    if (a & 3) == (b & 3):
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:
        score += 1
    return score
