"""Charge / utilise le modèle ML pour classer les choix."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from ml_features import matrix_for_choices

MODEL_PATH = Path(__file__).resolve().parent / "models" / "choice_model.joblib"

_bundle = None


def load_model(force: bool = False):
    global _bundle
    if _bundle is not None and not force:
        return _bundle
    if not MODEL_PATH.exists():
        _bundle = None
        return None
    _bundle = joblib.load(MODEL_PATH)
    return _bundle


def ml_rank_choices(prompt: str, choices: list[str]) -> list[tuple[float, str]]:
    """Retourne (qualité prédite, choix) triés desc. Vide si pas de modèle."""
    bundle = load_model()
    if not bundle or not choices:
        return []
    model = bundle["model"]
    X = matrix_for_choices(prompt, choices)
    preds = model.predict(X)
    ranked = sorted(zip(preds.tolist(), choices), key=lambda x: x[0], reverse=True)
    return ranked


def ml_best_choice(prompt: str, choices: list[str]) -> tuple[str, str] | None:
    ranked = ml_rank_choices(prompt, choices)
    if not ranked:
        return None
    score, choice = ranked[0]
    return choice, f"ML qualité ~{score:.1f}/100"
