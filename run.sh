#!/bin/bash
# Activate virtual environment and run the bot
cd "$(dirname "$0")"
source .venv/bin/activate
python bot.py

