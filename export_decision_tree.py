"""
Ranker leak-free: meilleures methodes empiriques sur GroupKFold(event_id).

Compare:
- heuristique carriere
- LogisticRegression is_best + blend
- Ridge regression sur scores carriere (pointwise) + blend

Export JS = poids lineaires du meilleur modele.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from rank_features import (
    CLUBS,
    KEYWORDS,
    heur_best,
    heuristic,
    load_dilemmas,
    matrix,
    ranking_acc,
    resolve_best,
)

OUT_JSON = Path("docs/tree_model.json")
OUT_JOBLIB = Path("models/choice_tree.joblib")
OUT_REPORT = Path("docs/tree_train_report.json")


def expand_cls(dilemmas, soft=True, augment=False):
    X, y, g = [], [], []
    for d in dilemmas:
        best = resolve_best(d) if soft else int(d["best_i"])
        prompts = [d["prompt"]]
        if augment:
            for club in CLUBS:
                if "ton club" in d["prompt"]:
                    prompts.append(d["prompt"].replace("ton club", club))
        for pr in dict.fromkeys(prompts):
            M = matrix(pr, d["choices"])
            for i in range(len(d["choices"])):
                X.append(M[i])
                y.append(1 if i == best else 0)
                g.append(d["group"])
    return np.asarray(X, float), np.asarray(y, int), np.asarray(g)


def expand_reg(dilemmas, augment=False):
    """Cibles = scores carriere (qualites), pas juste is_best."""
    X, y, g = [], [], []
    for d in dilemmas:
        scores = d.get("scores")
        if not scores:
            scores = [1.0 if i == int(d["best_i"]) else 0.0 for i in range(len(d["choices"]))]
        prompts = [d["prompt"]]
        if augment:
            for club in CLUBS:
                if "ton club" in d["prompt"]:
                    prompts.append(d["prompt"].replace("ton club", club))
        for pr in dict.fromkeys(prompts):
            M = matrix(pr, d["choices"])
            for i, sc in enumerate(scores):
                X.append(M[i])
                y.append(float(sc))
                g.append(d["group"])
    return np.asarray(X, float), np.asarray(y, float), np.asarray(g)


def predict_lr(clf, scaler, prompt, choices):
    M = matrix(prompt, choices)
    proba = clf.predict_proba(scaler.transform(M))
    idx = list(clf.classes_).index(1) if 1 in clf.classes_ else -1
    return proba[:, idx]


def predict_ridge(reg, scaler, prompt, choices):
    return reg.predict(scaler.transform(matrix(prompt, choices)))


def blend_pick(ml_scores, prompt, choices, w_h):
    hs = np.asarray([heuristic(prompt, ch) for ch in choices], float)
    hn = (hs - hs.min()) / (hs.max() - hs.min() + 1e-9)
    ml = np.asarray(ml_scores, float)
    mn = (ml - ml.min()) / (ml.max() - ml.min() + 1e-9)
    return choices[int(np.argmax(w_h * hn + (1 - w_h) * mn))]


def fold_cv(dilemmas, method: str, w_h: float) -> float:
    g_list = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    gkf = GroupKFold(n_splits=5)
    accs, ns = [], []
    for tr, te in gkf.split(Zd, np.zeros(len(dilemmas)), g_list):
        tr_d = [dilemmas[i] for i in tr]
        te_d = [dilemmas[i] for i in te]
        assert not (set(g_list[tr]) & set(g_list[te]))

        if method == "heur":
            fn = heur_best
        elif method == "lr":
            X, y, _ = expand_cls(tr_d, soft=True, augment=True)
            sc = StandardScaler().fit(X)
            clf = LogisticRegression(
                C=0.5, max_iter=4000, class_weight="balanced", random_state=0
            )
            clf.fit(sc.transform(X), y)

            def fn(p, c, _clf=clf, _sc=sc, _w=w_h):
                if _w >= 0.999:
                    return heur_best(p, c)
                ml = predict_lr(_clf, _sc, p, c)
                if _w <= 0.001:
                    return c[int(np.argmax(ml))]
                return blend_pick(ml, p, c, _w)

        elif method == "ridge":
            X, y, _ = expand_reg(tr_d, augment=True)
            sc = StandardScaler().fit(X)
            reg = Ridge(alpha=2.0, random_state=0)
            reg.fit(sc.transform(X), y)

            def fn(p, c, _reg=reg, _sc=sc, _w=w_h):
                if _w >= 0.999:
                    return heur_best(p, c)
                ml = predict_ridge(_reg, _sc, p, c)
                if _w <= 0.001:
                    return c[int(np.argmax(ml))]
                return blend_pick(ml, p, c, _w)
        else:
            raise ValueError(method)

        a = ranking_acc(fn, te_d)
        accs.append(a)
        ns.append(len(te_d))
    return float(np.average(accs, weights=ns))


def pack_linear(kind, weights, bias, best_w, best_cv, grid, dilemmas, n_rows):
    return {
        "type": kind,
        "n_features": int(len(weights)),
        "weights": [float(x) for x in weights],
        "bias": float(bias),
        "blend_w_heuristic": float(best_w),
        "cv_top1_holdout": float(best_cv),
        "cv_grid": {k: float(v) for k, v in grid.items()},
        "chance": float(np.mean([1 / len(d["choices"]) for d in dilemmas])),
        "n_dilemmas": len(dilemmas),
        "n_train_rows": int(n_rows),
        "keywords": KEYWORDS,
        "leak_checks": {
            "group_kfold_event": True,
            "aug_only_inside_train_fold_for_cv": True,
            "eval_against_career_best_i": True,
            "metrics_holdout_only": True,
        },
    }


def absorb_scaler(coef, intercept, scaler):
    w = coef / scaler.scale_
    b = float(intercept - np.dot(coef, scaler.mean_ / scaler.scale_))
    return w, b


def main():
    dilemmas = [d for d in load_dilemmas() if str(d["group"]).startswith("ev:")]
    print(f"game={len(dilemmas)}")
    heur_cv = fold_cv(dilemmas, "heur", 1.0)
    print(f"heur CV={100*heur_cv:.1f}%")

    grid = {"heur": heur_cv}
    best = ("heur", 1.0, heur_cv)

    for method in ("lr", "ridge"):
        for w_h in [0.0, 0.25, 0.4, 0.55, 0.7, 0.85]:
            cv = fold_cv(dilemmas, method, w_h)
            key = f"{method}_w{w_h}"
            grid[key] = cv
            print(f"{key} CV={100*cv:.1f}%")
            if cv > best[2]:
                best = (method, w_h, cv)

    method, best_w, best_cv = best
    print(f"BEST {method} w_h={best_w} CV={100*best_cv:.1f}% (no leak)")

    if method == "heur":
        # Export un modele "blend" degenerate = heuristique pure (weights nuls, w_h=1)
        X, y, _ = expand_cls(dilemmas, soft=True, augment=True)
        bundle = pack_linear(
            "logistic_pointwise_blend",
            [0.0] * int(matrix(dilemmas[0]["prompt"], dilemmas[0]["choices"]).shape[1]),
            0.0,
            1.0,
            best_cv,
            grid,
            dilemmas,
            len(y),
        )
        model_obj = None
        scaler = None
    elif method == "lr":
        X, y, _ = expand_cls(dilemmas, soft=True, augment=True)
        scaler = StandardScaler().fit(X)
        clf = LogisticRegression(C=0.5, max_iter=4000, class_weight="balanced", random_state=0)
        clf.fit(scaler.transform(X), y)
        idx = list(clf.classes_).index(1) if 1 in clf.classes_ else 0
        coef = clf.coef_[idx] if clf.coef_.shape[0] > 1 else clf.coef_[0]
        intercept = float(
            clf.intercept_[idx] if len(np.atleast_1d(clf.intercept_)) > 1 else clf.intercept_[0]
        )
        w, b = absorb_scaler(coef, intercept, scaler)
        bundle = pack_linear(
            "logistic_pointwise_blend", w, b, best_w, best_cv, grid, dilemmas, len(y)
        )
        model_obj = clf
    else:
        X, y, _ = expand_reg(dilemmas, augment=True)
        scaler = StandardScaler().fit(X)
        reg = Ridge(alpha=2.0, random_state=0)
        reg.fit(scaler.transform(X), y)
        w, b = absorb_scaler(reg.coef_, float(reg.intercept_), scaler)
        bundle = pack_linear(
            "logistic_pointwise_blend", w, b, best_w, best_cv, grid, dilemmas, len(y)
        )
        bundle["underlying"] = "ridge_career_scores"
        model_obj = reg

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JOBLIB.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"model": model_obj, "scaler": scaler, "meta": bundle}, OUT_JOBLIB)
    print(f"Saved {OUT_JSON} ({OUT_JSON.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
