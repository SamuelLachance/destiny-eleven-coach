"""
Entraîne un arbre de décision (sklearn) et l'exporte en JSON pour GitHub Pages.

Features volontairement simples = mêmes calculs possibles en JavaScript.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.tree import DecisionTreeRegressor

SAMPLES = Path("data/choice_samples.jsonl")
OUT_JSON = Path("docs/tree_model.json")
OUT_JOBLIB = Path("models/choice_tree.joblib")

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


def features(prompt: str, choice: str) -> list[float]:
    p, c = _norm(prompt), _norm(choice)
    feats: list[float] = []
    for kw in KEYWORDS:
        feats.append(1.0 if kw in c else 0.0)
        feats.append(1.0 if kw in p else 0.0)

    feats.append(min(len(c), 200) / 100.0)
    feats.append(1.0 if re.search(r"^\s*collectif\b", c) else 0.0)
    feats.append(1.0 if "legendaire" in c else 0.0)
    feats.append(1.0 if re.search(r"prudent|sagesse|^pro\b", c) else 0.0)

    safe = 1.0 if re.search(
        r"soigner|repos|verif|travailler|ecout|discret|prudent|hygiene|rentrer|"
        r"medical|present|garant|collectif|excus|focus|licence|federation|danse|repousser",
        c,
    ) else 0.0
    risk = 1.0 if re.search(
        r"panenka|clash|insult|engueul|soiree|boite|alcool|fete|tiktok|buzz|"
        r"forcer|cacher|payer|dopage|casino|legendaire|retraite",
        c,
    ) else 0.0
    feats.extend([safe, risk])

    feats.append(1.0 if ("agent" in p and ("verif" in c or "licence" in c)) else 0.0)
    feats.append(1.0 if ("bless" in p and ("repos" in c or "soigner" in c or "medical" in c)) else 0.0)
    feats.append(1.0 if (("banc" in p or "temps de jeu" in p) and "rester" in c) else 0.0)
    feats.append(1.0 if ("penalty" in p and "force" in c) else 0.0)
    feats.append(1.0 if ("penalty" in p and "panenka" in c) else 0.0)
    feats.append(1.0 if (("soir" in p or "boite" in p) and ("rentrer" in c or "refuser" in c)) else 0.0)
    feats.append(1.0 if ("retrait" in p and ("danse" in c or "repousser" in c or "encore" in c)) else 0.0)
    feats.append(1.0 if ("retrait" in p and "annoncer" in c) else 0.0)
    feats.append(1.0 if (("coach" in p or "staff" in p) and ("ecout" in c or "travaill" in c)) else 0.0)
    return feats


def feature_names() -> list[str]:
    names = []
    for kw in KEYWORDS:
        names.append(f"c:{kw}")
        names.append(f"p:{kw}")
    names += [
        "len_c", "tag_collectif", "tag_legendaire", "tag_prudent",
        "safe", "risk",
        "ix_agent_verif", "ix_bless_care", "ix_bench_stay", "ix_pen_force",
        "ix_pen_panenka", "ix_party_refuse", "ix_retire_continue", "ix_retire_quit",
        "ix_coach_listen",
    ]
    return names


def tree_to_dict(tree) -> dict:
    t = tree.tree_

    def rec(i: int) -> dict:
        if t.feature[i] < 0:
            return {"v": float(t.value[i][0][0])}
        return {
            "f": int(t.feature[i]),
            "t": float(t.threshold[i]),
            "l": rec(t.children_left[i]),
            "r": rec(t.children_right[i]),
        }

    return rec(0)


def main() -> None:
    X, y, groups = [], [], []
    with SAMPLES.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            prompt = row.get("prompt") or ""
            choice = row.get("choice") or ""
            label = row.get("label")
            if not choice or label is None:
                continue
            X.append(features(prompt, choice))
            y.append(float(label))
            groups.append(str(row.get("event_id") or prompt[:80]))

    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    print(f"samples={len(y)} dim={X.shape[1]}")

    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    tr, te = next(gss.split(X, y, groups))
    model = DecisionTreeRegressor(
        max_depth=10,
        min_samples_leaf=8,
        random_state=42,
    )
    model.fit(X[tr], y[tr])
    pred = model.predict(X[te])
    mae = float(np.mean(np.abs(pred - y[te])))

    # ranking acc holdout by group
    by = {}
    meta_te = []
    # rebuild meta from file for te indices is hard; eval on full dilemmas after fit-all

    model_full = DecisionTreeRegressor(max_depth=10, min_samples_leaf=8, random_state=42)
    model_full.fit(X, y)

    # ranking on unique scenarios file if present
    scen_path = Path("data/game_scenarios.jsonl")
    ok = tot = 0
    if scen_path.exists():
        for line in scen_path.open(encoding="utf-8"):
            s = json.loads(line)
            choices = s.get("choices") or []
            if len(choices) < 2:
                continue
            scores = [model_full.predict([features(s["prompt"], ch)])[0] for ch in choices]
            pick = choices[int(np.argmax(scores))]
            best = choices[int(s["best_i"])]
            tot += 1
            ok += pick == best

    print(f"MAE holdout: {mae:.2f}")
    print(f"nodes: {model_full.tree_.node_count}")
    if tot:
        print(f"game top-1: {ok}/{tot} = {100*ok/tot:.1f}%")

    bundle = {
        "type": "decision_tree_regressor",
        "keywords": KEYWORDS,
        "feature_names": feature_names(),
        "n_features": int(X.shape[1]),
        "mae_holdout": mae,
        "n_samples": int(len(y)),
        "game_top1": (ok / tot) if tot else None,
        "tree": tree_to_dict(model_full),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_JOBLIB.parent.mkdir(parents=True, exist_ok=True)
    try:
        import joblib

        joblib.dump({"model": model_full, "keywords": KEYWORDS}, OUT_JOBLIB)
    except Exception:
        pass
    print(f"Saved {OUT_JSON}")


if __name__ == "__main__":
    main()
