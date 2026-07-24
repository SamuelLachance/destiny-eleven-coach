"""
Entraîne un arbre de décision SANS leakage, puis l'exporte pour GitHub Pages.

Garanties anti-leak:
1. Split / CV par `event_id` (GroupKFold) — aucun événement en train ET test
2. Pas d'augs bruitées dans le set d'eval (labels ±1)
3. Métriques reportées UNIQUEMENT sur folds holdout (jamais in-sample)
4. Le modèle exporté est re-fit sur TOUT seulement APRÈS l'évaluation
5. Assert train_groups ∩ test_groups == ∅
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
from sklearn.tree import DecisionTreeRegressor

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


def features(prompt: str, choice: str) -> list[float]:
    """Features texte only — jamais le label / is_best / raw_scores."""
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


def load_rows() -> list[dict]:
    """Charge samples propres: pas d'augs bruitées; dédup (event_id, choice)."""
    raw = []
    with SAMPLES.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            src = row.get("source") or ""
            # Exclure augs (label bruité ±1) — source de leakage / overfitting
            if src == "game_aug":
                continue
            if not row.get("choice") or row.get("label") is None:
                continue
            raw.append(row)

    # Dédup: un exemplaire par (group, choice normalisée)
    # Pour game_event multi-clubs: on garde "ton club" en priorité, sinon 1er vu
    by_key: dict[tuple[str, str], dict] = {}
    for row in raw:
        eid = row.get("event_id")
        if eid:
            group = f"ev:{eid}"
        else:
            group = f"other:{_norm(row.get('prompt') or '')[:100]}"
        ck = _norm(row.get("choice") or "")
        key = (group, ck)
        prompt = row.get("prompt") or ""
        prefer = "ton club" in prompt.lower() or "votre club" in prompt.lower()
        if key not in by_key:
            by_key[key] = {**row, "_group": group}
        elif prefer:
            by_key[key] = {**row, "_group": group}

    rows = list(by_key.values())
    return rows


def assert_no_leak(train_groups: np.ndarray, test_groups: np.ndarray, fold: int) -> None:
    inter = set(train_groups) & set(test_groups)
    if inter:
        raise RuntimeError(f"LEAK fold {fold}: {len(inter)} groups in train∩test e.g. {list(inter)[:5]}")


def ranking_acc(model, dilemmas: list[dict]) -> float:
    if not dilemmas:
        return 0.0
    ok = 0
    for d in dilemmas:
        choices = d["choices"]
        scores = [float(model.predict([features(d["prompt"], ch)])[0]) for ch in choices]
        pick = choices[int(np.argmax(scores))]
        if pick == choices[int(d["best_i"])]:
            ok += 1
    return ok / len(dilemmas)


def load_dilemmas_by_group() -> dict[str, dict]:
    """Scenarios jeu indexés par group id (un dilemme par event)."""
    out = {}
    if not SCENARIOS.exists():
        return out
    for line in SCENARIOS.open(encoding="utf-8"):
        s = json.loads(line)
        eid = s.get("id")
        if not eid or len(s.get("choices") or []) < 2:
            continue
        out[f"ev:{eid}"] = {
            "prompt": s["prompt"],
            "choices": s["choices"],
            "best_i": int(s["best_i"]),
            "id": eid,
        }
    return out


