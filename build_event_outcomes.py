"""
Deprecated helper — prefer scrape_all_events.py which writes
docs/event_outcomes.json (fx + weights) for the live coach.

Kept as a thin wrapper so older docs still point somewhere useful.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    scrape = ROOT / "scrape_all_events.py"
    if scrape.exists():
        print("Delegating to scrape_all_events.py …")
        return subprocess.call([sys.executable, str(scrape)])
    print("scrape_all_events.py missing; nothing to build.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
