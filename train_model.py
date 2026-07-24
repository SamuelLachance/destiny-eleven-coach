"""
Entraîne un modèle qui prédit la QUALITÉ d'un choix (0-100 attendu).

Métrique clé: top-1 ranking accuracy sur dilemmes held-out
(est-ce que le modèle classe le bon choix #1 ?).

Usage:
  .\\.venv\\Scripts\\python build_dataset.py
  .\\.venv\\Scripts\\python train_model.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupShuffleSplit

from ml_features import FEATURE_DIM, choice_features, matrix_for_choices

DATA = Path("data/choice_samples.jsonl")
MODEL = Path("models/choice_model.joblib")


def load_rows():
    X, y, groups, meta = [], [], [], []
    if not DATA.exists():
        raise SystemExit(f"Pas de data: {DATA} — lance build_dataset.py")

    with DATA.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            prompt = row.get("prompt") or ""
            choice = row.get("choice") or ""
            label = row.get("label")
            if not choice or label is None:
                continue
            X.append(choice_features(prompt, choice))
            y.append(float(label))
            # group by event id for clean holdout
            groups.append(str(row.get("event_id") or prompt.strip().lower()[:160])
            )
            meta.append(row)
    if not X:
        raise SystemExit("Aucune ligne entraînable")
    return np.vstack(X), np.asarray(y, dtype=np.float64), np.asarray(groups), meta


def ranking_accuracy(model, meta_subset) -> float:
    """Parmi les dilemmes avec plusieurs choix labellisés, % où argmax = is_best."""
    by_prompt: dict[str, list] = defaultdict(list)
    for row in meta_subset:
        if not row.get("choices") or len(row["choices"]) < 2:
            continue
        by_prompt[row["prompt"]].append(row)

    ok = 0
    tot = 0
    for prompt, rows in by_prompt.items():
        # un exemplaire de dilemme: scorons toutes les options du champ choices
        choices = rows[0]["choices"]
        if len(choices) < 2:
            continue
        best_set = {r["choice"] for r in rows if r.get("is_best")}
        if not best_set:
            # retrouver via labels max dans rows
            continue
        preds = model.predict(matrix_for_choices(prompt, choices))
        pick = choices[int(np.argmax(preds))]
        tot += 1
        if pick in best_set:
            ok += 1
    return (ok / tot) if tot else 0.0


def margin_on_dilemmas(model, scenarios_meta) -> float:
    """Écart moyen pred(best) - pred(worst) sur dilemmes uniques."""
    seen = set()
    margins = []
    for row in scenarios_meta:
        key = row["prompt"]
        if key in seen or not row.get("choices"):
            continue
        seen.add(key)
        choices = row["choices"]
        if len(choices) < 2:
            continue
        preds = model.predict(matrix_for_choices(key, choices))
        # best from is_best rows for this prompt in full meta — approx max label row
        best_choices = [r["choice"] for r in scenarios_meta if r["prompt"] == key and r.get("is_best")]
        if not best_choices:
            continue
        bi = choices.index(best_choices[0]) if best_choices[0] in choices else int(np.argmax(preds))
        margins.append(float(preds[bi] - preds.min()))
    return float(np.mean(margins)) if margins else 0.0


def main():
    X, y, groups, meta = load_rows()
    print(f"Samples: {len(y)} | dim={X.shape[1]} (expect {FEATURE_DIM})")
    print(f"Label mean={y.mean():.1f} std={y.std():.1f}")

    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    tr_idx, te_idx = next(gss.split(X, y, groups))
    Xtr, Xte, ytr, yte = X[tr_idx], X[te_idx], y[tr_idx], y[te_idx]
    meta_te = [meta[i] for i in te_idx]

    model = HistGradientBoostingRegressor(
        max_depth=8,
        learning_rate=0.05,
        max_iter=500,
        min_samples_leaf=5,
        l2_regularization=0.05,
        random_state=42,
    )
    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    mae = float(np.mean(np.abs(pred - yte)))
    # réentraîne sur tout pour le modèle final
    model_full = HistGradientBoostingRegressor(
        max_depth=8,
        learning_rate=0.05,
        max_iter=500,
        min_samples_leaf=5,
        l2_regularization=0.05,
        random_state=42,
    )
    model_full.fit(X, y)

    # ranking metrics on holdout prompts
    acc = ranking_accuracy(model, meta_te)
    # also on train-style full scenarios via full model
    acc_all = ranking_accuracy(model_full, meta)
    margin = margin_on_dilemmas(model_full, meta)

    print(f"MAE holdout: {mae:.2f}")
    print(f"Top-1 ranking acc (holdout dilemmas): {acc:.1%}")
    print(f"Top-1 ranking acc (all samples/dilemmas): {acc_all:.1%}")
    print(f"Mean margin best-min: {margin:.2f}")

    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model_full,
            "mae": mae,
            "n": int(len(y)),
            "rank_acc_holdout": acc,
            "rank_acc_all": acc_all,
            "margin": margin,
            "feature_dim": FEATURE_DIM,
            "objective": "choice_quality",
        },
        MODEL,
    )
    print(f"Saved -> {MODEL}")


if __name__ == "__main__":
    main()
