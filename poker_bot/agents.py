"""Agents that can sit at the table. Each implements act(state, seat) -> action id
(or ("raise", amount) for a custom-sized raise)."""

import pickle
import random

from abstraction import card_bucket, infoset_key, N_BUCKETS
from cards import chen_score
from dealer import FOLD, CALL, RAISE_HALF, RAISE_POT, ALLIN


# Backoff views of an infoset key (street, cards, pos, n_in, raises, price, spr, aggr, pot):
# when an exact situation was never visited in training, fall back to the average
# strategy over similar situations, dropping the least important features first.
BACKOFFS = (
    lambda k: (k[0], k[1], k[2], k[3], k[4], k[5], k[7]),   # ignore stack depth / pot size
    lambda k: (k[0], k[1], k[4], k[5]),                     # street, cards, raises, price
    lambda k: (k[0], k[1], k[5] > 0),                       # street, cards, facing a bet?
)


class CFRAgent:
    """Plays the average strategy learned by self-play MCCFR."""

    def __init__(self, policy_path, rng=None, name="CFR"):
        with open(policy_path, "rb") as f:
            data = pickle.load(f)
        self.policy = data["policy"]
        self.meta = data["meta"]
        self.rng = rng or random.Random()
        self.name = name
        self.lookups = 0
        self.misses = 0
        self.backoff_hits = 0
        self._backoff = [self._build(f) for f in BACKOFFS]

    def _build(self, view):
        sums = {}
        for key, probs in self.policy.items():
            k = view(key)
            acc = sums.get(k)
            if acc is None:
                sums[k] = list(probs)
            else:
                for i, p in enumerate(probs):
                    acc[i] += p
        return {k: tuple(x / sum(v) for x in v) for k, v in sums.items() if sum(v) > 0}

    def lookup(self, key):
        probs = self.policy.get(key)
        if probs is not None:
            return probs
        for view, table in zip(BACKOFFS, self._backoff):
            probs = table.get(view(key))
            if probs is not None:
                self.backoff_hits += 1
                return probs
        return None

    def probabilities(self, st, seat):
        legal = st.legal()
        self.lookups += 1
        probs = self.lookup(infoset_key(st, seat))
        if probs is None:  # completely unseen situation: just check/call
            self.misses += 1
            return {a: (1.0 if a == CALL else 0.0) for a in legal}
        p = [probs[a] for a in legal]
        tot = sum(p)
        if tot <= 0:
            return {a: 1.0 / len(legal) for a in legal}
        return {a: x / tot for a, x in zip(legal, p)}

    def act(self, st, seat):
        probs = self.probabilities(st, seat)
        r = self.rng.random()
        acc = 0.0
        for a, p in probs.items():
            acc += p
            if r < acc:
                return a
        return list(probs)[-1]


class RandomAgent:
    """Uniform over legal actions, but shoves rarely (otherwise it just spews stacks)."""
    name = "Random"

    def __init__(self, rng=None):
        self.rng = rng or random.Random()

    def act(self, st, seat):
        legal = [a for a in st.legal() if a != ALLIN or self.rng.random() < 0.1]
        return self.rng.choice(legal or [CALL])


class CallingStation:
    name = "CallingStation"

    def act(self, st, seat):
        return CALL


class Maniac:
    """Pot-sized raise whenever possible."""
    name = "Maniac"

    def act(self, st, seat):
        legal = st.legal()
        return RAISE_POT if RAISE_POT in legal else CALL


class TightHeuristic:
    """Tight-aggressive rule bot: Chen formula preflop, equity buckets postflop."""
    name = "TightHeuristic"

    def act(self, st, seat):
        legal = st.legal()
        pot = st.pot()
        tc = st.to_call(seat)
        if st.street == 0:
            s = chen_score(st.hole[seat])
            if s >= 12:
                return RAISE_POT if RAISE_POT in legal else (ALLIN if s >= 16 else CALL)
            if s >= 9 and st.raises <= 1:
                return RAISE_HALF if RAISE_HALF in legal and st.raises == 0 else CALL
            if tc == 0 or (s >= 7 and tc <= 2 * st.cfg["bb"]):
                return CALL
            return FOLD
        strength = (card_bucket(st, seat) + 0.5) / N_BUCKETS
        if strength >= 0.8 and st.raises < 2:
            return RAISE_POT if RAISE_POT in legal else CALL
        if strength >= 0.65 and st.raises == 0 and RAISE_HALF in legal:
            return RAISE_HALF
        if tc == 0 or strength >= tc / (pot + tc) + 0.1:  # pot odds with a margin
            return CALL
        return FOLD


BASELINES = {
    "random": RandomAgent,
    "calling": CallingStation,
    "maniac": Maniac,
    "tight": TightHeuristic,
}
