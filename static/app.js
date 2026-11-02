"use strict";

const $ = (id) => document.getElementById(id);
const SUIT = { c: "♣", d: "♦", h: "♥", s: "♠" };
const N = 9;
let busy = false;
let current = null;      // latest snapshot
let glossary = {};

// ------------------------------------------------------------------ API
async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

// ------------------------------------------------------------------ rendering helpers
function cardEl(code, size = "") {
  const d = document.createElement("div");
  if (!code) {
    d.className = `card back ${size}`;
    return d;
  }
  const r = code[0] === "T" ? "10" : code[0];
  const s = code[1];
  d.className = `card ${size} ${s === "h" || s === "d" ? "red" : ""}`;
  d.innerHTML = `<span class="r">${r}</span><span class="s">${SUIT[s]}</span>`;
  return d;
}

// colour any card tokens ("Ah", "A\u2665") inside a string, leave other words alone
function prettyCards(str) {
  if (!str) return "";
  return String(str).split(" ").map((w) => {
    const m = w.match(/^([2-9TJQKA])([cdhs\u2663\u2666\u2665\u2660])([,.)]?)$/);
    if (!m) return w;
    const sym = SUIT[m[2]] || m[2];
    const red = sym === "\u2665" || sym === "\u2666";
    return `<b style="color:${red ? "#ff6b6f" : "inherit"}">${m[1] === "T" ? "10" : m[1]}${sym}</b>${m[3]}`;
  }).join(" ");
}

const money = (x) => `$${Number(x).toLocaleString()}`;

// table geometry: 10 slots around an ellipse, the dealer sits in the top slot.
function slotAngle(seat) {
  const slot = seat < 5 ? seat : seat + 1;
  return (90 + slot * 36) * Math.PI / 180;
}
function seatPos(seat, rx = 45, ry = 43) {
  const a = slotAngle(seat);
  return { left: 50 + rx * Math.cos(a), top: 50 + ry * Math.sin(a) };
}

function actClass(txt) {
  const t = (txt || "").toLowerCase();
  if (t.startsWith("fold")) return "fold";
  if (t.startsWith("raise")) return "raise";
  if (t.startsWith("bet")) return "bet";
  if (t.startsWith("all")) return "allin";
  if (t.startsWith("call")) return "call";
  if (t.startsWith("check")) return "check";
  return "blind";
}

// ------------------------------------------------------------------ render snapshot
function render(snap) {
  current = snap;
  const seatsEl = $("seats");
  seatsEl.innerHTML = "";
  const winners = new Set((snap.result && snap.kind === "result" ? snap.result.winners : []).map((w) => w.seat));

  snap.seats.forEach((s, i) => {
    const p = seatPos(i);
    const el = document.createElement("div");
    el.className = "seat" + (s.is_human ? " human" : "") + (s.folded ? " folded" : "")
      + (snap.to_act === i ? " to-act" : "") + (winners.has(i) ? " winner" : "");
    el.style.left = p.left + "%";
    el.style.top = p.top + "%";

    const cards = document.createElement("div");
    cards.className = "cards";
    if (s.cards) s.cards.forEach((c) => cards.appendChild(cardEl(c, s.is_human ? "big" : "small")));
    else if (s.has_cards && !snap.hand_over) { cards.appendChild(cardEl(null, "small")); cards.appendChild(cardEl(null, "small")); }
    el.appendChild(cards);

    const plate = document.createElement("div");
    plate.className = "plate";
    plate.innerHTML = `<div class="name">${s.name}${s.allin ? " • all-in" : ""}</div>
      <div class="stack">${money(s.stack)}</div>
      <div class="act ${actClass(s.last_action)}">${s.last_action || ""}</div>`;
    if (i === snap.button) plate.insertAdjacentHTML("beforeend", `<div class="badge dbtn" title="Dealer button">D</div>`);
    else if (i === snap.sb) plate.insertAdjacentHTML("beforeend", `<div class="badge blind" title="Small blind">SB</div>`);
    else if (i === snap.bb) plate.insertAdjacentHTML("beforeend", `<div class="badge blind" title="Big blind">BB</div>`);
    el.appendChild(plate);
    seatsEl.appendChild(el);

    if (s.bet > 0) {
      const bp = seatPos(i, 27, 22);
      const b = document.createElement("div");
      b.className = "bet";
      b.style.left = bp.left + "%";
      b.style.top = bp.top + "%";
      b.innerHTML = `<span class="chip"></span>${money(s.bet)}`;
      seatsEl.appendChild(b);
    }
  });

  const board = $("board");
  board.innerHTML = "";
  for (let k = 0; k < 5; k++) {
    if (snap.board[k]) board.appendChild(cardEl(snap.board[k]));
    else { const sl = document.createElement("div"); sl.className = "slot"; board.appendChild(sl); }
  }
  $("pot").textContent = `Pot ${money(snap.pot)}`;
  $("street").textContent = snap.hand_over ? (snap.hand_no ? "Hand over" : "") : snap.street;

  if (snap.message) {
    const m = $("message");
    m.innerHTML = snap.message;
    m.className = "message" + (snap.kind === "result" ? " result" : "");
  }
  renderStats(snap.session);
  renderControls(snap);
}

