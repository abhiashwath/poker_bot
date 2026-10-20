"""9-seat No-Limit Hold'em (blinds 1/2): game state, betting rules, side pots and the Dealer.

TableState is immutable-by-convention: apply() returns a new state, which lets the
CFR trainer branch on actions cheaply. The Dealer runs complete hands between agents,
tracks stacks across hands and moves the dealer button.

Bot action menu (the "action abstraction"): fold, check/call, raise half pot, raise pot,
all-in. Humans (and apply(..., raise_to=X)) may raise to any legal amount.
"""

import random

from cards import cards_str

FOLD, CALL, RAISE_HALF, RAISE_POT, ALLIN = range(5)
N_ACTIONS = 5
RAISES = (RAISE_HALF, RAISE_POT, ALLIN)
ACTION_NAMES = {FOLD: "fold", CALL: "call", RAISE_HALF: "raise ½ pot",
                RAISE_POT: "raise pot", ALLIN: "all-in"}
STREET_NAMES = ["Preflop", "Flop", "Turn", "River"]
BOARD_SIZE = [0, 3, 4, 5]

# max_sized_raises: after this many raises on a street, bots may only fold / call / shove
DEFAULTS = dict(sb=1, bb=2, max_sized_raises=3)
POT_FRACTION = {RAISE_HALF: 0.5, RAISE_POT: 1.0}


class TableState:
    __slots__ = (
        "n", "button", "stacks", "contrib", "sbet", "folded", "allin", "hole", "board",
        "street", "cur", "raises", "last_raise", "pending", "aggr", "prev_aggr", "done",
        "cfg", "cache", "log",
    )

    @classmethod
    def new_hand(cls, n, button, stacks, deck, cfg=None, cache=None, log=False):
        s = cls()
        s.cfg = cfg or DEFAULTS
        s.n = n
        s.button = button
        s.stacks = list(stacks)
        s.contrib = [0] * n
        s.sbet = [0] * n
        s.folded = [False] * n
        s.allin = [False] * n
        s.hole = [deck[2 * i:2 * i + 2] for i in range(n)]
        s.board = deck[2 * n:2 * n + 5]
        s.street = 0
        s.raises = 0
        s.last_raise = s.cfg["bb"]
        s.aggr = None
        s.prev_aggr = None
        s.done = False
        s.cache = {} if cache is None else cache
        s.log = [] if log else None

        sb_seat, bb_seat = s.blind_seats()
        s._put(sb_seat, s.cfg["sb"])
        s._put(bb_seat, s.cfg["bb"])
        if s.log is not None:
            s.log.append(("blind", sb_seat, s.sbet[sb_seat]))
            s.log.append(("blind", bb_seat, s.sbet[bb_seat]))
        s.pending = sum(1 for i in range(n) if not s.allin[i])
        s.cur = s._next_able(bb_seat)
        if s.pending == 0 or s.cur is None:
            s.done = True
        return s

    def copy(self):
        s = TableState.__new__(TableState)
        s.n = self.n
        s.button = self.button
        s.stacks = self.stacks
        s.contrib = self.contrib[:]
        s.sbet = self.sbet[:]
        s.folded = self.folded[:]
        s.allin = self.allin[:]
        s.hole = self.hole
        s.board = self.board
        s.street = self.street
        s.cur = self.cur
        s.raises = self.raises
        s.last_raise = self.last_raise
        s.pending = self.pending
        s.aggr = self.aggr
        s.prev_aggr = self.prev_aggr
        s.done = self.done
        s.cfg = self.cfg
        s.cache = self.cache
        s.log = None if self.log is None else self.log[:]
        return s

    # ----- queries -------------------------------------------------------
    def blind_seats(self):
        if self.n == 2:
            return self.button, (self.button + 1) % 2
        return (self.button + 1) % self.n, (self.button + 2) % self.n

    def pot(self):
        return sum(self.contrib)

    def max_bet(self):
        return max(self.sbet)

    def to_call(self, seat=None):
        seat = self.cur if seat is None else seat
        return min(self.max_bet() - self.sbet[seat], self.left(seat))

    def left(self, seat):
        return self.stacks[seat] - self.contrib[seat]

    def visible_board(self):
        return self.board[:BOARD_SIZE[self.street]]

    def num_in_hand(self):
        return self.n - sum(self.folded)

    def _able(self, i):
        return not self.folded[i] and not self.allin[i]

    def _next_able(self, seat):
        for k in range(1, self.n + 1):
            j = (seat + k) % self.n
            if self._able(j):
                return j
        return None

    def min_raise_to(self, seat=None):
        seat = self.cur if seat is None else seat
        return min(self.max_bet() + self.last_raise, self.sbet[seat] + self.left(seat))

    def max_raise_to(self, seat=None):
        seat = self.cur if seat is None else seat
        return self.sbet[seat] + self.left(seat)

    def can_raise(self, seat=None):
        p = self.cur if seat is None else seat
        if self.left(p) <= self.max_bet() - self.sbet[p]:
            return False
        return any(self._able(j) for j in range(self.n) if j != p)

    def raise_target(self, a, seat=None):
        """Total street bet ('raise to') for an abstract raise action."""
        p = self.cur if seat is None else seat
        cap = self.max_raise_to(p)
        if a == ALLIN:
            return cap
        tc = self.max_bet() - self.sbet[p]
        target = self.max_bet() + int(round(POT_FRACTION[a] * (self.pot() + tc)))
        target = max(target, self.max_bet() + self.last_raise)
        return min(target, cap)

    def legal(self):
        p = self.cur
        tc = self.max_bet() - self.sbet[p]
        acts = [FOLD, CALL] if tc > 0 else [CALL]
        if not self.can_raise(p):
            return acts
        cap = self.max_raise_to(p)
        seen = set()
        if self.raises < self.cfg["max_sized_raises"]:
            for a in (RAISE_HALF, RAISE_POT):
                t = self.raise_target(a, p)
                if t < cap and t not in seen:
                    seen.add(t)
                    acts.append(a)
        acts.append(ALLIN)
        return acts

    # ----- transitions ---------------------------------------------------
    def _put(self, seat, amount):
        amount = max(0, min(amount, self.left(seat)))
        self.contrib[seat] += amount
        self.sbet[seat] += amount
        if self.left(seat) == 0:
            self.allin[seat] = True
        return amount

    def apply(self, a, raise_to=None):
        """Apply an action. For a custom-sized raise pass raise_to (total street bet)."""
        s = self.copy()
        p = s.cur
        tc = s.max_bet() - s.sbet[p]
        if raise_to is not None or a in RAISES:
            target = raise_to if raise_to is not None else s.raise_target(a, p)
            target = max(min(target, s.max_raise_to(p)), s.min_raise_to(p))
            increment = target - s.max_bet()
            if increment >= s.last_raise:
                s.last_raise = increment
            s._put(p, target - s.sbet[p])
            s.raises += 1
            s.aggr = p
            s.pending = sum(1 for j in range(s.n) if j != p and s._able(j))
            kind = "all-in" if s.allin[p] else ("bet" if s.max_bet() == target and tc == 0 else "raise")
        elif a == FOLD:
            s.folded[p] = True
            s.pending -= 1
            kind = "fold"
        else:
            s._put(p, tc)
            s.pending -= 1
            kind = "check" if tc == 0 else ("all-in" if s.allin[p] else "call")
        if s.log is not None:
            s.log.append((kind, p, s.sbet[p]))
        s._advance(p)
        return s

    def _advance(self, p):
        if self.num_in_hand() == 1:
            self.done = True
            return
        if self.pending > 0:
            self.cur = self._next_able(p)
            if self.cur is not None:
                return
        if self.street == 3:
            self.done = True
            return
        self.street += 1
        self.sbet = [0] * self.n
        self.raises = 0
        self.last_raise = self.cfg["bb"]
        self.prev_aggr = self.aggr
        self.aggr = None
        if self.log is not None:
            self.log.append(("street", self.street, None))
        able = [i for i in range(self.n) if self._able(i)]
        if len(able) < 2:
            # nobody left to bet against: the dealer runs the board out
            self.street = 3
            self.done = True
            return
        self.pending = len(able)
        self.cur = self._next_able(self.button)

    # ----- showdown ------------------------------------------------------
    def payoffs(self):
        """Net chips won (+) or lost (-) by each seat. Sums to zero."""
        net = [-c for c in self.contrib]
        live = [i for i in range(self.n) if not self.folded[i]]
        if len(live) == 1:
            net[live[0]] += self.pot()
            return net
        for seat, amount in self.pot_awards():
            net[seat] += amount
        return net

    def pot_awards(self):
        """[(seat, chips)] from the main pot and side pots at showdown."""
        from cards import evaluate
        n = self.n
        live = [i for i in range(n) if not self.folded[i]]
        scores = {i: evaluate(self.hole[i] + self.board) for i in live}
        levels = sorted(set(self.contrib[i] for i in live))
        awards = []
        prev = 0
        order = [(self.button + k) % n for k in range(1, n + 1)]  # odd chips go left of button
        for level in levels:
            pot = sum(min(c, level) - min(c, prev) for c in self.contrib)
            prev = level
            if pot <= 0:
                continue
            elig = [i for i in live if self.contrib[i] >= level]
            best = max(scores[i] for i in elig)
            winners = [i for i in order if i in elig and scores[i] == best]
            share, odd = divmod(pot, len(winners))
            for k, w in enumerate(winners):
                awards.append((w, share + (1 if k < odd else 0)))
        return awards


