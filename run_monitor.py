"""Backwards-compatible entry point: python run_monitor.py  (== generate + evaluate)."""
from agent_monitor.cli import main
raise SystemExit(main(["evaluate", "data"]))
