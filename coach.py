"""Poker coach: analyses a decision and explains whether it was a good one.

Combines several independent signals:
  * hand reading   - what you have (top pair, overpair, set, ...) and what draws you hold
  * the nuts       - the best possible hand on this board and how your hand ranks vs. all holdings
  * equity         - Monte Carlo win probability vs. the opponents' *likely ranges*
                     (ranges narrowed by how each opponent has played the hand so far)
  * pot odds       - the equity you need to call profitably
  * preflop charts - position-aware opening / defending guidelines
  * the bot        - how often the self-play CFR bot takes each action in this spot
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "poker_bot"))

from cards import RANKS, cards_str, chen_score, evaluate, hand_category, preflop_label # noqa: E402
from dealer import ALLIN, CALL, FOLD, RAISE_HALF, RAISE_POT  # noqa: E402

STREETS = ["Preflop", "Flop", "Turn", "River"]
POSITION_NAMES = {0: "Button", 1: "Small Blind", 2: "Big Blind", 3: "UTG", 4: "UTG+1",
                  5: "Middle Position", 6: "Lojack", 7: "Hijack", 8: "Cutoff"}
# minimum Chen score to open-raise from each position (9-handed, first in)
OPEN_THRESHOLD = {3: 9, 4: 9, 5: 8, 6: 8, 7: 7, 8: 7, 0: 6, 1: 7, 2: 7}
LATE_POSITIONS = {0, 7, 8}

_rng = random.Random()


# --------------------------------------------------------------------------- helpers
def position_of(st, seat):
    return (seat - st.button) % st.n


def money(x):
    return f"${x:,.0f}" if float(x).is_integer() else f"${x:,.2f}"


def preflop_tier(score):
    if score >= 12:
        return "Premium"
    if score >= 9:
        return "Strong"
    if score >= 7:
        return "Playable"
    if score >= 5:
        return "Speculative"
    return "Weak"


def opponent_profiles(st, hero):
    """For each opponent still in the hand: how they have acted so far."""
    prof = {}
    street = 0
    for kind, seat, _ in (st.log or []):
        if kind == "street":
            street = seat  # street events store the street index in the seat slot
            continue
        if seat == hero or kind == "blind":
            continue
        p = prof.setdefault(seat, {"pf_raise": False, "pf_call": False, "post_aggr": False})
        if street == 0:
            if kind in ("raise", "bet", "all-in"):
                p["pf_raise"] = True
            elif kind == "call":
                p["pf_call"] = True
        elif kind in ("raise", "bet", "all-in"):
            p["post_aggr"] = True
    opps = [i for i in range(st.n) if i != hero and not st.folded[i]]
    return {i: prof.get(i, {"pf_raise": False, "pf_call": False, "post_aggr": False}) for i in opps}


def _fits_range(hand, board, p):
    chen = chen_score(hand)
    if p["pf_raise"] and chen < 8:
        return False
    if p["pf_call"] and chen < 5:
        return False
    if p["post_aggr"] and board:
        cat = evaluate(hand + board) >> 20
        board_cat = evaluate(board) >> 20 if len(board) >= 5 else 0
        suits = [c & 3 for c in hand + board]
        has_fd = max(suits.count(s) for s in range(4)) >= 4
        if cat <= board_cat and not has_fd:
            return False
    return True


def range_equity(st, hero, samples=500, rng=None):
    """Equity vs opponents' likely ranges (rejection-sampled from how they've played)."""
    rng = rng or _rng
    hole = st.hole[hero]
    board = st.visible_board()
    profs = opponent_profiles(st, hero)
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    total = 0.0
    for _ in range(samples):
        avail = deck[:]
        rng.shuffle(avail)
        opp_hands = []
        for i, p in profs.items():
            pick = None
            for _try in range(25):
                j = rng.randrange(0, len(avail) - 1)
                cand = [avail[j], avail[j + 1]]
                if _fits_range(cand, board, p):
                    pick = cand
                    break
            if pick is None:
                pick = avail[:2]
            avail = [c for c in avail if c not in pick]
            opp_hands.append(pick)
        full = board + avail[:need]
        mine = evaluate(hole + full)
        opp = [evaluate(h + full) for h in opp_hands] or [-1]
        best = max(opp)
        if mine > best:
            total += 1
        elif mine == best:
            total += 1 / (1 + opp.count(mine))
    return total / samples


def nuts_analysis(hole, board):
    """Best possible holding on this board and hero's percentile vs all holdings."""
    used = set(hole) | set(board)
    rest = [c for c in range(52) if c not in used]
    mine = evaluate(hole + board)
    best, best_combo = -1, None
    beat = total = 0
    for i in range(len(rest)):
        for j in range(i + 1, len(rest)):
            s = evaluate([rest[i], rest[j]] + board)
            total += 1
            if s > best:
                best, best_combo = s, (rest[i], rest[j])
            if mine > s:
                beat += 1
            elif mine == s:
                beat += 0.5
    has_nuts = mine >= best
    return {
        "nut_hand": hand_category(best),
        "nut_example": cards_str(best_combo, True) if best_combo else "",
        "has_nuts": has_nuts,
        "percentile": beat / total if total else 0.0,
    }


