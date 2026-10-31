"""Web server for the poker trainer.  Run:  python3 server.py   then open http://127.0.0.1:5050"""

import argparse
import os
import threading

from flask import Flask, jsonify, request, send_from_directory

import coach
from game_session import POLICY, GameError, GameSession

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(HERE, "static"), static_url_path="/static")
app.json.sort_keys = False  # keep the coach's stats in a readable order
lock = threading.Lock()
session = None


def get_session():
    global session
    if session is None:
        session = GameSession(app.config.get("POLICY", POLICY))
    return session


def respond(fn):
    with lock:
        try:
            return jsonify(fn())
        except GameError as e:
            return jsonify({"error": str(e)}), 400


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def state():
    return respond(lambda: {"events": [get_session().snapshot()]})


@app.post("/api/new_session")
def new_session():
    global session
    with lock:
        session = None
    return respond(lambda: {"events": [get_session().snapshot("New session: you sit down with $100.")]})


@app.post("/api/next_hand")
def next_hand():
    return respond(lambda: {"events": get_session().new_hand()})


@app.post("/api/action")
def action():
    body = request.get_json(force=True) or {}

    def run():
        events, fb = get_session().act(body.get("action"), body.get("amount"))
        return {"events": events, "feedback": fb}
    return respond(run)


@app.get("/api/hint")
def hint():
    return respond(lambda: get_session().hint())


@app.post("/api/rebuy")
def rebuy():
    return respond(lambda: {"events": get_session().rebuy()})


@app.get("/api/history")
def history():
    return respond(lambda: {"history": get_session().history[-50:]})


@app.get("/api/glossary")
def glossary():
    return jsonify(coach.GLOSSARY)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5050)
    ap.add_argument("--policy", default=POLICY)
    args = ap.parse_args()
    app.config["POLICY"] = args.policy
    print(f"Poker trainer running at http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
