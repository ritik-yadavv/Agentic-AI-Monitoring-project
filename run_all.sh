#!/usr/bin/env sh
# Regenerate all data and rebuild the report. Python 3.10+, no dependencies.
set -e
python scripts/build_handcrafted.py
python -m agent_monitor generate --seed 7 --split dev
python -m agent_monitor generate --seed 2026 --split test --subdir generated
python -m agent_monitor evaluate data --out reports