def describe_made_hand(hole, board):
    score = evaluate(hole + board)
    cat = score >> 20
    name = hand_category(score)
    hr = sorted((c >> 2 for c in hole), reverse=True)
    br = sorted(set(c >> 2 for c in board), reverse=True)
    board_score = evaluate(board) if len(board) >= 5 else None
    if board_score is not None and board_score == score:
        return f"{name} (playing the board)", cat
    if cat == 1:
        pocket = hr[0] == hr[1]
        if pocket:
            if hr[0] > br[0]:
                return f"Overpair ({RANKS[hr[0]]}s)", cat
            return f"Underpair ({RANKS[hr[0]]}s below the top card)", cat
        paired = [r for r in hr if r in br]
        if not paired:
            return "Pair on the board only (you're playing kickers)", cat
        r = paired[0]
        kicker = [k for k in hr if k != r]
        ktxt = f", {RANKS[kicker[0]]} kicker" if kicker else ""
        if r == br[0]:
            return f"Top pair ({RANKS[r]}s{ktxt})", cat
        if len(br) > 1 and r == br[1]:
            return f"Second pair ({RANKS[r]}s)", cat
        return f"Bottom/weak pair ({RANKS[r]}s)", cat
    if cat == 3:
        if hr[0] == hr[1]:
            return f"Set of {RANKS[hr[0]]}s (very strong, well disguised)", cat
        return "Trips", cat
    if cat == 2:
        used = sum(1 for r in hr if r in br)
        if used == 2 and hr[0] != hr[1]:
            return "Two pair (both hole cards)", cat
        return "Two pair", cat
    if cat == 0:
        over = sum(1 for r in hr if r > br[0])
        return ("High card" + (f" with {over} overcard{'s' if over > 1 else ''}" if over else "")), cat
    return name, cat


def draws(hole, board):
    """Flush/straight draws and outs to a straight or better."""
    if len(board) >= 5 or not board:
        return {"names": [], "outs": 0}
    cards = hole + board
    current = evaluate(cards) >> 20
    names = []
    for s in range(4):
        suited = [c for c in cards if c & 3 == s]
        if len(suited) == 4 and any(c & 3 == s for c in hole):
            ace_missing = not any(c >> 2 == 12 for c in board if c & 3 == s)
            hero_ace = any(c >> 2 == 12 and c & 3 == s for c in hole)
            names.append("Nut flush draw" if hero_ace and ace_missing else "Flush draw")
    used = set(cards)
    outs = 0
    straight_ranks = set()
    if current < 4:
        for c in range(52):
            if c in used:
                continue
            new = evaluate(cards + [c]) >> 20
            if new >= 4:
                outs += 1
                if new == 4:
                    straight_ranks.add(c >> 2)
    if len(straight_ranks) >= 2:
        names.append("Open-ended straight draw")
    elif len(straight_ranks) == 1:
        names.append("Gutshot straight draw")
    return {"names": names, "outs": outs}


