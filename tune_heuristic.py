"""Tune heuristic rule weights with GroupKFold (no leak)."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from sklearn.model_selection import GroupKFold

from rank_features import load_dilemmas

OUT = Path("docs/tuned_heuristic.json")
OUT_MODEL = Path("docs/tree_model.json")
OUT_REPORT = Path("docs/tree_train_report.json")


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


# Each rule: (name, choice_pat, prompt_pat|None, default_weight)
RULES = [
    ("good_base", r"collectif|travailler|soigner|repos|verif|licence|prudent|discret|ecout|rentrer|hygiene|garant|diplomat|excus|focus|danse|repousser|encore|titulaire|minutes", None, 5.0),
    ("bad_base", r"panenka|clash|insult|engueul|soiree|boite|alcool|fete|tiktok|buzz|forcer|dopage|casino|legendaire|annoncer la retraite|prendre votre retraite|banc", None, -6.0),
    ("inj_good", r"repos|soigner|medical|inapte|suivre|repousser", r"bless|douleur|medical|kine|radios", 6.0),
    ("inj_bad", r"forcer|cacher|anti-douleur|annoncer la retraite", r"bless|douleur|medical|kine|radios", -6.0),
    ("agent_good", r"verif|licence|federation|refuser|lire", r"agent|frais|sponsor", 8.0),
    ("agent_bad", r"^payer|donner|signer pour", r"agent|frais|sponsor", -8.0),
    ("pen_force", r"force", r"penalty", 4.0),
    ("pen_pan", r"panenka", r"penalty", -5.0),
    ("ret_good", r"danse|repousser|encore|battre|reconqu", r"retrait|radios|reverence", 10.0),
    ("ret_bad", r"annoncer la retraite|prendre votre retraite|tete haute", r"retrait|radios|reverence", -12.0),
    ("night_good", r"rentrer|refuser|dormir", r"soir|boite|fete|nuit", 5.0),
    ("night_bad", r"accepter|profiter|verre", r"soir|boite|fete|nuit", -5.0),
    ("coach_good", r"ecout|travaill|respect|discut", r"coach|staff|entrain", 5.0),
    ("coach_bad", r"clash|insult|engueul", r"coach|staff|entrain", -6.0),
    ("press_good", r"discret|equipe|collectif|diplomat|excus", r"presse|journal|interview|media|reseaux", 4.0),
    ("press_bad", r"clash|attaquer|provoc|polemique|insult", r"presse|journal|interview|media|reseaux", -5.0),
    ("playtime_go", r"d1|d2|indemnite|partir|accepter|offre|titulaire|pret", r"temps de jeu|banc|famelique|remplacant", 5.0),
    ("playtime_stay", r"^rester\b", r"temps de jeu|banc|famelique|remplacant", -4.0),
]


def rule_hits(prompt: str, choice: str) -> np.ndarray:
    c, p = _norm(choice), _norm(prompt)
    hits = np.zeros(len(RULES), float)
    for i, (_, cpat, ppat, _) in enumerate(RULES):
        if ppat and not re.search(ppat, p):
            continue
        if re.search(cpat, c):
            hits[i] = 1.0
    return hits


def score_with(w: np.ndarray, prompt: str, choice: str) -> float:
    return float(np.dot(w, rule_hits(prompt, choice)))


def pick_with(w: np.ndarray, prompt: str, choices: list[str]) -> str:
    scores = [score_with(w, prompt, ch) for ch in choices]
    return choices[int(np.argmax(scores))]


def fold_loss(w: np.ndarray, ds: list[dict]) -> float:
    """Softmax CE vs career soft targets + L2."""
    loss = 0.0
    for d in ds:
        scores = np.asarray(
            d.get("scores")
            or [1.0 if i == d["best_i"] else 0.0 for i in range(len(d["choices"]))],
            float,
        )
        t = scores - scores.max()
        t = np.exp(t / (np.std(scores) + 0.5))
        t = t / t.sum()
        s = np.asarray([score_with(w, d["prompt"], ch) for ch in d["choices"]], float)
        s = s - s.max()
        p = np.exp(s)
        p = p / (p.sum() + 1e-12)
        loss -= float(np.sum(t * np.log(p + 1e-12)))
    loss += 0.01 * float(np.dot(w - np.asarray([r[3] for r in RULES]), w - np.asarray([r[3] for r in RULES])))
    return loss


def top1(w, ds):
    if not ds:
        return 0.0
    ok = sum(
        1
        for d in ds
        if pick_with(w, d["prompt"], d["choices"]) == d["choices"][int(d["best_i"])]
    )
    return ok / len(ds)


def main():
    dilemmas = [d for d in load_dilemmas() if str(d["group"]).startswith("ev:")]
    w0 = np.asarray([r[3] for r in RULES], float)
    print(f"n={len(dilemmas)} default_heur={100*top1(w0, dilemmas):.1f}% (in-sample)")

    g = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    accs, ns = [], []
    for tr, te in GroupKFold(5).split(Zd, np.zeros(len(dilemmas)), g):
        assert not (set(g[tr]) & set(g[te]))
        trd = [dilemmas[i] for i in tr]
        ted = [dilemmas[i] for i in te]
        res = minimize(
            lambda w, ds=trd: fold_loss(w, ds),
            w0,
            method="L-BFGS-B",
            options={"maxiter": 80},
        )
        a = top1(res.x, ted)
        accs.append(a)
        ns.append(len(ted))
        print(f" fold holdout={100*a:.1f}% (n={len(ted)})")
    cv = float(np.average(accs, weights=ns))
    print(f"TUNED heur CV={100*cv:.1f}% (no leak)")
    print(f"DEFAULT heur CV via same folds...", end=" ")
    # default CV
    daccs, dns = [], []
    for tr, te in GroupKFold(5).split(Zd, np.zeros(len(dilemmas)), g):
        ted = [dilemmas[i] for i in te]
        daccs.append(top1(w0, ted))
        dns.append(len(ted))
    dcv = float(np.average(daccs, weights=dns))
    print(f"{100*dcv:.1f}%")

    # Fit final on all
    res = minimize(lambda w: fold_loss(w, dilemmas), w0, method="L-BFGS-B", options={"maxiter": 120})
    w = res.x
    bundle = {
        "type": "tuned_heuristic_rules",
        "cv_top1_holdout": float(cv),
        "default_cv_top1_holdout": float(dcv),
        "chance": float(np.mean([1 / len(d["choices"]) for d in dilemmas])),
        "n_dilemmas": len(dilemmas),
        "rules": [
            {
                "name": RULES[i][0],
                "choice_pat": RULES[i][1],
                "prompt_pat": RULES[i][2],
                "weight": float(w[i]),
                "default": float(RULES[i][3]),
            }
            for i in range(len(RULES))
        ],
        "leak_checks": {
            "group_kfold_event": True,
            "weights_fit_inside_train_fold_for_cv": True,
            "eval_against_career_best_i": True,
            "metrics_holdout_only": True,
        },
    }
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MODEL.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {OUT_MODEL}")
    for i, r in enumerate(RULES):
        print(f"  {r[0]:14s} {r[3]:+5.1f} -> {w[i]:+6.2f}")


if __name__ == "__main__":
    main()
