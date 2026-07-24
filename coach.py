"""
Destiny Eleven Coach — conseil en direct via le navigateur.

Usage:
  pip install -r requirements.txt
  python -m playwright install chromium
  python coach.py

Le script ouvre destinyeleven.com. Joue dans cette fenêtre :
à chaque dilemme, le terminal affiche le choix recommandé.
"""

from __future__ import annotations

import hashlib
import time

from playwright.sync_api import sync_playwright

from advisor import advise
from dom_extract import EXTRACT_JS

URL = "https://destinyeleven.com/"


def extract_state(page) -> tuple[str, list[str]]:
    """Lit le prompt + boutons de choix visibles."""
    return page.evaluate(EXTRACT_JS)


def main() -> None:
    print("=" * 56)
    print(" DESTINY ELEVEN COACH")
    print(" Joue dans la fenêtre Chromium qui s'ouvre.")
    print(" Les conseils s'affichent ici à chaque dilemme.")
    print(" Ctrl+C pour quitter.")
    print("=" * 56)

    last_fp = ""
    with sync_playwright() as p:
        from browser_profile_cfg import PROFILE_DIR, launch_game_context

        context = launch_game_context(p)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(URL, wait_until="domcontentloaded")
        print(f"\nProfil persistant: {PROFILE_DIR}")
        print("Ta carrière Destiny Eleven est gardée dans ce profil (localStorage).")
        print("Page chargée. Reprends / lance ta carrière…\n")

        try:
            while True:
                try:
                    prompt, choices = extract_state(page)
                except Exception:
                    time.sleep(0.4)
                    continue

                if len(choices) < 2:
                    time.sleep(0.35)
                    continue

                fp = hashlib.md5(
                    (prompt + "||" + "||".join(choices)).encode("utf-8", "ignore")
                ).hexdigest()
                if fp == last_fp:
                    time.sleep(0.35)
                    continue
                last_fp = fp

                pick, reason = advise(prompt, choices)
                print("-" * 56)
                if prompt:
                    print(f"SITUATION: {prompt[:220]}{'…' if len(prompt) > 220 else ''}")
                print("CHOIX:")
                for i, ch in enumerate(choices, 1):
                    mark = " <<<" if ch == pick else ""
                    print(f"  {i}. {ch}{mark}")
                print(f"\n>>> PRENDS: {pick}")
                print(f"    ({reason})\n")
                time.sleep(0.35)
        except KeyboardInterrupt:
            print("\nArrêt coach.")
        finally:
            context.close()


if __name__ == "__main__":
    main()
