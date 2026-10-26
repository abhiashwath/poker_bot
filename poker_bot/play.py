"""Play No-Limit Hold'em (1/2 blinds) against 8 self-play-trained bots at a 9-seat table.

  python play.py                      # you sit in seat 0
  python play.py --seat 4 --show-probs
Commands at your turn: f fold, c check/call, r N raise to N, h half-pot, p pot, a all-in, q quit
"""

import argparse
import random

from agents import CFRAgent
from cards import cards_str, evaluate, hand_category
from dealer import Dealer, ACTION_NAMES, FOLD, CALL, RAISE_HALF, RAISE_POT, ALLIN, STREET_NAMES

N = 9


class Human:
    name = "You"

    def __init__(self, advisor=None):
        self.advisor = advisor

    def act(self, st, seat):
        tc = st.to_call(seat)
        board = st.visible_board()
        print(f"\n  Your hand: {cards_str(st.hole[seat], True)}   "
              f"Board: {cards_str(board, True) or '--'}   Pot: {st.pot()}   "
              f"To call: {tc}   Your stack: {st.left(seat)}")
        if self.advisor:
            probs = self.advisor.probabilities(st, seat)
            print("  (bot would: " + ", ".join(f"{ACTION_NAMES[a]} {p:.0%}" for a, p in probs.items()) + ")")
        legal = st.legal()
        prompt = ["[c]heck" if tc == 0 else f"[c]all {tc}"]
        if FOLD in legal:
            prompt.insert(0, "[f]old")
        can_raise = st.can_raise(seat)
        if can_raise:
            lo, hi = st.min_raise_to(seat), st.max_raise_to(seat)
            prompt.append(f"[r N] raise to N ({lo}-{hi})")
            prompt.append(f"[h]alf pot ({st.raise_target(RAISE_HALF, seat)})")
            prompt.append(f"[p]ot ({st.raise_target(RAISE_POT, seat)})")
            prompt.append("[a]ll-in")
        while True:
            try:
                raw = input("  " + " / ".join(prompt) + " > ").strip().lower()
            except EOFError:
                raw = "q"
            if not raw:
                continue
            cmd = raw[0]
            if cmd == "q":
                raise KeyboardInterrupt
            if cmd == "c":
                return CALL
            if cmd == "f" and FOLD in legal:
                return FOLD
            if can_raise and cmd in "hpa":
                return ("raise", st.raise_target({"h": RAISE_HALF, "p": RAISE_POT, "a": ALLIN}[cmd], seat))
            if can_raise and cmd == "r":
                try:
                    amt = int(raw[1:].strip())
                except ValueError:
                    print("  usage: r 25   (raise to 25 total this street)")
                    continue
                if lo <= amt <= hi:
                    return ("raise", amt)
                print(f"  raise must be between {lo} and {hi}")


class TablePrinter:
    """Dealer observer that narrates the hand."""

    def __init__(self, names, human_seat):
        self.names = names
        self.human = human_seat

    def label(self, st, seat):
        tags = []
        if seat == st.button:
            tags.append("D")
        sb, bb = st.blind_seats()
        if seat == sb:
            tags.append("SB")
        if seat == bb:
            tags.append("BB")
        t = f" ({'/'.join(tags)})" if tags else ""
        return f"{self.names[seat]}{t}"

    def on_hand_start(self, st):
        print("\n" + "=" * 64)
        print(f"New hand. Dealer button: seat {st.button}")
        for seat in range(st.n):
            print(f"  seat {seat}: {self.label(st, seat):22s} stack {st.stacks[seat]}")
        sb, bb = st.blind_seats()
        print(f"Dealer posts blinds: {self.names[sb]} {st.contrib[sb]}, {self.names[bb]} {st.contrib[bb]}")
        print(f"Dealer deals. Your cards: {cards_str(st.hole[self.human], True)}")
        print(f"--- {STREET_NAMES[0]} ---")
        self._street = 0

    def on_action(self, st, seat):
        kind, _, amount = st.log[-1] if st.log[-1][0] != "street" else st.log[-2]
        verb = {"fold": "folds", "check": "checks", "call": "calls", "bet": "bets",
                "raise": "raises to", "all-in": "is ALL-IN for"}[kind]
        extra = f" {amount}" if kind in ("bet", "raise", "all-in") else ""
        print(f"  {self.label(st, seat)} {verb}{extra}")
        if st.street != self._street and not st.done:
            self._street = st.street
            print(f"--- {STREET_NAMES[st.street]}: {cards_str(st.visible_board(), True)}  (pot {st.pot()}) ---")

    def on_hand_end(self, st, net):
        live = [i for i in range(st.n) if not st.folded[i]]
        if len(live) > 1:
            print(f"--- Showdown. Board: {cards_str(st.board, True)} ---")
            for i in live:
                score = evaluate(st.hole[i] + st.board)
                print(f"  {self.names[i]:10s} {cards_str(st.hole[i], True)}  {hand_category(score)}")
        for i in range(st.n):
            if net[i] > 0:
                print(f"  {self.names[i]} wins {net[i] + st.contrib[i]} (net {net[i]:+d})")
        print(f"  Your result this hand: {net[self.human]:+d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="models/nlhe9_policy.pkl")
    ap.add_argument("--seat", type=int, default=0)
    ap.add_argument("--stack", type=int, default=200)
    ap.add_argument("--show-probs", action="store_true", help="show what the bot would do in your spot")
    args = ap.parse_args()

    bot_policy = CFRAgent(args.policy)
    agents, names = [], []
    for i in range(N):
        if i == args.seat:
            agents.append(Human(bot_policy if args.show_probs else None))
            names.append("You")
        else:
            agents.append(CFRAgent(args.policy, rng=random.Random(i)))
            names.append(f"Bot{i}")
    dealer = Dealer(N, stack=args.stack)
    printer = TablePrinter(names, args.seat)
    total = 0
    try:
        while True:
            net = dealer.play_hand(agents, observer=printer)
            total += net[args.seat]
            print(f"  Session: {total:+d} chips over {dealer.hands_played} hands "
                  f"({total / 2 / dealer.hands_played:+.2f} BB/hand)")
    except KeyboardInterrupt:
        print(f"\nThanks for playing. Final: {total:+d} chips over {dealer.hands_played} hands.")


if __name__ == "__main__":
    main()
