"""Profil Chromium persistant — garde localStorage Destiny Eleven entre sessions."""

from __future__ import annotations

from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"

VIEWPORT = {"width": 420, "height": 820}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def ensure_profile_dir() -> Path:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR


def launch_game_context(playwright):
    """Ouvre Chromium avec profil disque (carrière = destinyEleven_current)."""
    user_data = str(ensure_profile_dir())
    context = playwright.chromium.launch_persistent_context(
        user_data,
        headless=False,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        locale="fr-FR",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return context
