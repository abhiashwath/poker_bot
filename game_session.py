"""A live 9-seat table: you + 8 self-play bots, with a dealer, run one decision at a time.

Each call returns a list of *events*. Every event carries a full public snapshot of
the table, so the browser can animate the hand step by step.
"""

import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "poker_bot"))

import coach  # noqa: E402
from agents import CFRAgent  # noqa: E402
from cards import card_str, evaluate, hand_category  # noqa: E402
from dealer import CALL, DEFAULTS, FOLD, RAISE_HALF, RAISE_POT, STREET_NAMES, TableState  # noqa: E402

N = 9
HUMAN = 0
BUY_IN = 100
POLICY = os.path.join(HERE, "poker_bot", "models", "nlhe9_policy.pkl")


class GameError(Exception):
    pass


class GameSession:
    def __init__(self, policy_path=POLICY, buy_in=BUY_IN, seed=None):
        self.rng = random.Random(seed)
        self.bot = CFRAgent(policy_path, rng=random.Random(seed))
        self.buy_in = buy_in
        self.cfg = DEFAULTS
        self.names = ["You"] + [f"Bot {i}" for i in range(1, N)]
        self.stacks = [buy_in] * N
        self.button = self.rng.randrange(N)
        self.state = None
        self.hand_no = 0
        self.last_action = {}
        self.hand_feedback = []
        self.last_result = None
        self.total_bought = buy_in
        self.history = []  # past hand summaries
        self.stats = {"hands": 0, "vpip": 0, "pfr": 0, "won": 0,
                      "verdicts": {"Great": 0, "Good": 0, "Okay": 0, "Mistake": 0}}
        self._flags = {}

    # ------------------------------------------------------------------ helpers
    @property
    def in_hand(self):
        return self.state is not None and not self.state.done

    def _options(self):
        st = self.state
        if not self.in_hand or st.cur != HUMAN:
            return None
        tc = st.to_call(HUMAN)
        opts = {"can_fold": tc > 0, "to_call": tc, "can_check": tc == 0, "can_raise": st.can_raise(HUMAN)}
        if opts["can_raise"]:
            opts.update(
                min_to=st.min_raise_to(HUMAN),
                max_to=st.max_raise_to(HUMAN),
                half_to=st.raise_target(RAISE_HALF, HUMAN),
                pot_to=st.raise_target(RAISE_POT, HUMAN),
                is_bet=st.max_bet() == 0,
            )
        return opts

    def snapshot(self, message="", kind="info"):
        st = self.state
        seats = []
        live = [] if st is None else [i for i in range(N) if not st.folded[i]]
        showdown = st is not None and st.done and len(live) > 1
        for i in range(N):
            seat = {"name": self.names[i], "is_human": i == HUMAN}
            if st is None:
                seat.update(stack=self.stacks[i], bet=0, folded=False, allin=False, cards=None)
            else:
                show = i == HUMAN or (showdown and i in live)
                seat.update(
                    # once the pot is awarded show the new stacks, otherwise chips behind
                    stack=self.stacks[i] if (st.done and self.last_result is not None) else st.left(i),
                    bet=st.sbet[i] if not st.done else 0,
                    folded=st.folded[i],
                    allin=st.allin[i],
                    cards=[card_str(c) for c in st.hole[i]] if show else None,
                    has_cards=not st.folded[i],
                )
            seat["last_action"] = self.last_action.get(i, "")
            seats.append(seat)
        sb, bb = (st.blind_seats() if st else ((self.button + 1) % N, (self.button + 2) % N))
        board = [] if st is None else [card_str(c) for c in (st.board if showdown else st.visible_board())]
        return {
            "kind": kind,
            "message": message,
            "hand_no": self.hand_no,
            "seats": seats,
            "button": st.button if st else self.button,
            "sb": sb,
            "bb": bb,
            "board": board,
            "pot": st.pot() if st else 0,
            "street": STREET_NAMES[st.street] if st else "",
            "to_act": st.cur if self.in_hand else None,
            "options": self._options(),
            "hand_over": not self.in_hand,
            "result": self.last_result if not self.in_hand else None,
            "session": self.session_info(),
        }

    def session_info(self):
        s = self.stats
        h = max(1, s["hands"])
        stack = self.state.left(HUMAN) if self.in_hand else self.stacks[HUMAN]
        return {
            "stack": stack,
            "bought_in": self.total_bought,
            "profit": self.stacks[HUMAN] - self.total_bought,
            "hands": s["hands"],
            "vpip": s["vpip"] / h,
            "pfr": s["pfr"] / h,
            "verdicts": s["verdicts"],
            "can_rebuy": not self.in_hand and self.stacks[HUMAN] < self.buy_in,
            "busted": not self.in_hand and self.stacks[HUMAN] < self.cfg["bb"],
            "policy_iterations": self.bot.meta.get("iterations"),
        }

    def _describe(self, entry):
        kind, seat, amount = entry
        name = self.names[seat]
        words = {"fold": "folds", "check": "checks", "call": f"calls ${amount}", "bet": f"bets ${amount}",
                 "raise": f"raises to ${amount}", "all-in": f"is ALL-IN (${amount})", "blind": f"posts ${amount}"}
        short = {"fold": "Fold", "check": "Check", "call": f"Call ${amount}", "bet": f"Bet ${amount}",
                 "raise": f"Raise ${amount}", "all-in": "ALL-IN", "blind": f"Blind ${amount}"}
        return f"{name} {words[kind]}", short[kind]

    def _step(self, action, raise_to=None):
        """Apply one action and return the events it produced."""
        st = self.state
        before = len(st.log)
        seat = st.cur
        self.state = st = st.apply(action, raise_to=raise_to)
        events = []
        for entry in st.log[before:]:
            if entry[0] == "street":
                continue
            msg, short = self._describe(entry)
            self.last_action[seat] = short
            events.append(self.snapshot(msg, "action"))
        new_streets = [e for e in st.log[before:] if e[0] == "street"]
        if new_streets and not st.done:
            self.last_action = {i: a for i, a in self.last_action.items() if a in ("Fold", "ALL-IN")}
            events.append(self.snapshot(
                f"Dealer deals the {STREET_NAMES[st.street].lower()}: "
                + " ".join(card_str(c) for c in st.visible_board()[-(3 if st.street == 1 else 1):]),
                "deal"))
        return events

    def _run_bots(self):
        events = []
        while self.in_hand and self.state.cur != HUMAN:
            st = self.state
            events += self._step(self.bot.act(st, st.cur))
        if self.state.done and self.last_result is None:
            events.append(self._finish())
        return events

    def _finish(self):
        st = self.state
        net = st.payoffs()
        live = [i for i in range(N) if not st.folded[i]]
        winners = []
        if len(live) == 1:
            winners.append({"seat": live[0], "name": self.names[live[0]], "amount": st.pot(), "hand": "uncontested"})
            msg = f"{self.names[live[0]]} wins ${st.pot()} (everyone else folded)"
        else:
            totals = {}
            for seat, amt in st.pot_awards():
                totals[seat] = totals.get(seat, 0) + amt
            for seat, amt in totals.items():
                winners.append({"seat": seat, "name": self.names[seat], "amount": amt,
                                "hand": hand_category(evaluate(st.hole[seat] + st.board))})
            msg = "Showdown: " + ", ".join(f"{w['name']} wins ${w['amount']} with {w['hand'].lower()}" for w in winners)
        self.stacks = [s + d for s, d in zip(self.stacks, net)]
        self.stats["hands"] += 1
        self.stats["vpip"] += self._flags.get("vpip", 0)
        self.stats["pfr"] += self._flags.get("pfr", 0)
        if net[HUMAN] > 0:
            self.stats["won"] += 1
        self.last_result = {
            "winners": winners,
            "net": net[HUMAN],
            "message": msg,
            "feedback": self.hand_feedback,
            "shown": {self.names[i]: [card_str(c) for c in st.hole[i]] for i in live} if len(live) > 1 else {},
        }
        self.history.append({"hand_no": self.hand_no, "net": net[HUMAN],
                             "hole": " ".join(card_str(c) for c in st.hole[HUMAN]),
                             "board": " ".join(card_str(c) for c in st.board[:5 if len(live) > 1 else len(st.visible_board())]),
                             "feedback": self.hand_feedback})
        self.button = (self.button + 1) % N
        return self.snapshot(msg, "result")

    # ------------------------------------------------------------------ API
    def new_hand(self):
        if self.in_hand:
            raise GameError("A hand is already in progress.")
        if self.stacks[HUMAN] < self.cfg["bb"]:
            raise GameError("You're out of chips. Rebuy to keep playing.")
        events = []
        for i in range(1, N):
            if self.stacks[i] < self.cfg["bb"] * 5:
                self.stacks[i] = self.buy_in
                events.append(self.snapshot(f"{self.names[i]} rebuys for ${self.buy_in}", "info"))
        deck = list(range(52))
        self.rng.shuffle(deck)
        self.hand_no += 1
        self.last_action = {}
        self.hand_feedback = []
        self.last_result = None
        self._flags = {}
        self.state = TableState.new_hand(N, self.button, self.stacks, deck, self.cfg, log=True)
        sb, bb = self.state.blind_seats()
        self.last_action = {sb: f"SB ${self.state.sbet[sb]}", bb: f"BB ${self.state.sbet[bb]}"}
        events.append(self.snapshot(
            f"Hand #{self.hand_no}: the dealer shuffles and deals. "
            f"{self.names[sb]} posts the $1 small blind, {self.names[bb]} posts the $2 big blind.", "deal"))
        return events + self._run_bots()

    def act(self, action, amount=None):
        st = self.state
        if not self.in_hand or st.cur != HUMAN:
            raise GameError("It's not your turn.")
        opts = self._options()
        raise_to = None
        if action == "fold":
            a = FOLD if opts["can_fold"] else CALL
        elif action in ("call", "check"):
            a = CALL
        elif action == "raise":
            if not opts["can_raise"]:
                raise GameError("You can't raise here.")
            raise_to = int(max(opts["min_to"], min(opts["max_to"], int(amount or opts["min_to"]))))
            a = None
        else:
            raise GameError(f"Unknown action {action!r}")

        analysis = coach.analyze(st, HUMAN, self.bot)
        fb = coach.grade(st, HUMAN, a if a is not None else RAISE_HALF, raise_to, analysis)
        self.hand_feedback.append(fb)
        self.stats["verdicts"][fb["verdict"]] += 1
        if st.street == 0 and (raise_to is not None or (a == CALL and opts["to_call"] > 0)):
            self._flags["vpip"] = 1
            if raise_to is not None:
                self._flags["pfr"] = 1

        events = self._step(a if a is not None else RAISE_HALF, raise_to=raise_to)
        events += self._run_bots()
        return events, fb

    def hint(self):
        st = self.state
        if not self.in_hand or st.cur != HUMAN:
            raise GameError("It's not your turn.")
        a = coach.analyze(st, HUMAN, self.bot)
        tips = []
        if a["to_call"] > 0 and not (st.street == 0 and st.raises == 0):
            verdict = "profitable" if a["equity"] >= a["pot_odds"] else "not profitable on pot odds alone"
            tips.append(f"You need {a['pot_odds']:.0%} equity to call; you have about {a['equity']:.0%}, so a call is {verdict}.")
        if st.street == 0:
            need = coach.OPEN_THRESHOLD[a["pos_idx"]]
            tips.append(f"{a['hand_label']} has a Chen score of {a['chen']:g}. From {a['position']}, "
                        f"open-raise hands scoring about {need}+ when nobody has raised yet.")
        top = max(a["bot"], key=a["bot"].get)
        tips.append(f"The self-play bot would {top} here {a['bot'][top]:.0%} of the time.")
        return {"stats": coach._stats(a), "bot": a["bot"], "tips": tips}

    def rebuy(self):
        if self.in_hand:
            raise GameError("You can only rebuy between hands.")
        if self.stacks[HUMAN] >= self.buy_in:
            raise GameError("You already have a full buy-in.")
        add = self.buy_in - self.stacks[HUMAN]
        self.stacks[HUMAN] = self.buy_in
        self.total_bought += add
        return [self.snapshot(f"You rebuy ${add} (back to ${self.buy_in}).", "info")]