function renderStats(s) {
  const profitCls = s.profit > 0 ? "pos" : s.profit < 0 ? "neg" : "";
  const v = s.verdicts;
  const graded = v.Great + v.Good + v.Okay + v.Mistake;
  const good = graded ? Math.round(100 * (v.Great + v.Good) / graded) : 0;
  $("stats").innerHTML = [
    ["Stack", money(s.stack)],
    ["Profit", `<span class="${profitCls}">${s.profit >= 0 ? "+" : "-"}${money(Math.abs(s.profit))}</span>`],
    ["Hands", s.hands],
    ["VPIP / PFR", `${Math.round(s.vpip * 100)}% / ${Math.round(s.pfr * 100)}%`],
    ["Good decisions", graded ? `${good}%` : "–"],
    ["Mistakes", v.Mistake],
  ].map(([k, val]) => `<div class="stat"><div class="k">${k}</div><div class="val">${val}</div></div>`).join("");
  $("rebuyBtn").hidden = !s.can_rebuy;
}

function renderControls(snap) {
  const opts = snap.options;
  const myTurn = !!opts && !busy;
  $("actionRow").hidden = !myTurn;
  $("dealRow").hidden = !snap.hand_over || busy;
  $("dealBtn").disabled = snap.session.busted;
  if (snap.session.busted && snap.hand_over) $("message").innerHTML = "You're out of chips. Press <b>Rebuy to $100</b> to keep playing.";
  if (!myTurn) return;

  $("foldBtn").disabled = !opts.can_fold;
  $("callBtn").innerHTML = (opts.can_check ? "Check" : `Call ${money(opts.to_call)}`) + " <kbd>C</kbd>";
  $("raiseBox").style.display = opts.can_raise ? "" : "none";
  if (opts.can_raise) {
    const sl = $("raiseSlider"), inp = $("raiseInput");
    sl.min = inp.min = opts.min_to;
    sl.max = inp.max = opts.max_to;
    setRaise(opts.half_to > opts.min_to ? opts.half_to : opts.min_to);
  }
}

function setRaise(v) {
  const opts = current && current.options;
  if (!opts) return;
  v = Math.max(opts.min_to, Math.min(opts.max_to, Math.round(Number(v) || opts.min_to)));
  $("raiseSlider").value = v;
  $("raiseInput").value = v;
  const verb = v >= opts.max_to ? "All-in" : opts.is_bet ? "Bet" : "Raise to";
  $("raiseBtn").innerHTML = `${verb} ${money(v)} <kbd>R</kbd>`;
}

// ------------------------------------------------------------------ event playback
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function play(events) {
  busy = true;
  const delay = Number($("speed").value);
  for (let i = 0; i < events.length; i++) {
    const e = events[i];
    render(e);
    if (e.kind === "result") showHandReview(e.result);
    if (i < events.length - 1) await sleep(e.kind === "deal" ? delay * 1.3 : delay);
  }
  busy = false;
  if (current) renderControls(current);
}

// ------------------------------------------------------------------ coach panel
function verdictBadge(v) { return `<span class="v ${v}">${v}</span>`; }

function kvHtml(stats) {
  return `<div class="kv">${Object.entries(stats)
    .map(([k, v]) => `<div class="k">${k}</div><div class="val">${prettyCards(v)}</div>`)
    .join("")}</div>`;
}