def classify_action(st, seat, action, raise_to):
    """Map a human action onto the bot's abstract actions (for comparing with the bot)."""
    if raise_to is None and action in (FOLD, CALL):
        return action
    target = raise_to if raise_to is not None else st.raise_target(action, seat)
    if target >= st.max_raise_to(seat):
        return ALLIN
    tc = st.max_bet() - st.sbet[seat]
    frac = (target - st.max_bet()) / max(1, st.pot() + tc)
    return RAISE_HALF if frac < 0.75 else RAISE_POT


# --------------------------------------------------------------------------- analysis
def analyze(st, seat, bot=None, samples=500):
    """Everything the coach knows about the current spot (used for hints and grading)."""
    hole = st.hole[seat]
    board = st.visible_board()
    pot = st.pot()
    tc = st.to_call(seat)
    pos = position_of(st, seat)
    a = {
        "street": STREETS[st.street],
        "street_idx": st.street,
        "hole": cards_str(hole, True),
        "board": cards_str(board, True),
        "position": POSITION_NAMES[pos],
        "pos_idx": pos,
        "pot": pot,
        "to_call": tc,
        "stack": st.left(seat),
        "opponents": st.num_in_hand() - 1,
        "raises": st.raises,
    }
    a["pot_odds"] = tc / (pot + tc) if tc > 0 else 0.0
    a["equity"] = range_equity(st, seat, samples)
    eff = min(st.left(seat), max((st.left(j) for j in range(st.n) if j != seat and not st.folded[j]), default=0))
    a["spr"] = eff / pot if pot else 0
    if st.street == 0:
        score = chen_score(hole)
        a["hand_label"] = preflop_label(hole)
        a["chen"] = score
        a["tier"] = preflop_tier(score)
        a["made"] = f"{a['hand_label']} ({a['tier']} starting hand)"
        a["draws"] = {"names": [], "outs": 0}
        a["nuts"] = None
    else:
        a["made"], a["made_cat"] = describe_made_hand(hole, board)
        a["draws"] = draws(hole, board)
        a["nuts"] = nuts_analysis(hole, board)
    if bot is not None:
        probs = bot.probabilities(st, seat)
        a["bot"] = _group_bot_probs(probs)
        a["bot_raw"] = probs
    return a


def _group_bot_probs(probs):
    g = {"fold": 0.0, "check/call": 0.0, "raise": 0.0}
    for act, p in probs.items():
        if act == FOLD:
            g["fold"] += p
        elif act == CALL:
            g["check/call"] += p
        else:
            g["raise"] += p
    return g


# --------------------------------------------------------------------------- grading
VERDICT_RANK = {"Mistake": 0, "Okay": 1, "Good": 2, "Great": 3}


def _action_text(st, seat, kind, raise_to):
    tc = st.to_call(seat)
    if kind == FOLD:
        return "Fold"
    if kind == CALL:
        return "Check" if tc == 0 else f"Call {money(tc)}"
    target = raise_to if raise_to is not None else st.raise_target(kind, seat)
    verb = "Bet" if st.max_bet() == 0 else "Raise"
    if kind == ALLIN:
        return f"All-in ({money(target)})"
    size = {RAISE_HALF: "about \u00bd pot", RAISE_POT: "about pot-sized"}.get(kind, "")
    return f"{verb} to {money(target)}" + (f" ({size})" if size else "")


def _evaluate(st, seat, kind, raise_to, a):
    """Grade one candidate action: (verdict, reasons, concepts)."""
    reasons, concepts = [], []
    if st.street == 0:
        verdict = _grade_preflop(st, seat, kind, raise_to, a, reasons, concepts)
    else:
        verdict = _grade_postflop(st, seat, kind, raise_to, a, reasons, concepts)
    bot = a.get("bot")
    if bot:
        bucket = "fold" if kind == FOLD else "check/call" if kind == CALL else "raise"
        freq = bot[bucket]
        top = max(bot, key=bot.get)
        reasons.append(
            f"The self-play bot {'also chooses' if freq >= 0.3 else 'rarely chooses'} "
            f"'{bucket}' here ({freq:.0%}); its most common play is '{top}' ({bot[top]:.0%})."
        )
        if verdict == "Mistake" and freq >= 0.45:
            verdict = "Okay"
            reasons.append("Because the trained bot likes this play, it's closer than the math alone suggests.")
        elif verdict == "Okay" and freq >= 0.6:
            verdict = "Good"
            reasons.append("The trained bot strongly prefers this play here, which makes it a solid choice.")
        elif verdict == "Good" and freq >= 0.6 and top == bucket:
            verdict = "Great"
    return verdict, reasons, concepts


