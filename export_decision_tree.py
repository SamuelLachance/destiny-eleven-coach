"""
Arbre de decision — ranking DANS le dilemme, sans leak.

Idee simple:
- On ne predit pas un score abstrait isole
- On predit P(ce choix est le meilleur | prompt + autres options)
- Features = texte du choix + comparaison aux freres du meme dilemme
- Split GroupKFold par event_id (aucun event en train et test)

Export JSON pour GitHub Pages.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import GroupKFold
from sklearn.tree import DecisionTreeClassifier

SAMPLES = Path("data/choice_samples.jsonl")
SCENARIOS = Path("data/game_scenarios.jsonl")
OUT_JSON = Path("docs/tree_model.json")
OUT_JOBLIB = Path("models/choice_tree.joblib")
OUT_REPORT = Path("docs/tree_train_report.json")

KEYWORDS = [
    "collectif", "hygiene", "repos", "soigner", "medecin", "travailler",
    "verifier", "licence", "payer", "panenka", "force", "autorite",
    "legendaire", "promettre", "refuser", "rester", "accepter", "signer",
    "transfert", "offre", "salaire", "bless", "douleur", "soiree", "alcool",
    "coach", "presse", "agent", "contrat", "titulaire", "banc", "selection",
    "penalty", "derby", "clash", "prudent", "investir", "boite", "pret",
    "reseaux", "sponsor", "medical", "garanties", "focus", "staff", "inapte",
    "rentrer", "dormir", "minutes", "retraite", "danse", "repousser",
]


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _has(pat: str, text: str) -> float:
    return 1.0 if re.search(pat, text) else 0.0


def heuristic(prompt: str, choice: str) -> float:
    """Signal pro/safe compact (meme idee que le coach, pas le label Engine)."""
    c, p = _norm(choice), _norm(prompt)
    s = 0.0
    s += 5 * _has(r"collectif|travailler|soigner|repos|verif|licence|prudent|discret|ecout|rentrer|hygiene|garant|diplomat|excus|focus|danse|repousser|encore", c)
    s -= 6 * _has(r"panenka|clash|insult|engueul|soiree|boite|alcool|fete|tiktok|buzz|forcer|dopage|casino|legendaire|annoncer la retraite|prendre votre retraite", c)
    if _has(r"bless|douleur|medical|kine", p):
        s += 6 * _has(r"repos|soigner|medical|inapte|suivre", c)
        s -= 6 * _has(r"forcer|cacher|anti-douleur", c)
    if _has(r"agent|frais", p):
        s += 8 * _has(r"verif|licence|federation|refuser|lire", c)
        s -= 8 * _has(r"^payer|donner", c)
    if _has(r"penalty|penalty", p):
        s += 4 * _has(r"force", c)
        s -= 5 * _has(r"panenka", c)
    if _has(r"retrait|radios|reverence", p):
        s += 10 * _has(r"danse|repousser|encore|battre|reconqu", c)
        s -= 12 * _has(r"annoncer la retraite|prendre votre retraite|tete haute", c)
    if _has(r"soir|boite|fete|nuit", p):
        s += 5 * _has(r"rentrer|refuser|dormir", c)
        s -= 5 * _has(r"accepter|profiter|verre", c)
    return s


def base_features(prompt: str, choice: str) -> list[float]:
    p, c = _norm(prompt), _norm(choice)
    feats: list[float] = []
    for kw in KEYWORDS:
        feats.append(1.0 if kw in c else 0.0)
        feats.append(1.0 if kw in p else 0.0)
    feats.append(min(len(c), 200) / 100.0)
    feats.append(_has(r"^\s*collectif\b", c))
    feats.append(1.0 if "legendaire" in c else 0.0)
    feats.append(_has(r"prudent|sagesse", c))
    feats.append(_has(
        r"soigner|repos|verif|travailler|ecout|discret|prudent|hygiene|rentrer|"
        r"medical|present|garant|collectif|excus|focus|licence|danse|repousser",
        c,
    ))
    feats.append(_has(
        r"panenka|clash|insult|soiree|boite|alcool|fete|tiktok|buzz|forcer|"
        r"legendaire|retraite",
        c,
    ))
    h = heuristic(prompt, choice)
    feats.append(h / 20.0)
    return feats


def dilemma_matrix(prompt: str, choices: list[str]) -> np.ndarray:
    """Features absolues + relatives au dilemme (valide a l'inference: on a tous les choix)."""
    bases = [base_features(prompt, ch) for ch in choices]
    hs = [heuristic(prompt, ch) for ch in choices]
    h_max = max(hs) if hs else 0.0
    h_mean = float(np.mean(hs)) if hs else 0.0
    rows = []
    for i, b in enumerate(bases):
        rel = [
            hs[i] / 20.0,
            (hs[i] - h_mean) / 20.0,
            1.0 if hs[i] >= h_max - 1e-9 else 0.0,
            1.0 if hs[i] == min(hs) else 0.0,
            len(choices) / 5.0,
        ]
        rows.append(b + rel)
    return np.asarray(rows, dtype=np.float64)


N_BASE = len(base_features("", "x"))
N_FEATS = N_BASE + 5


def feature_names() -> list[str]:
    names = []
    for kw in KEYWORDS:
        names.append(f"c:{kw}")
        names.append(f"p:{kw}")
    names += ["len_c", "tag_collectif", "tag_legendaire", "tag_prudent", "safe", "risk", "heur_abs"]
    names += ["heur", "heur_rel", "heur_is_max", "heur_is_min", "n_choices"]
    return names


def tree_to_dict(clf) -> dict:
    t = clf.tree_
    # classes_: expect [0,1] for is_best
    classes = [int(c) for c in clf.classes_]

    def leaf_prob_best(node_id: int) -> float:
        # value shape (n_nodes, 1, n_classes) counts
        counts = t.value[node_id][0]
        total = float(counts.sum()) or 1.0
        # prob of class 1 (is_best)
        if 1 in classes:
            idx = classes.index(1)
            return float(counts[idx] / total)
        return float(counts[-1] / total)

    def rec(i: int) -> dict:
        if t.feature[i] < 0:
            return {"v": leaf_prob_best(i)}
        return {
            "f": int(t.feature[i]),
            "t": float(t.threshold[i]),
            "l": rec(t.children_left[i]),
            "r": rec(t.children_right[i]),
        }

    return rec(0)


def load_dilemmas() -> list[dict]:
    """Une ligne = un dilemme complet (pas des samples isoles)."""
    # Prefer scenarios.jsonl (canonique)
    dilemmas = []
    seen = set()
    if SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            eid = s.get("id")
            ch = s.get("choices") or []
            if not eid or eid in seen or len(ch) < 2:
                continue
            seen.add(eid)
            dilemmas.append(
                {
                    "group": f"ev:{eid}",
                    "id": eid,
                    "prompt": s["prompt"],
                    "choices": ch,
                    "best_i": int(s["best_i"]),
                    "source": "game",
                }
            )

    # Setup / manual depuis samples (groupés)
    by = defaultdict(list)
    if SAMPLES.exists():
        for line in SAMPLES.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("source") in ("game_event", "game_aug"):
                continue
            if not r.get("choice") or r.get("label") is None:
                continue
            g = f"other:{_norm(r.get('prompt') or '')[:100]}"
            by[g].append(r)
    for g, rs in by.items():
        # rebuild choices unique
        choices = []
        labels = []
        for r in rs:
            if r["choice"] in choices:
                continue
            choices.append(r["choice"])
            labels.append(float(r["label"]))
        if len(choices) < 2:
            continue
        best_i = int(np.argmax(labels))
        dilemmas.append(
            {
                "group": g,
                "id": g,
                "prompt": rs[0]["prompt"],
                "choices": choices,
                "best_i": best_i,
                "source": "other",
            }
        )
    return dilemmas


def assert_no_leak(tr_g, te_g, fold: int) -> None:
    inter = set(tr_g) & set(te_g)
    if inter:
        raise RuntimeError(f"LEAK fold {fold}: {list(inter)[:5]}")


def expand(dilemmas: list[dict]):
    X, y, groups = [], [], []
    for d in dilemmas:
        M = dilemma_matrix(d["prompt"], d["choices"])
        for i in range(len(d["choices"])):
            X.append(M[i])
            y.append(1 if i == d["best_i"] else 0)
            groups.append(d["group"])
    return np.asarray(X, float), np.asarray(y, int), np.asarray(groups)


def predict_best(clf, prompt: str, choices: list[str]) -> str:
    M = dilemma_matrix(prompt, choices)
    # predict_proba column for class 1
    if hasattr(clf, "predict_proba"):
        proba = clf.predict_proba(M)
        classes = list(clf.classes_)
        idx = classes.index(1) if 1 in classes else -1
        scores = proba[:, idx]
    else:
        scores = clf.predict(M)
    return choices[int(np.argmax(scores))]


def ranking_acc(clf, dilemmas: list[dict]) -> float:
    if not dilemmas:
        return 0.0
    ok = sum(
        1
        for d in dilemmas
        if predict_best(clf, d["prompt"], d["choices"]) == d["choices"][d["best_i"]]
    )
    return ok / len(dilemmas)


def main() -> None:
    dilemmas = load_dilemmas()
    print(f"dilemmas={len(dilemmas)}")
    X, y, groups = expand(dilemmas)
    assert X.shape[1] == N_FEATS == len(feature_names())
    print(f"rows={len(y)} pos_rate={y.mean():.2f} dim={X.shape[1]} groups={len(set(groups))}")

    n_splits = min(5, len(set(groups)))
    gkf = GroupKFold(n_splits=n_splits)
    fold_acc = []
    fold_n = []

    # index dilemmas by group for holdout lists
    by_g = {d["group"]: d for d in dilemmas}

    for fold, (tr, te) in enumerate(gkf.split(X, y, groups), 1):
        assert_no_leak(groups[tr], groups[te], fold)
        te_groups = sorted(set(groups[te]))
        holdout = [by_g[g] for g in te_groups if g in by_g]

        clf = DecisionTreeClassifier(
            max_depth=6,
            min_samples_leaf=8,
            min_samples_split=16,
            class_weight="balanced",
            random_state=40 + fold,
        )
        clf.fit(X[tr], y[tr])
        acc = ranking_acc(clf, holdout)
        fold_acc.append(acc)
        fold_n.append(len(holdout))
        print(f"fold {fold}: holdout_events={len(holdout)} top1={100*acc:.1f}%")

    cv = float(np.average(fold_acc, weights=fold_n))
    chance = float(np.mean([1 / len(d["choices"]) for d in dilemmas]))
    print("---")
    print(f"CV top-1 holdout (no leak): {100*cv:.1f}%")
    print(f"chance: {100*chance:.1f}%")

    clf_all = DecisionTreeClassifier(
        max_depth=6,
        min_samples_leaf=8,
        min_samples_split=16,
        class_weight="balanced",
        random_state=42,
    )
    clf_all.fit(X, y)
    in_sample = ranking_acc(clf_all, dilemmas)
    print(f"(debug) in-sample top1={100*in_sample:.1f}% — pas la metrique officielle")

    bundle = {
        "type": "decision_tree_classifier_is_best",
        "keywords": KEYWORDS,
        "feature_names": feature_names(),
        "n_features": N_FEATS,
        "n_dilemmas": len(dilemmas),
        "n_rows": int(len(y)),
        "cv_folds": n_splits,
        "cv_top1_holdout": cv,
        "chance": chance,
        "in_sample_top1_debug": in_sample,
        "leak_checks": {
            "group_kfold_event": True,
            "metrics_holdout_only": True,
            "relative_features_ok_at_inference": True,
        },
        "tree": tree_to_dict(clf_all),
    }
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"model": clf_all, "bundle": bundle}, OUT_JOBLIB)
    print(f"Saved {OUT_JSON}")


if __name__ == "__main__":
    main()
