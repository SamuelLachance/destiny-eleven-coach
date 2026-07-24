"""Holdout propre: split par event_id, compare ML / H / blend."""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from advisor import _score_choice, advise
from ml_features import choice_features, matrix_for_choices
from ml_model import load_model

SCEN = Path("data/game_scenarios.jsonl")


def main() -> None:
    rows = [json.loads(l) for l in SCEN.open(encoding="utf-8")]
    ids = [r["id"] for r in rows]
    rng = random.Random(42)
    ids_shuffled = ids[:]
    rng.shuffle(ids_shuffled)
    cut = max(1, int(0.2 * len(ids_shuffled)))
    te_ids = set(ids_shuffled[:cut])
    tr = [r for r in rows if r["id"] not in te_ids]
    te = [r for r in rows if r["id"] in te_ids]

    # train from scratch on train events only
    X, y = [], []
    for r in tr:
        for i, ch in enumerate(r["choices"]):
            X.append(choice_features(r["prompt"], ch))
            # sharp labels
            y.append(90.0 if i == r["best_i"] else 40.0)
    X = np.vstack(X)
    y = np.asarray(y)
    model = HistGradientBoostingRegressor(
        max_depth=4, learning_rate=0.08, max_iter=200, min_samples_leaf=12, l2_regularization=0.5, random_state=0
    )
    model.fit(X, y)

    def acc(subset, picker):
        ok = 0
        for r in subset:
            pick = picker(r)
            ok += pick == r["choices"][r["best_i"]]
        return ok / len(subset) if subset else 0.0

    def ml_pick(r):
        preds = model.predict(matrix_for_choices(r["prompt"], r["choices"]))
        return r["choices"][int(np.argmax(preds))]

    def h_pick(r):
        return max(r["choices"], key=lambda ch: _score_choice(ch, r["prompt"]))

    def blend_pick(r):
        return advise(r["prompt"], r["choices"])[0]

    # production model
    load_model(force=True)

    print(f"train events={len(tr)} holdout events={len(te)}")
    print(f"ML (retrain clean) train top1={100*acc(tr, ml_pick):.1f}%  holdout={100*acc(te, ml_pick):.1f}%")
    print(f"Heuristique alone   train={100*acc(tr, h_pick):.1f}%  holdout={100*acc(te, h_pick):.1f}%")
    print(f"Prod blend advise   train={100*acc(tr, blend_pick):.1f}%  holdout={100*acc(te, blend_pick):.1f}%")
    # chance
    chance = np.mean([1 / len(r["choices"]) for r in te])
    print(f"chance holdout ≈ {100*chance:.1f}%")


if __name__ == "__main__":
    main()
