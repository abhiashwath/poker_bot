# Poker Trainer: No-Limit Hold'em $1/$2

A local website where you sit at a 9-seat No-Limit Texas Hold'em table with a dealer and
**8 bots trained by self-play**, using a $100 buy-in (play money). After every decision, a
built-in coach grades your play and explains the reasoning.

## Start it
Double-click **`start.command`**, or run:
```bash
cd ~/Desktop/poker_game && python3 server.py
```
Then open http://127.0.0.1:5050. You need Python 3 and Flask (`pip3 install flask`).

## Playing
- Blinds are $1/$2. You start with $100, and the bots automatically rebuy for $100 when they run low.
- The dealer shuffles, posts the blinds, deals, and moves the **D** button one seat each hand.
- Buttons: **Fold**, **Check/Call**, **Raise** (slider, or the Min, ½ Pot, Pot and All-in presets), **Hint**.
- Keyboard: `F` fold, `C` check/call, `R` raise, `H` hint, `N` next hand.
- The **Rebuy to $100** button tops you back up between hands.

## The coach
Each decision gets a grade (**Great / Good / Okay / Mistake**) plus an explanation built from:

| Signal | What it tells you |
|---|---|
| Hand reading | your made hand (top pair, overpair, set, ...) and your draws (flush draw, open-ender, gutshot) |
| Outs & rule of 2/4 | how often your draw gets there |
| The nuts | the best possible hand on this board, and what % of all holdings you beat |
| Equity vs likely ranges | Monte Carlo win %, against hands that fit how each opponent has actually played (raisers get strong ranges, and so on) |
| Pot odds | the equity you need to call profitably, compared with the equity you have |
| Position & preflop guidelines | opening, calling and 3-bet guidelines by seat (UTG through Button and the blinds) |
| Bot second opinion | how often the self-play bot takes each action in your exact spot |

When a decision is graded **Okay** or **Mistake**, the coach also grades every other option
(fold, check/call, and each raise size) the same way. It then shows the best one as
**Better play**, with the key numbers behind it (for example "you need 33% equity to call and
you have about 11%") and why it's better. If no alternative is clearly better, it says the
spot was a close decision. The end-of-hand review lists each of your decisions next to the
better play.

The **Hand history** tab lists every hand and its grades. **Concepts** is a glossary. Click
any concept chip on a feedback card to see its definition.

## Folder layout
```
poker_game/
  server.py         Flask web server + JSON API
  game_session.py   the live table: you (seat 0) + 8 bots, run one decision at a time
  coach.py          decision analysis and grading
  static/           the website (index.html, style.css, app.js)
  tests/            tests for the table and the coach
  poker_bot/        the self-play bot: engine, MCCFR trainer, trained models (see its README)
```

## Making the bots stronger
The bots load `poker_bot/models/nlhe9_policy.pkl`. You can train them more at any time:
```bash
cd ~/Desktop/poker_game/poker_bot && python3 train.py --resume --iterations 10000000 --stack-range 60-240
```
Then click **New session** on the website to load the updated bots.
