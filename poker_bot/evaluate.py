"""Evaluate a trained policy at a 9-seat table.

Each deck is replayed 9 times with the hero rotated through every seat (the other seats
keep their agents), which cancels most of the card luck. Results are in mbb/hand
(thousandths of a big blind per hand; 1000 mbb = 1 BB = 2 chips).

  python evaluate.py --policy models/nlhe9_policy.pkl --decks 300
  python evaluate.py --policy models/nlhe9_policy.pkl --vs-policy models/snapshots/policy_iter_2000.pkl
"""

import argparse
import math
import random

from agents import BASELINES, CFRAgent
from dealer import Dealer, DEFAULTS

N = 9


def run_match(hero, villains, decks, seed=0):
    """villains: list of N-1 agents. Returns (mbb/hand, standard error)."""
    rng = random.Random(seed)
    dealer = Dealer(N, stack=200, rng=rng, reset_stacks=True)
    results = []
    for _ in range(decks):
        deck = list(range(52))
        rng.shuffle(deck)
        button = rng.randrange(N)
        for hero_seat in range(N):
            agents = list(villains)
            agents.insert(hero_seat, hero)
            dealer.button = button
            net = dealer.play_hand(agents, deck=deck)
            results.append(net[hero_seat] / DEFAULTS["bb"] * 1000)
    mean = sum(results) / len(results)
    var = sum((x - mean) ** 2 for x in results) / max(1, len(results) - 1)
    # duplicate hands share cards, so use per-deck means for the error estimate
    per_deck = [sum(results[i:i + N]) / N for i in range(0, len(results), N)]
    dvar = sum((x - mean) ** 2 for x in per_deck) / max(1, len(per_deck) - 1)
    se = math.sqrt(dvar / len(per_deck)) if per_deck else math.sqrt(var)
    return mean, se


def baseline_report(policy_path, decks, seed=0, out=print):
    hero = CFRAgent(policy_path, rng=random.Random(seed))
    rows = []
    for name, cls in BASELINES.items():
        villains = [cls() for _ in range(N - 1)]
        rows.append((f"vs 8x {cls.name}", *run_match(hero, villains, decks, seed)))
    mixed = [BASELINES[k]() for k in ("random", "calling", "maniac", "tight") * 2]
    rows.append(("vs mixed table (2 of each)", *run_match(hero, mixed, decks, seed)))
    for label, mean, se in rows:
        out(f"  {label:30s} {mean:+9.1f} mbb/hand  (±{se:.1f})")
    if hero.lookups:
        out(f"  infoset coverage: {100 * (1 - hero.misses / hero.lookups):.1f}% of decisions found in policy")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="models/nlhe9_policy.pkl")
    ap.add_argument("--vs-policy", help="play the hero against 8 copies of another policy")
    ap.add_argument("--decks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    print(f"Hero policy: {args.policy}")
    if args.vs_policy:
        hero = CFRAgent(args.policy, rng=random.Random(args.seed))
        villains = [CFRAgent(args.vs_policy, rng=random.Random(args.seed + i + 1)) for i in range(N - 1)]
        mean, se = run_match(hero, villains, args.decks, args.seed)
        print(f"  vs 8x {args.vs_policy}: {mean:+.1f} mbb/hand (±{se:.1f})")
    else:
        baseline_report(args.policy, args.decks, args.seed)


if __name__ == "__main__":
    main()
