"""Compare methodes de ranking leak-free (GroupKFold event_id)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.model_selection import GroupKFold
from sklearn.tree import DecisionTreeClassifier

from rank_features import features, heuristic, load_dilemmas, matrix, ranking_acc as pairwise_ranking_acc


def make_pairs(dilemmas):
    """Pairwise diffs: label 1 if left is career-better than right."""
    X, y, g = [], [], []
    for d in dilemmas:
        choices = d["choices"]
        scores = d.get("scores")
        if scores is None:
            best = int(d["best_i"])
            scores = [1.0 if i == best else 0.0 for i in range(len(choices))]
        M = matrix(d["prompt"], choices)
        for i in range(len(choices)):
            for j in range(len(choices)):
                if i == j:
                    continue
                X.append(M[i] - M[j])
                y.append(1 if scores[i] > scores[j] else 0)
                g.append(d["group"])
    return np.asarray(X, float), np.asarray(y, int), np.asarray(g)


def dilemma_matrix(prompt, choices):
    bases = [features(prompt, ch) for ch in choices]
    hs = [heuristic(prompt, ch) for ch in choices]
    h_max, h_min = max(hs), min(hs)
    h_mean = float(np.mean(hs))
    rows = []
    for i, b in enumerate(bases):
        rel = np.asarray(
            [
                hs[i] / 20.0,
                (hs[i] - h_mean) / 20.0,
                1.0 if hs[i] >= h_max - 1e-9 else 0.0,
                1.0 if hs[i] <= h_min + 1e-9 else 0.0,
                len(choices) / 5.0,
            ],
            dtype=float,
        )
        rows.append(np.concatenate([b, rel]))
    return np.vstack(rows)


def expand_pointwise(dilemmas):
    X, y, g = [], [], []
    for d in dilemmas:
        M = dilemma_matrix(d["prompt"], d["choices"])
        for i in range(len(d["choices"])):
            X.append(M[i])
            y.append(1 if i == d["best_i"] else 0)
            g.append(d["group"])
    return np.asarray(X), np.asarray(y), np.asarray(g)


def pointwise_predict(clf, prompt, choices):
    M = dilemma_matrix(prompt, choices)
    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(M)
        classes = list(clf.classes_)
        idx = classes.index(1) if 1 in classes else -1
        scores = proba[:, idx]
    else:
        scores = clf.predict(M)
    return choices[int(np.argmax(scores))]


def pointwise_acc(clf, dilemmas):
    if not dilemmas:
        return 0.0
    ok = sum(
        1
        for d in dilemmas
        if pointwise_predict(clf, d["prompt"], d["choices"]) == d["choices"][d["best_i"]]
    )
    return ok / len(dilemmas)


def heur_predict(prompt, choices):
    scores = [heuristic(prompt, ch) for ch in choices]
    return choices[int(np.argmax(scores))]


def heur_acc(dilemmas):
    if not dilemmas:
        return 0.0
    ok = sum(
        1
        for d in dilemmas
        if heur_predict(d["prompt"], d["choices"]) == d["choices"][d["best_i"]]
    )
    return ok / len(dilemmas)


def blend_predict(clf, prompt, choices, w_h=0.45):
    """Melange proba ML + heuristique normalisee."""
    M = dilemma_matrix(prompt, choices)
    proba = clf.predict_proba(M)
    classes = list(clf.classes_)
    idx = classes.index(1) if 1 in classes else -1
    ml = proba[:, idx]
    hs = np.asarray([heuristic(prompt, ch) for ch in choices], float)
    # norm 0-1
    if hs.max() > hs.min():
        hn = (hs - hs.min()) / (hs.max() - hs.min())
    else:
        hn = np.zeros_like(hs)
    if ml.max() > ml.min():
        mn = (ml - ml.min()) / (ml.max() - ml.min())
    else:
        mn = ml
    score = w_h * hn + (1 - w_h) * mn
    return choices[int(np.argmax(score))]


def blend_acc(clf, dilemmas, w_h=0.45):
    ok = sum(
        1
        for d in dilemmas
        if blend_predict(clf, d["prompt"], d["choices"], w_h) == d["choices"][d["best_i"]]
    )
    return ok / len(dilemmas) if dilemmas else 0.0


def cv_eval(name, fit_fn, pred_acc_fn, dilemmas, groups_for_split, X=None, y=None, groups=None):
    by_g = {d["group"]: d for d in dilemmas}
    # split on dilemma groups
    g_list = np.asarray([d["group"] for d in dilemmas])
    # dummy X for GroupKFold on dilemmas
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    yd = np.zeros(len(dilemmas))
    gkf = GroupKFold(n_splits=min(5, len(set(g_list))))
    accs, ns = [], []
    for fold, (tr_d, te_d) in enumerate(gkf.split(Zd, yd, g_list), 1):
        tr_groups = set(g_list[tr_d])
        te_groups = set(g_list[te_d])
        assert not (tr_groups & te_groups)
        holdout = [dilemmas[i] for i in te_d]
        holdout = [d for d in holdout if str(d["group"]).startswith("ev:")] or holdout
        model = fit_fn(tr_groups)
        acc = pred_acc_fn(model, holdout)
        accs.append(acc)
        ns.append(len(holdout))
        print(f"  {name} fold{fold}: n={len(holdout)} acc={100*acc:.1f}%")
    cv = float(np.average(accs, weights=ns))
    print(f"=> {name} CV={100*cv:.1f}%\n")
    return cv


def main():
    dilemmas = load_dilemmas()
    game = [d for d in dilemmas if str(d["group"]).startswith("ev:")]
    print(f"game dilemmas={len(game)} all={len(dilemmas)}")
    print(f"heuristic alone on all game: {100*heur_acc(game):.1f}%")

    # 1) Heuristic CV
    def fit_heur(_tr):
        return None

    def acc_heur(_m, hold):
        return heur_acc(hold)

    cv_eval("heuristic", fit_heur, acc_heur, game, None)

    # 2) Pointwise HGB
    Xp, yp, gp = expand_pointwise(dilemmas)

    def fit_hgb(tr_groups):
        mask = np.array([g in tr_groups for g in gp])
        clf = HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.08,
            max_iter=200,
            min_samples_leaf=8,
            random_state=42,
        )
        clf.fit(Xp[mask], yp[mask])
        return clf

    cv_hgb = cv_eval("pointwise_HGB", fit_hgb, pointwise_acc, dilemmas, None)

    # 3) Pointwise RF
    def fit_rf(tr_groups):
        mask = np.array([g in tr_groups for g in gp])
        clf = RandomForestClassifier(
            n_estimators=120,
            max_depth=12,
            min_samples_leaf=3,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(Xp[mask], yp[mask])
        return clf

    cv_rf = cv_eval("pointwise_RF", fit_rf, pointwise_acc, dilemmas, None)

    # 4) Blend HGB + heur
    def acc_blend(m, hold):
        return blend_acc(m, hold, 0.4)

    cv_blend = cv_eval("blend_HGB+heur", fit_hgb, acc_blend, dilemmas, None)

    # 5) Pairwise HGB
    Xpair, ypair, gpair = make_pairs(dilemmas)

    def fit_pair(tr_groups):
        mask = np.array([g in tr_groups for g in gpair])
        clf = HistGradientBoostingClassifier(
            max_depth=5,
            learning_rate=0.08,
            max_iter=180,
            min_samples_leaf=10,
            random_state=0,
        )
        clf.fit(Xpair[mask], ypair[mask])
        return clf

    cv_pair = cv_eval("pairwise_HGB", fit_pair, pairwise_ranking_acc, dilemmas, None)

    print("SUMMARY")
    print(f"  heuristic CV ~ see above")
    print(f"  pointwise_HGB {100*cv_hgb:.1f}%")
    print(f"  pointwise_RF  {100*cv_rf:.1f}%")
    print(f"  blend         {100*cv_blend:.1f}%")
    print(f"  pairwise_HGB  {100*cv_pair:.1f}%")


if __name__ == "__main__":
    main()
