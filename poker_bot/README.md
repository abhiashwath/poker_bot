# Self-play poker bot: 9-player No-Limit Hold'em (1/2)

A full-ring (9 seats + dealer) No-Limit Texas Hold'em bot, blinds 1/2 with 200-chip
(100 BB) stacks. It learns **only by playing against copies of itself**. There's no
hand-coded strategy and no human hand histories.

## How it learns
It uses **External-sampling Monte Carlo Counterfactual Regret Minimization (MCCFR)**, the
same family of algorithms behind Libratus and Pluribus.

1. Each iteration, the dealer deals a random hand to 9 seats that all use the current strategy.
2. One seat is the *traverser*. At each of its decisions it tries **every** action and asks
   "how much better would I have done with this action than with my current mix?" That
   difference is the *regret*, and it accumulates per situation.
3. At the other 8 seats one action is sampled from the same current strategy (this is the
   self-play part), and their average strategy accumulates.
4. The next strategy plays each action in proportion to its positive regret (regret
   matching+). Over millions of hands the **average strategy** settles on strong,
   hard-to-exploit play.

Training runs in parallel. Worker processes are forked per epoch, run MCCFR on their own
share of hands, and send their regret changes back to be merged.

## Abstraction (what makes 9-player NL tractable)
| Part | What the bot uses |
|---|---|
| Actions | fold, check/call, raise ½ pot, raise pot, all-in (up to 3 sized raises per street, then only fold/call/shove) |
| Preflop cards | all 169 distinct starting hands |
| Postflop cards | 10 equity buckets: Monte Carlo win probability vs. the opponents still in (up to 3) |
| Betting situation | position, players in hand, raises this street, price to call (to_call ÷ pot), stack-to-pot ratio, previous-street aggressor, pot size |

The situation is described with ratios rather than exact bet sizes, so the bots can respond
to any bet size a human makes.

## Files
| File | Purpose |
|---|---|
| `cards.py` | cards, 7-card hand evaluator, preflop classes |
| `dealer.py` | `TableState` (NL betting rules, min-raise, side pots, showdown) and `Dealer` (shuffles, posts blinds, deals, moves the button) |
| `abstraction.py` | maps a game state to an information-set key |
| `mccfr.py` | self-play MCCFR trainer, checkpointing, policy export |
| `agents.py` | `CFRAgent` plus baselines: Random, CallingStation, Maniac, TightHeuristic |
| `train.py` | training CLI |
| `evaluate.py` | seat-rotated duplicate matches, reported in mbb/hand |
| `play.py` | play at the table yourself against 8 bots |
| `tests/` | evaluator, dealer, side-pot and trainer tests |

## Usage (run from this folder)
```bash
python3 train.py --iterations 10000000          # train (uses cores-2 workers)
python3 train.py --iterations 5000000 --resume  # keep training
python3 evaluate.py --decks 300                 # vs baseline tables
python3 evaluate.py --vs-policy models/snapshots/policy_iter_100000.pkl   # vs an earlier self
python3 play.py --show-probs                    # play; shows what the bot would do in your spot
python3 -m pytest tests
```
In `play.py`: `f` fold, `c` check/call, `r 25` raise to 25, `h` half pot, `p` pot, `a` all-in, `q` quit.

## Output
- `models/nlhe9_policy.pkl`: compact average strategy used by the bots
- `models/nlhe9_checkpoint.pkl`: full regret tables, used for `--resume`
- `models/snapshots/`: early policies, useful for measuring how much self-play helped
- `models/train_log.txt`: training log

## Limitations
- The card and betting abstractions lose information. A 9-player NL game is far too large to solve exactly.
- With more than 2 players, CFR has no Nash-equilibrium guarantee. It works well in practice (Pluribus), but it has no theoretical backing.
- Simplification: every all-in counts as a full raise, so a short all-in reopens the betting.
- No-limit results have high variance. Use many decks (`--decks 300+`) before trusting a result.