class Dealer:
    """Runs hands at a 9-seat table: shuffles, posts blinds, deals, asks each agent to
    act, awards main/side pots and moves the dealer button one seat left after every hand.

    Agents implement act(state, seat) returning either an action id or ("raise", amount).
    """

    def __init__(self, n=9, stack=200, cfg=None, rng=None, reset_stacks=False):
        self.n = n
        self.start_stack = stack
        self.stacks = [stack] * n
        self.cfg = cfg or DEFAULTS
        self.rng = rng or random.Random()
        self.button = self.rng.randrange(n)
        self.reset_stacks = reset_stacks
        self.hands_played = 0

    def play_hand(self, agents, deck=None, observer=None):
        if self.reset_stacks:
            self.stacks = [self.start_stack] * self.n
        for i in range(self.n):  # automatic rebuy for busted players
            if self.stacks[i] < self.cfg["bb"]:
                self.stacks[i] = self.start_stack
        if deck is None:
            deck = list(range(52))
            self.rng.shuffle(deck)
        st = TableState.new_hand(self.n, self.button, self.stacks, deck, self.cfg,
                                 log=observer is not None)
        if observer:
            observer.on_hand_start(st)
        while not st.done:
            seat = st.cur
            a = agents[seat].act(st, seat)
            if isinstance(a, tuple):
                st = st.apply(None, raise_to=a[1]) if st.can_raise() else st.apply(CALL)
            else:
                st = st.apply(a if a in st.legal() else CALL)
            if observer:
                observer.on_action(st, seat)
        net = st.payoffs()
        if observer:
            observer.on_hand_end(st, net)
        self.stacks = [s + d for s, d in zip(self.stacks, net)]
        self.button = (self.button + 1) % self.n
        self.hands_played += 1
        return net


def describe_showdown(st):
    return [f"Seat {i}: {cards_str(st.hole[i], True)}" for i in range(st.n) if not st.folded[i]]
