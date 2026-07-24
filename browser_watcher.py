"""Watcher Playwright en thread pour le serveur web."""

from __future__ import annotations

import hashlib
import threading
import time

_thread: threading.Thread | None = None
_stop = threading.Event()


def start_watcher(state: dict) -> None:
    global _thread
    if state.get("running"):
        return
    _stop.clear()
    state["running"] = True
    state["error"] = ""
    _thread = threading.Thread(target=_run, args=(state,), daemon=True)
    _thread.start()


def stop_watcher(state: dict) -> None:
    _stop.set()
    state["running"] = False


def _run(state: dict) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        state["error"] = f"Playwright manquant: {e}"
        state["running"] = False
        return

    last_fp = ""
    context = None
    try:
        with sync_playwright() as p:
            from browser_profile_cfg import launch_game_context

            context = launch_game_context(p)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://destinyeleven.com/", wait_until="domcontentloaded")
            state["error"] = ""
            # hint UI: profil persistant
            state["profile"] = "browser_profile (localStorage garde ta carrière)"

            while not _stop.is_set():
                try:
                    from dom_extract import EXTRACT_JS

                    prompt, choices = page.evaluate(EXTRACT_JS)
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

                from advisor import advise, clean_choices

                choices = clean_choices(choices)
                if len(choices) < 2:
                    time.sleep(0.35)
                    continue

                pick, reason = advise(prompt, choices)
                if not pick:
                    time.sleep(0.35)
                    continue
                state["prompt"] = prompt
                state["choices"] = choices
                state["pick"] = pick
                state["reason"] = reason

                time.sleep(0.35)

            context.close()
            context = None
    except Exception as e:
        state["error"] = str(e)
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        state["running"] = False
