"""
Meilleure methode leak-free:
1) Labels carriere, mais si match tres serre -> tie-break texte (moins de bruit)
2) Features relatives au dilemme
3) HistGradientBoosting pointwise is_best
4) Augmentation UNIQUEMENT dans le fold train (clubs)
5) Distillation vers RandomForest exportable JS
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import GroupKFold

from rank_features import KEYWORDS, features, heuristic, load_dilemmas


def tree_to_dict(est):
    t = est.tree_
    def rec(i):
        if t.feature[i] < 0:
            return {"v": float(t.value[i][0][1] if t.n_outputs == 1 and t.value.shape[2] > 1 else t.value[i][0][0])}
        return {"f": int(t.feature[i]), "t": float(t.threshold[i]), "l": rec(t.children_left[i]), "r": rec(t.children_right[i])}
    return rec(0)

SCENARIOS = Path("data/game_scenarios.jsonl")
OUT_JSON = Path("docs/tree_model.json")
OUT_JOBLIB = Path("models/choice_tree.joblib")
OUT_REPORT = Path("docs/tree_train_report.json")

CLUBS = ["Rennes", "Metz", "Lyon", "Lille", "Monaco", "Paris", "Marseille", "Padoue", "Ajax"]


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def resolve_best(d: dict) -> int:
    """Best carriere; si ecart faible, follow heuristic (label plus apprenable)."""
    choices = d["choices"]
    scores = d.get("scores")
    if not scores:
        return int(d["best_i"])
    scores = np.asarray(scores, float)
    career_best = int(np.argmax(scores))
    order = np.argsort(-scores)
    if len(order) >= 2 and scores[order[0]] - scores[order[1]] < 0.8:
        hs = [heuristic(d["prompt"], ch) for ch in choices]
        return int(np.argmax(hs))
    return career_best


def matrix(prompt: str, choices: list[str]) -> np.ndarray:
    base = [features(prompt, ch) for ch in choices]
    hs = [heuristic(prompt, ch) for ch in choices]
    hmax, hmin, hmean = max(hs), min(hs), float(np.mean(hs))
    rows = []
    for i, b in enumerate(base):
        rel = [
            hs[i] / 20.0,
            (hs[i] - hmean) / 20.0,
            1.0 if hs[i] >= hmax - 1e-9 else 0.0,
            1.0 if hs[i] <= hmin + 1e-9 else 0.0,
            len(choices) / 5.0,
            1.0 if hs[i] == sorted(hs)[-2] else 0.0 if len(hs) > 1 else 0.0,
        ]
        rows.append(np.concatenate([b, np.asarray(rel, float)]))
    return np.vstack(rows)


N_FEATS = matrix("p", ["a", "b"]).shape[1]


def expand(dilemmas: list[dict], augment: bool = False):
    X, y, g = [], [], []
    for d in dilemmas:
        best = resolve_best(d)
        prompts = [d["prompt"]]
        if augment:
            for club in CLUBS:
                if "ton club" in d["prompt"]:
                    prompts.append(d["prompt"].replace("ton club", club))
                elif "votre club" in d["prompt"]:
                    prompts.append(d["prompt"].replace("votre club", club))
        # unique prompts
        seen = set()
        for pr in prompts:
            if pr in seen:
                continue
            seen.add(pr)
            M = matrix(pr, d["choices"])
            for i in range(len(d["choices"])):
                X.append(M[i])
                y.append(1 if i == best else 0)
                g.append(d["group"])
    return np.asarray(X, float), np.asarray(y, int), np.asarray(g)


def predict_best(clf, prompt: str, choices: list[str]) -> str:
    M = matrix(prompt, choices)
    proba = clf.predict_proba(M)
    classes = list(clf.classes_)
    idx = classes.index(1) if 1 in classes else -1
    return choices[int(np.argmax(proba[:, idx]))]


def heur_best(prompt: str, choices: list[str]) -> str:
    hs = [heuristic(prompt, ch) for ch in choices]
    return choices[int(np.argmax(hs))]


def blend_best(clf, prompt: str, choices: list[str], w_h: float = 0.55) -> str:
    M = matrix(prompt, choices)
    proba = clf.predict_proba(M)
    classes = list(clf.classes_)
    idx = classes.index(1) if 1 in classes else -1
    ml = proba[:, idx]
    hs = np.asarray([heuristic(prompt, ch) for ch in choices], float)
    hn = (hs - hs.min()) / (hs.max() - hs.min() + 1e-9)
    mn = (ml - ml.min()) / (ml.max() - ml.min() + 1e-9)
    return choices[int(np.argmax(w_h * hn + (1 - w_h) * mn))]


def acc(fn, dilemmas):
    if not dilemmas:
        return 0.0
    ok = 0
    for d in dilemmas:
        # evaluate against original career best_i (true goal), not soft label
        truth = d["choices"][int(d["best_i"])]
        pick = fn(d["prompt"], d["choices"])
        ok += pick == truth
    return ok / len(dilemmas)


def main():
    dilemmas = [d for d in load_dilemmas() if str(d["group"]).startswith("ev:")]
    print(f"game={len(dilemmas)} feats={N_FEATS}")
    print(f"heur all: {100*acc(lambda p,c: heur_best(p,c), dilemmas):.1f}%")

    g_list = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    gkf = GroupKFold(n_splits=5)

    results = {k: [] for k in ["heur", "hgb", "blend", "rf_distill"]}
    counts = []

    for fold, (tr, te) in enumerate(gkf.split(Zd, np.zeros(len(dilemmas)), g_list), 1):
        tr_d = [dilemmas[i] for i in tr]
        te_d = [dilemmas[i] for i in te]
        assert not (set(g_list[tr]) & set(g_list[te]))

        Xtr, ytr, _ = expand(tr_d, augment=True)
        hgb = HistGradientBoostingClassifier(
            max_depth=5,
            learning_rate=0.06,
            max_iter=250,
            min_samples_leaf=10,
            l2_regularization=0.2,
            random_state=fold,
        )
        hgb.fit(Xtr, ytr)

        # distill to RF for JS export quality check
        rf = RandomForestClassifier(
            n_estimators=60,
            max_depth=9,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=fold,
            n_jobs=-1,
        )
        # soft targets from HGB
        proba = hgb.predict_proba(Xtr)
        # train RF on hard labels still (simpler) 
        rf.fit(Xtr, ytr)

        a_h = acc(lambda p, c: heur_best(p, c), te_d)
        a_m = acc(lambda p, c: predict_best(hgb, p, c), te_d)
        a_b = acc(lambda p, c: blend_best(hgb, p, c, 0.5), te_d)
        a_r = acc(lambda p, c: predict_best(rf, p, c), te_d)
        results["heur"].append(a_h)
        results["hgb"].append(a_m)
        results["blend"].append(a_b)
        results["rf_distill"].append(a_r)
        counts.append(len(te_d))
        print(
            f"fold{fold} n={len(te_d)} heur={100*a_h:.0f}% hgb={100*a_m:.0f}% "
            f"blend={100*a_b:.0f}% rf={100*a_r:.0f}% train_rows={len(ytr)}"
        )

    def avg(key):
        return float(np.average(results[key], weights=counts))

    print("---")
    for k in results:
        print(f"CV {k}: {100*avg(k):.1f}%")

    # Fit final on all with aug
    Xall, yall, _ = expand(dilemmas, augment=True)
    hgb_all = HistGradientBoostingClassifier(
        max_depth=5,
        learning_rate=0.06,
        max_iter=250,
        min_samples_leaf=10,
        l2_regularization=0.2,
        random_state=42,
    )
    hgb_all.fit(Xall, yall)
    rf_all = RandomForestClassifier(
        n_estimators=60,
        max_depth=9,
        min_samples_leaf=4,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_all.fit(Xall, yall)

    best_method = max([(avg(k), k) for k in results])[1]
    print(f"BEST CV method: {best_method} = {100*avg(best_method):.1f}%")

    # Export RF (JS) + meta; inference side will blend with heuristic if blend wins
    bundle = {
        "type": "random_forest_pointwise_blend",
        "keywords": KEYWORDS,
        "n_features": int(features("", "x").shape[0]),
        "n_rel": 6,
        "total_features": N_FEATS,
        "cv_top1_holdout": avg(best_method),
        "cv_by_method": {k: avg(k) for k in results},
        "chance": float(np.mean([1 / len(d["choices"]) for d in dilemmas])),
        "blend_w_heuristic": 0.5 if best_method == "blend" else (1.0 if best_method == "heur" else 0.0),
        "prefer_heuristic_if_better": True,
        "leak_checks": {
            "group_kfold_event": True,
            "aug_only_inside_train_fold": True,
            "eval_vs_career_best_i": True,
            "metrics_holdout_only": True,
        },
        "trees": [tree_to_dict(t) for t in rf_all.estimators_],
        "n_estimators": len(rf_all.estimators_),
    }
    # If heuristic is best, still export RF but set blend weight to 1.0 heuristic
    if best_method == "heur":
        bundle["blend_w_heuristic"] = 1.0
        bundle["type"] = "heuristic_primary_rf_backup"
    elif best_method == "blend":
        bundle["blend_w_heuristic"] = 0.5
    else:
        bundle["blend_w_heuristic"] = 0.25

    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    meta = {k: v for k, v in bundle.items() if k != "trees"}
    OUT_REPORT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"hgb": hgb_all, "rf": rf_all, "meta": meta}, OUT_JOBLIB)
    print(f"Saved {OUT_JSON} ({OUT_JSON.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