function botBars(bot) {
  if (!bot) return "";
  const f = bot["fold"] || 0, c = bot["check/call"] || 0, r = bot["raise"] || 0;
  const seg = (cls, p, label) => p > 0.001 ? `<div class="${cls}" style="width:${p * 100}%">${p >= 0.12 ? `${label} ${Math.round(p * 100)}%` : ""}</div>` : "";
  return `<div class="botbar"><div class="lbl">What the self-play bot does here</div>
    <div class="bars">${seg("f", f, "Fold")}${seg("c", c, "Check/Call")}${seg("r", r, "Raise")}</div></div>`;
}

function betterHtml(b) {
  if (!b) return "";
  if (!b.action) return `<div class="better close"><div class="better-head">Close decision</div>
    <ul class="reasons">${b.why.map((r) => `<li>${r}</li>`).join("")}</ul></div>`;
  return `<div class="better">
    <div class="better-head">Better play: <b>${b.action}</b> ${verdictBadge(b.verdict)}</div>
    <div class="fb-sub">Why:</div>
    <ul class="reasons">${b.why.map((r) => `<li>${r}</li>`).join("")}</ul></div>`;
}

function showFeedback(fb) {
  $("hintCard").innerHTML = "";
  const html = `<div class="fb">
      <div class="fb-head">${verdictBadge(fb.verdict)}
        <div><div class="fb-title">${fb.action}</div>
        <div class="fb-sub">${fb.street} · ${prettyCards(fb.hand)}${fb.board ? " · board " + prettyCards(fb.board) : ""}</div></div>
      </div>
      ${kvHtml(fb.stats)}
      <ul class="reasons">${fb.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>
      ${betterHtml(fb.better)}
      <div class="concepts">${fb.concepts.map((c) => `<button class="concept" data-concept="${c}">${c}</button>`).join("")}</div>
    </div>`;
  $("feedback").innerHTML = html + $("feedback").innerHTML.replace(/<div class="empty">[\s\S]*?<\/div>\s*$/, "");
  const cards = $("feedback").querySelectorAll(".fb");
  cards.forEach((c, i) => { if (i >= 6) c.remove(); });
  switchTab("feedback");
}