def _lc(text):
    return text[:1].lower() + text[1:]


def _key_fact(st, seat, a, kind):
    """One line with the numbers that decide between the player's play and the better one."""
    tc, eq, need = a["to_call"], a["equity"], a["pot_odds"]
    if st.street == 0:
        if st.raises == 0:
            return (f"{a['hand_label']} scores {a['chen']:g} on the Chen scale; opening from "
                    f"{a['position']} needs about {OPEN_THRESHOLD[a['pos_idx']]}+.")
        return (f"{a['hand_label']} (Chen {a['chen']:g}) facing a raise: you'd pay {money(tc)} "
                f"with roughly {eq:.0%} equity against the raiser's likely range.")
    if tc > 0:
        return f"You need {need:.0%} equity to call and you have about {eq:.0%} against their likely hands."
    if kind != CALL and kind != FOLD:
        return f"With about {eq:.0%} equity ({_lc(a['made'])}), your hand is worth betting."
    return f"With about {eq:.0%} equity ({_lc(a['made'])}), there's no need to put more money in."


def best_alternative(st, seat, a, chosen_kind, chosen_verdict):
    """Evaluate every other legal action and return the best one if it beats the player's."""
    legal = st.legal()
    bot_raw = a.get("bot_raw", {})
    best = None
    for kind in legal:
        if kind == chosen_kind:
            continue
        verdict, reasons, concepts = _evaluate(st, seat, kind, None, a)
        # rank by verdict, then by how often the trained bot plays it
        score = VERDICT_RANK[verdict] + 0.5 * bot_raw.get(kind, 0.0)
        if best is None or score > best[0]:
            best = (score, kind, verdict, reasons, concepts)
    if best is None or VERDICT_RANK[best[2]] <= VERDICT_RANK[chosen_verdict]:
        return None
    return best


def grade(st, seat, action, raise_to, analysis):
    """Return a verdict + explanation for the decision the player just made, and, if it
    wasn't the best play, what the better play was and why."""
    a = analysis
    kind = classify_action(st, seat, action, raise_to)
    verdict, reasons, concepts = _evaluate(st, seat, kind, raise_to, a)

    better = None
    if verdict in ("Okay", "Mistake"):
        alt = best_alternative(st, seat, a, kind, verdict)
        if alt:
            _, alt_kind, alt_verdict, alt_reasons, alt_concepts = alt
            # keep only the reasoning specific to the better play (drop shared context lines)
            why = [r for r in alt_reasons if r not in reasons and "self-play bot" not in r]
            bot_line = [r for r in alt_reasons if "self-play bot" in r]
            better = {
                "action": _action_text(st, seat, alt_kind, None),
                "verdict": alt_verdict,
                "why": [_key_fact(st, seat, a, alt_kind)] + (why or alt_reasons[-1:]) + bot_line,
            }
            concepts = concepts + alt_concepts
        elif verdict == "Okay":
            better = {"action": None, "verdict": None,
                      "why": ["This was a close spot: none of the other options is clearly better."]}

    return {
        "verdict": verdict,
        "action": _action_text(st, seat, kind, raise_to),
        "street": a["street"],
        "hand": a["hole"],
        "board": a["board"],
        "reasons": reasons,
        "better": better,
        "concepts": sorted(set(concepts)),
        "stats": _stats(a),
    }