def main() -> None:
    rows = load_rows()
    if len(rows) < 50:
        raise SystemExit(f"Trop peu de samples propres: {len(rows)}")

    X = np.asarray([features(r["prompt"], r["choice"]) for r in rows], dtype=np.float64)
    y = np.asarray([float(r["label"]) for r in rows], dtype=np.float64)
    groups = np.asarray([r["_group"] for r in rows])

    # Vérif: features ne contiennent pas le label
    assert X.shape[1] == len(feature_names())
    # Corrélation label↔feature max (info, pas un leak train/test)
    corrs = []
    for j in range(X.shape[1]):
        if X[:, j].std() < 1e-9:
            continue
        corrs.append(abs(float(np.corrcoef(X[:, j], y)[0, 1])))
    print(f"samples_clean={len(y)} groups={len(set(groups))} dim={X.shape[1]}")
    print(f"max |corr(feature,y)|={max(corrs):.3f} (info; <1 attendu)")

    dilemmas = load_dilemmas_by_group()
    unique_groups = np.array(sorted(set(groups)))
    n_splits = min(5, len(unique_groups))
    if n_splits < 2:
        raise SystemExit("Pas assez de groupes pour une CV sans leak")

    gkf = GroupKFold(n_splits=n_splits)
    fold_mae = []
    fold_rank = []
    fold_sizes = []

    # Map group -> row indices for building holdout dilemmas from samples too
    for fold, (tr, te) in enumerate(gkf.split(X, y, groups), start=1):
        assert_no_leak(groups[tr], groups[te], fold)

        model = DecisionTreeRegressor(
            max_depth=8,
            min_samples_leaf=12,
            min_samples_split=24,
            random_state=42 + fold,
        )
        model.fit(X[tr], y[tr])
        pred = model.predict(X[te])
        mae = float(np.mean(np.abs(pred - y[te])))
        fold_mae.append(mae)

        # Ranking UNIQUEMENT sur events holdout (pas vus en train)
        te_groups = set(groups[te])
        holdout_dils = [dilemmas[g] for g in te_groups if g in dilemmas]
        # Si pas dans scenarios.jsonl, reconstruire depuis samples holdout
        if not holdout_dils:
            by_g: dict[str, list] = defaultdict(list)
            for i in te:
                by_g[groups[i]].append(rows[i])
            for g, rs in by_g.items():
                # besoin d'un dilemme multi-choix
                choices_map = {}
                for r in rs:
                    choices_map[r["choice"]] = r
                # best = max label
                if len(choices_map) < 2:
                    continue
                chs = list(choices_map.keys())
                best_i = int(np.argmax([choices_map[c]["label"] for c in chs]))
                holdout_dils.append(
                    {"prompt": rs[0]["prompt"], "choices": chs, "best_i": best_i, "id": g}
                )

        acc = ranking_acc(model, holdout_dils)
        fold_rank.append(acc)
        fold_sizes.append(len(holdout_dils))
        print(
            f"fold {fold}: train={len(tr)} test={len(te)} "
            f"holdout_events={len(holdout_dils)} MAE={mae:.2f} top1={100*acc:.1f}%"
        )

    cv_mae = float(np.mean(fold_mae))
    cv_rank = float(np.average(fold_rank, weights=fold_sizes)) if sum(fold_sizes) else 0.0
    print("---")
    print(f"CV MAE (holdout only): {cv_mae:.2f}")
    print(f"CV top-1 ranking (holdout events only): {100*cv_rank:.1f}%")
    print(f"Chance approx: ~{100*np.mean([1/len(d['choices']) for d in dilemmas.values()] or [0.5]):.1f}%")

    # Sanity: in-sample ranking MUST NOT être la métrique officielle
    model_all = DecisionTreeRegressor(
        max_depth=8,
        min_samples_leaf=12,
        min_samples_split=24,
        random_state=42,
    )
    model_all.fit(X, y)
    in_sample = ranking_acc(model_all, list(dilemmas.values()))
    print(f"(debug) in-sample top-1 after full fit: {100*in_sample:.1f}% — NE PAS utiliser comme perf réelle")

    if cv_rank < 0.45:
        print("WARNING: holdout top-1 proche du hasard — features/labels peu généralisables")

    bundle = {
        "type": "decision_tree_regressor",
        "keywords": KEYWORDS,
        "feature_names": feature_names(),
        "n_features": int(X.shape[1]),
        "n_samples": int(len(y)),
        "n_groups": int(len(set(groups))),
        "cv_folds": n_splits,
        "cv_mae_holdout": cv_mae,
        "cv_top1_holdout": cv_rank,
        "in_sample_top1_debug": in_sample,
        "leak_checks": {
            "group_kfold": True,
            "aug_excluded": True,
            "dedup_event_choice": True,
            "metrics_holdout_only": True,
        },
        "tree": tree_to_dict(model_all),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_JOBLIB.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model_all, "keywords": KEYWORDS, "report": bundle}, OUT_JOBLIB)
    print(f"Saved {OUT_JSON}")
    print(f"Report {OUT_REPORT}")


if __name__ == "__main__":
    main()
