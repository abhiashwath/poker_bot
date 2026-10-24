"""External-sampling Monte Carlo CFR for 9-player No-Limit Hold'em 1/2 (self-play).

Every iteration deals a random hand; one seat is the "traverser". At the traverser's
decisions every action is explored and regrets are updated; at every other seat (all
playing the same current strategy -- that is the self-play) a single action is sampled
and the average strategy is accumulated. Regret matching+ floors regrets at zero and the
average strategy is weighted linearly by iteration (Linear CFR).

Table entry layout: [5 cumulative regrets | 5 strategy sums], indexed by action id
(fold, call, raise half pot, raise pot, all-in).
"""

import multiprocessing as mp
import pickle
import random
import time

import abstraction
from abstraction import infoset_key
from dealer import TableState, DEFAULTS, N_ACTIONS

A = N_ACTIONS

N_PLAYERS = 9
STACK = 200
STACK_RANGE = None     # (lo, hi): random per-seat stacks each hand, so the bot sees many depths
PRUNE_AFTER = 5000     # iterations before regret-based pruning kicks in
PRUNE_PROB = 0.95      # fraction of iterations that prune zero-regret, zero-prob actions

TABLE = {}


def regret_strategy(e, legal):
    pos = [e[a] if e[a] > 0 else 0.0 for a in legal]
    tot = sum(pos)
    if tot > 0:
        return [x / tot for x in pos]
    return [1.0 / len(legal)] * len(legal)


def average_strategy(e, legal):
    s = [e[A + a] for a in legal]
    tot = sum(s)
    if tot > 0:
        return [x / tot for x in s]
    return [1.0 / len(legal)] * len(legal)


def _sample(probs, rng):
    r = rng.random()
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if r < acc:
            return i
    return len(probs) - 1


def _add(deltas, key, idx, d):
    if deltas is None:
        return
    row = deltas.get(key)
    if row is None:
        row = deltas[key] = [0.0] * (2 * A)
    row[idx] += d


def traverse(st, trav, weight, rng, prune, deltas):
    if st.done:
        return st.payoffs()[trav]
    p = st.cur
    legal = st.legal()
    if len(legal) == 1:
        return traverse(st.apply(legal[0]), trav, weight, rng, prune, deltas)
    key = infoset_key(st, p)
    e = TABLE.get(key)
    if e is None:
        e = TABLE[key] = [0.0] * (2 * A)
    strat = regret_strategy(e, legal)

    if p == trav:
        utils = {}
        node_u = 0.0
        for a, pr in zip(legal, strat):
            if prune and pr == 0.0 and e[a] <= 0.0:
                continue
            u = traverse(st.apply(a), trav, weight, rng, prune, deltas)
            utils[a] = u
            node_u += pr * u
        for a, u in utils.items():
            new = e[a] + u - node_u
            if new < 0.0:
                new = 0.0
            _add(deltas, key, a, new - e[a])
            e[a] = new
        return node_u

    for a, pr in zip(legal, strat):
        d = weight * pr
        e[A + a] += d
        _add(deltas, key, A + a, d)
    a = legal[_sample(strat, rng)]
    return traverse(st.apply(a), trav, weight, rng, prune, deltas)


def run_iteration(t, rng, deltas=None, cfg=None):
    deck = list(range(52))
    rng.shuffle(deck)
    button = rng.randrange(N_PLAYERS)
    if STACK_RANGE:
        stacks = [rng.randint(*STACK_RANGE) for _ in range(N_PLAYERS)]
    else:
        stacks = [STACK] * N_PLAYERS
    st = TableState.new_hand(N_PLAYERS, button, stacks, deck, cfg or DEFAULTS)
    trav = rng.randrange(N_PLAYERS)
    prune = t > PRUNE_AFTER and rng.random() < PRUNE_PROB
    traverse(st, trav, float(t), rng, prune, deltas)


def _worker(args):
    seed, start_t, n_iters = args
    rng = random.Random(seed)
    abstraction.seed(seed ^ 0x5EED)
    deltas = {}
    for i in range(n_iters):
        run_iteration(start_t + i, rng, deltas)
    return deltas


def merge(deltas):
    for key, d in deltas.items():
        e = TABLE.get(key)
        if e is None:
            e = TABLE[key] = [0.0] * (2 * A)
        for i in range(A):
            v = e[i] + d[i]
            e[i] = v if v > 0.0 else 0.0
        for i in range(A, 2 * A):
            e[i] += d[i]


class Trainer:
    def __init__(self, workers=1, iters_per_worker=500, seed=None):
        self.workers = workers
        self.k = iters_per_worker
        self.iterations = 0
        self.rng = random.Random(seed)

    def train_epoch(self):
        """Run workers * k iterations. Workers are forked so they share TABLE copy-on-write;
        their regret/strategy deltas are merged back into the master table."""
        t0 = self.iterations + 1
        if self.workers <= 1:
            for i in range(self.k):
                run_iteration(t0 + i, self.rng)
            self.iterations += self.k
            return
        tasks = [(self.rng.getrandbits(62), t0, self.k) for _ in range(self.workers)]
        ctx = mp.get_context("fork")
        with ctx.Pool(self.workers) as pool:
            for deltas in pool.imap_unordered(_worker, tasks):
                merge(deltas)
        self.iterations += self.workers * self.k

    # ----- persistence ---------------------------------------------------
    def save_checkpoint(self, path):
        with open(path, "wb") as f:
            pickle.dump({"iterations": self.iterations, "table": TABLE}, f,
                        protocol=pickle.HIGHEST_PROTOCOL)

    def load_checkpoint(self, path):
        with open(path, "rb") as f:
            data = pickle.load(f)
        TABLE.clear()
        TABLE.update(data["table"])
        self.iterations = data["iterations"]


def export_policy(path, iterations):
    """Compact average-strategy file used by CFRAgent: key -> probabilities per action id."""
    policy = {}
    for key, e in TABLE.items():
        s = e[A:]
        tot = sum(s)
        if tot > 0:
            policy[key] = tuple(round(x / tot, 4) for x in s)
    meta = {
        "iterations": iterations,
        "players": N_PLAYERS,
        "game": "No-Limit Hold'em 1/2, 100BB stacks",
        "buckets": abstraction.N_BUCKETS,
        "eq_samples": abstraction.EQ_SAMPLES,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(path, "wb") as f:
        pickle.dump({"meta": meta, "policy": policy}, f, protocol=pickle.HIGHEST_PROTOCOL)
    return len(policy)