def _stats(a):
    s = {
        "Your hand": a["made"],
        "Position": a["position"],
        "Pot": money(a["pot"]),
        "To call": money(a["to_call"]),
        "Equity vs likely ranges": f"{a['equity']:.0%}",
    }
    if a["to_call"] > 0:
        s["Pot odds (equity needed)"] = f"{a['pot_odds']:.0%}"
    if a["draws"]["names"]:
        s["Draws"] = ", ".join(a["draws"]["names"]) + f" ({a['draws']['outs']} outs)"
    if a.get("nuts"):
        n = a["nuts"]
        s["The nuts"] = "You have it!" if n["has_nuts"] else f"{n['nut_hand']} (e.g. {n['nut_example']})"
        s["Beats"] = f"{n['percentile']:.0%} of possible hands"
    s["Stack-to-pot ratio"] = f"{a['spr']:.1f}"
    return s


def _grade_preflop(st, seat, kind, raise_to, a, reasons, concepts):
    score, tier, pos, tc = a["chen"], a["tier"], a["pos_idx"], a["to_call"]
    label = a["hand_label"]
    concepts.append("Position")
    raised = st.raises > 0  # someone has raised already (blinds don't count)
    bb = st.cfg["bb"]
    reasons.append(f"{label} is a {tier.lower()} starting hand (Chen score {score:g}). "
                   f"You're in {a['position']} with {a['opponents']} opponents still in.")

    if not raised:
        need = OPEN_THRESHOLD[pos]
        if pos == 2 and tc == 0:  # big blind, limped to us
            if kind == FOLD:
                reasons.append("Never fold the big blind when you can check for free.")
                return "Mistake"
            if kind == CALL:
                reasons.append("Checking your option is fine; you see a free flop.")
                return "Good" if score < 10 else "Okay"
            reasons.append("Raising limpers from the big blind with a strong hand builds a pot you're favoured to win."
                           if score >= 9 else "Raising a weak hand out of position into several limpers is risky.")
            return "Good" if score >= 9 else "Okay"
        reasons.append(f"Guideline: from {a['position']} open-raise roughly Chen ≥ {need} "
                       f"({'late position lets you play wider' if pos in LATE_POSITIONS else 'early seats need tighter ranges since more players act after you'}).")
        if kind == FOLD:
            if score >= need:
                reasons.append("This hand is strong enough to open-raise here; folding gives up profit.")
                return "Mistake" if score >= need + 2 else "Okay"
            reasons.append("Folding a hand below the opening range is disciplined.")
            return "Good"
        if kind == CALL:
            concepts.append("Limping")
            if score >= need:
                reasons.append("Limping (just calling the big blind) with a raising hand lets many players in cheaply. "
                               "Open-raise to about 3-4x the big blind to take the initiative.")
                return "Okay"
            reasons.append("Limping with a hand below the opening range often leads to tough spots out of position.")
            return "Mistake" if score < need - 2 else "Okay"
        size_txt = ""
        if raise_to is not None and raise_to > 6 * bb and kind != ALLIN:
            size_txt = " Your raise size is large; ~3-4x the big blind (+1x per limper) is standard."
        if kind == ALLIN and st.left(seat) > 30 * bb:
            reasons.append("Open-shoving deep-stacked only gets called by hands that beat you. Use a normal raise size.")
            return "Mistake" if score < 14 else "Okay"
        if score >= need:
            reasons.append("Open-raising takes the initiative and can win the blinds right away." + size_txt)
            return "Good" if not size_txt else "Okay"
        if pos in LATE_POSITIONS or pos == 1:
            concepts.append("Steal")
            reasons.append("A loose raise from late position can work as a blind steal." + size_txt)
            return "Okay"
        reasons.append("This hand is too weak to open from this position. Many players still act behind you.")
        return "Mistake"

    # facing a raise
    concepts.append("Pot odds")
    reasons.append(f"You're facing {'a raise' if st.raises == 1 else f'{st.raises} raises'}: "
                   f"{money(tc)} to call into a {money(a['pot'])} pot.")
    three_bet = 12 if pos not in LATE_POSITIONS else 11
    call_min = 9 if pos not in LATE_POSITIONS else 8
    if st.raises >= 2:
        three_bet, call_min = 14, 12
    pocket_pair = label[0] == label[1] and len(label) == 2
    cheap = tc <= 0.07 * a["stack"]
    if pocket_pair and cheap:
        concepts.append("Implied odds")
    if kind == FOLD:
        if score >= three_bet:
            reasons.append("This is a premium hand vs. this action; you should re-raise or at least continue.")
            return "Mistake"
        if score >= call_min or (pocket_pair and cheap):
            reasons.append("You had a reasonable hand to continue. "
                           + ("Small pairs can call cheap raises to 'set mine' (implied odds)." if pocket_pair and cheap else ""))
            return "Okay"
        reasons.append("Folding a marginal hand to a raise is sound; raisers usually have strong ranges.")
        return "Good"
    if kind == CALL:
        if score >= three_bet:
            reasons.append("Calling is OK, but a re-raise (3-bet) gets more value and thins the field.")
            return "Okay"
        if score >= call_min:
            reasons.append("Calling with a solid hand keeps you in with the raiser's weaker holdings.")
            return "Good"
        if pocket_pair and cheap:
            reasons.append("Calling cheaply with a pocket pair to hit a set (about 1 in 8.5 flops) is a classic implied-odds play.")
            return "Good"
        reasons.append("This hand is dominated by most raising ranges; calling loses money over time.")
        return "Mistake"
    concepts.append("3-bet")
    if score >= three_bet:
        reasons.append("Re-raising with a premium hand builds the pot while you're ahead.")
        return "Good"
    if score >= call_min:
        reasons.append("A re-raise with a good-but-not-premium hand can work, though calling is often better.")
        return "Okay"
    reasons.append("Re-raising with a weak hand is a bluff that gets called or 4-bet by stronger hands.")
    return "Mistake"


