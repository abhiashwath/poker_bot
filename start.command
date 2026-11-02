#!/bin/bash
# Double-click to start the Poker Trainer, then play at http://127.0.0.1:5050
cd "$(dirname "$0")"
(sleep 2 && open "http://127.0.0.1:5050") &
python3 server.py