function showHandReview(result) {
  const fbs = result.feedback || [];
  const shown = Object.entries(result.shown || {})
    .map(([name, cs]) => `<div class="review-row"><span class="st">${name}</span>${prettyCards(cs.join(" "))}</div>`).join("");
  $("handReview").innerHTML = `<div class="fb review">
    <h4>Hand review · ${result.net >= 0 ? "+" : "-"}${money(Math.abs(result.net))}</h4>
    <div class="fb-sub">${result.message}</div>
    ${fbs.length ? fbs.map((f) => `<div class="review-row"><span class="st">${f.street}</span>${verdictBadge(f.verdict)} ${f.action}${
        f.better && f.better.action ? ` <span class="arrow">\u2192 better: <b>${f.better.action}</b></span>` : ""}</div>`).join("")
      : `<div class="fb-sub" style="margin-top:6px">You didn't have to make a decision this hand.</div>`}
    ${shown ? `<h4>Showdown</h4>${shown}` : ""}
  </div>`;
}

async function hint() {
  if (!current || !current.options || busy) return;
  try {
    const h = await api("/api/hint");
    $("hintCard").innerHTML = `<div class="fb hint-card">
      <div class="fb-head"><span class="v" style="background:#6a4fb3;color:#fff">Hint</span>
      <div class="fb-title">Think it through before you act</div></div>
      ${kvHtml(h.stats)}
      <ul class="tips">${h.tips.map((t) => `<li>${t}</li>`).join("")}</ul>
      ${botBars(h.bot)}</div>`;
    switchTab("feedback");
    $("tab-feedback").scrollTop = 0;
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ actions
async function doAction(action, amount) {
  if (busy || !current || !current.options) return;
  busy = true;
  $("actionRow").hidden = true;
  try {
    const data = await api("/api/action", { action, amount });
    showFeedback(data.feedback);
    await play(data.events);
  } catch (e) { toast(e.message); busy = false; renderControls(current); }
}

async function deal() {
  if (busy) return;
  $("handReview").innerHTML = "";
  $("hintCard").innerHTML = "";
  busy = true;
  $("dealRow").hidden = true;
  try { await play((await api("/api/next_hand", {})).events); }
  catch (e) { toast(e.message); busy = false; renderControls(current); }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["feedback", "history", "learn"].forEach((n) => ($(`tab-${n}`).hidden = n !== name));
  if (name === "history") loadHistory();
}

async function loadHistory() {
  const { history } = await api("/api/history");
  $("tab-history").innerHTML = history.length ? history.slice().reverse().map((h) => {
    const counts = {};
    h.feedback.forEach((f) => (counts[f.verdict] = (counts[f.verdict] || 0) + 1));
    return `<div class="hist-item">
      <div class="hist-top"><span>Hand #${h.hand_no}</span>
        <span class="${h.net > 0 ? "pos" : h.net < 0 ? "neg" : ""}">${h.net >= 0 ? "+" : "-"}${money(Math.abs(h.net))}</span></div>
      <div class="hist-cards">You: ${prettyCards(h.hole)} ${h.board ? "· Board: " + prettyCards(h.board) : ""}</div>
      <div style="margin-top:4px">${Object.entries(counts).map(([v, n]) => `${verdictBadge(v)} ×${n}`).join(" ") || '<span class="fb-sub">no decisions</span>'}</div>
    </div>`;
  }).join("") : `<p class="fb-sub">No hands played yet.</p>`;
}

function renderGlossary() {
  $("tab-learn").innerHTML = `<dl class="gloss">${Object.entries(glossary)
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function showConcept(btn) {
  document.querySelectorAll(".pop").forEach((p) => p.remove());
  const text = glossary[btn.dataset.concept];
  if (!text) return;
  const pop = document.createElement("div");
  pop.className = "pop";
  pop.innerHTML = `<b style="color:var(--gold)">${btn.dataset.concept}</b><br>${text}`;
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = Math.max(8, Math.min(window.innerWidth - 310, r.left)) + "px";
  pop.style.top = (r.bottom + 6) + "px";
  setTimeout(() => document.addEventListener("click", () => pop.remove(), { once: true }), 0);
}

// ------------------------------------------------------------------ wiring
$("foldBtn").onclick = () => doAction("fold");
$("callBtn").onclick = () => doAction("call");
$("raiseBtn").onclick = () => doAction("raise", Number($("raiseInput").value));
$("hintBtn").onclick = hint;
$("dealBtn").onclick = deal;
$("raiseSlider").oninput = (e) => setRaise(e.target.value);
$("raiseInput").onchange = (e) => setRaise(e.target.value);
document.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => {
  const o = current.options;
  setRaise({ min: o.min_to, half: o.half_to, pot: o.pot_to, max: o.max_to }[b.dataset.preset]);
}));
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));
document.addEventListener("click", (e) => { if (e.target.classList.contains("concept")) showConcept(e.target); });
$("rebuyBtn").onclick = async () => {
  try { await play((await api("/api/rebuy", {})).events); } catch (e) { toast(e.message); }
};
$("newSessionBtn").onclick = async () => {
  if (current && current.hand_no && !confirm("Start a new session? Your stats and history reset.")) return;
  $("feedback").innerHTML = "";
  $("handReview").innerHTML = "";
  $("hintCard").innerHTML = "";
  await play((await api("/api/new_session", {})).events);
};
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey) return;
  const k = e.key.toLowerCase();
  if (k === "n" && current && current.hand_over && !busy) deal();
  if (!current || !current.options || busy) return;
  if (k === "f" && current.options.can_fold) doAction("fold");
  else if (k === "c") doAction("call");
  else if (k === "r" && current.options.can_raise) doAction("raise", Number($("raiseInput").value));
  else if (k === "h") hint();
});

(async function init() {
  try {
    glossary = await api("/api/glossary");
    renderGlossary();
    const { events } = await api("/api/state");
    render(events[0]);
    const s = events[0];
    if (!s.hand_no) $("message").innerHTML = "Welcome! You have <b>$100</b>. Press <b>Deal next hand</b> to start.";
    else if (s.hand_over) $("message").innerHTML = (s.result ? s.result.message + ". " : "") + "Press <b>Deal next hand</b> to continue.";
    else $("message").innerHTML = s.options ? "Your turn." : "Hand in progress.";
  } catch (e) { toast("Can't reach the game server: " + e.message); }
})();