def _grade_postflop(st, seat, kind, raise_to, a, reasons, concepts):
    tc, pot, eq, need = a["to_call"], a["pot"], a["equity"], a["pot_odds"]
    d, nuts = a["draws"], a["nuts"]
    concepts.append("Equity")
    reasons.append(f"On the {a['street'].lower()} you have: {a['made']}. "
                   f"Against the hands your {a['opponents']} opponent{'s' if a['opponents'] != 1 else ''} "
                   f"likely hold (based on how they've played), you win about {eq:.0%} of the time.")
    if nuts:
        concepts.append("The nuts")
        if nuts["has_nuts"]:
            reasons.append("You have the nuts, the best possible hand right now. Focus on extracting value.")
        else:
            reasons.append(f"The nuts here is {nuts['nut_hand'].lower()} (e.g. {nuts['nut_example']}). "
                           f"Your hand beats {nuts['percentile']:.0%} of all possible holdings.")
    if d["names"]:
        concepts.append("Outs")
        cards_left = 2 if a["street_idx"] == 1 else 1
        rule = d["outs"] * (4 if cards_left == 2 else 2)
        reasons.append(f"Draw: {', '.join(d['names'])} with {d['outs']} outs. Rule of {4 if cards_left == 2 else 2}: "
                       f"~{min(rule, 100)}% to hit by the river{' (both cards to come)' if cards_left == 2 else ''}.")
    strong = eq >= 0.6 or (nuts and nuts["percentile"] >= 0.9)
    drawing = bool(d["names"])

    if tc > 0:
        concepts.append("Pot odds")
        reasons.append(f"Pot odds: call {money(tc)} to win {money(pot + tc)}, so you need {need:.0%} equity to break even.")
    if kind == FOLD:
        if tc == 0:
            reasons.append("Never fold when you can check for free.")
            return "Mistake"
        if eq >= need + 0.1:
            reasons.append(f"Your {eq:.0%} equity is well above the {need:.0%} needed, so calling is profitable.")
            return "Mistake"
        if eq >= need - 0.03:
            reasons.append("This is close: your equity is roughly what the price requires.")
            if drawing:
                concepts.append("Implied odds")
                reasons.append("With a draw, implied odds (money you win later when you hit) tip it towards calling.")
            return "Okay"
        reasons.append(f"You don't have the equity ({eq:.0%} < {need:.0%}). Folding saves money.")
        return "Good"

    if kind == CALL:
        if tc == 0:
            if strong and a["opponents"] >= 1:
                concepts.append("Value bet")
                reasons.append("With a strong hand, betting for value usually earns more than checking. "
                               "Weaker hands and draws will pay you off.")
                return "Okay"
            if eq < 0.35:
                reasons.append("Checking a weak hand controls the pot and keeps bluffing optional.")
                return "Good"
            reasons.append("Checking a medium-strength hand (pot control) is reasonable.")
            return "Good"
        if eq >= need:
            if strong and a["raises"] < 2:
                concepts.append("Value bet")
                reasons.append("Calling is profitable. With this much equity, raising for value is also worth considering.")
                return "Good"
            reasons.append(f"Your {eq:.0%} equity beats the {need:.0%} price, so this is a profitable call.")
            return "Good"
        if drawing and eq >= need - 0.08 and a["street_idx"] < 3:
            concepts.append("Implied odds")
            reasons.append("Direct odds are slightly short, but implied odds from hitting your draw can justify the call.")
            return "Okay"
        reasons.append(f"You're paying for {need:.0%} but only have about {eq:.0%} equity. Over time this call loses money.")
        return "Mistake"

    # bets and raises
    target = raise_to if raise_to is not None else st.raise_target(kind, seat)
    size = (target - st.max_bet()) / max(1, pot + tc)
    concepts.append("Bet sizing")
    if strong:
        concepts.append("Value bet")
        reasons.append(f"Betting/raising a strong hand for value is right (size ≈ {size:.0%} of pot).")
        if kind == ALLIN and a["spr"] > 3 and not (nuts and nuts["has_nuts"]):
            reasons.append("Shoving a deep stack can fold out the weaker hands you want calls from; a smaller bet may earn more.")
            return "Okay"
        return "Good"
    if drawing and a["street_idx"] < 3:
        concepts.append("Semi-bluff")
        reasons.append("A semi-bluff: you can win now through fold equity, and you still have outs if called.")
        return "Good" if eq >= 0.3 else "Okay"
    if eq >= 0.45:
        reasons.append("A thin value bet/protection bet. OK, but be careful if you get raised.")
        return "Okay"
    concepts.append("Bluff")
    if a["opponents"] >= 3:
        reasons.append(f"Bluffing into {a['opponents']} opponents rarely works because someone usually has a piece of the board.")
        return "Mistake"
    if a["street_idx"] == 3:
        reasons.append("A river bluff with a weak hand can work against one opponent, but pick spots where your story is believable.")
        return "Okay"
    reasons.append("Betting a weak hand with no draw is a pure bluff. It works only if opponents fold often.")
    return "Mistake" if eq < 0.25 else "Okay"


GLOSSARY = {
    "Equity": "Your share of the pot on average: the probability you win (ties split) if all cards were dealt out.",
    "Pot odds": "The price of a call: to_call / (pot + to_call). If your equity is higher, calling is profitable.",
    "Implied odds": "Extra money you expect to win on later streets when you hit, which makes calling a draw cheaper than it looks.",
    "Outs": "Unseen cards that improve you to a likely winning hand. Rule of 2 and 4: outs x4 (flop, two cards to come) or x2 (one card) ~ % to hit.",
    "The nuts": "The best possible hand given the board. Knowing the nuts tells you how vulnerable your hand is.",
    "Position": "Acting later in a betting round is an advantage because you see what others do first. The Button is the best seat.",
    "Value bet": "A bet made to get called by worse hands.",
    "Bluff": "A bet with a weak hand hoping better hands fold.",
    "Semi-bluff": "A bet with a drawing hand: it can win now if others fold, or later if you hit.",
    "Bet sizing": "Bets are usually 1/3 to 1 pot. Bigger bets charge draws more; smaller bets keep weaker hands in.",
    "3-bet": "A re-raise preflop (the blinds are the 1st bet, a raise the 2nd, a re-raise the 3rd).",
    "Limping": "Just calling the big blind preflop instead of raising. Usually weaker than raising or folding.",
    "Steal": "Raising from late position to win the blinds uncontested.",
}
