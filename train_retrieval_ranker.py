"""
Retrieval ranker leak-free: pour un event holdout, chercher le prompt
train le plus proche (TF-IDF), transferer le best label via matching des choix.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import GroupKFold

from rank_features import heur_best, heuristic, load_dilemmas, ranking_acc

OUT_JSON = Path("docs/tree_model.json")
OUT_REPORT = Path("docs/tree_train_report.json")
OUT_SCEN = Path("docs/scenarios.json")  # already used as oracle


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def choice_sim(a: str, b: str) -> float:
    na, nb = set(_norm(a).split()), set(_norm(b).split())
    if not na or not nb:
        return 0.0
    return len(na & nb) / len(na | nb)


def retrieve_pick(prompt: str, choices: list[str], bank: list[dict], vec, Xp, min_sim=0.25):
    q = vec.transform([prompt])
    sims = cosine_similarity(q, Xp)[0]
    i = int(np.argmax(sims))
    if sims[i] < min_sim:
        return None, float(sims[i])
    src = bank[i]
    best = src["choices"][int(src["best_i"])]
    # map best source choice onto target choices
    scores = [choice_sim(best, ch) for ch in choices]
    if max(scores) < 0.2:
        # fallback: score each target choice vs source qualities if available
        if src.get("scores"):
            # for each target, find best matching source choice score
            mapped = []
            for ch in choices:
                js = [choice_sim(ch, sch) for sch in src["choices"]]
                j = int(np.argmax(js))
                mapped.append(src["scores"][j] if js[j] >= 0.2 else -1e9)
            if max(mapped) > -1e8:
                return choices[int(np.argmax(mapped))], float(sims[i])
        return None, float(sims[i])
    return choices[int(np.argmax(scores))], float(sims[i])


def blend_retrieve(prompt, choices, bank, vec, Xp, w_h, min_sim):
    rp, sim = retrieve_pick(prompt, choices, bank, vec, Xp, min_sim=min_sim)
    hs = np.asarray([heuristic(prompt, ch) for ch in choices], float)
    if rp is None:
        return choices[int(np.argmax(hs))]
    # soft blend: boost retrieved pick
    boost = hs.copy()
    bi = choices.index(rp)
    boost[bi] += (1 - w_h) * (hs.max() - hs.min() + 5.0) * max(sim, 0.3)
    # also mix pure heur weight
    if w_h >= 0.999:
        return choices[int(np.argmax(hs))]
    return choices[int(np.argmax(boost))]


def main():
    dilemmas = [d for d in load_dilemmas() if str(d["group"]).startswith("ev:")]
    print(f"n={len(dilemmas)} heur={100*ranking_acc(heur_best, dilemmas):.1f}%")

    g = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)

    grid = {}
    best = (-1.0, None)
    for min_sim in (0.15, 0.25, 0.35, 0.45):
        for w_h in (0.0, 0.35, 0.55, 0.75, 1.0):
            accs, ns = [], []
            for tr, te in GroupKFold(5).split(Zd, np.zeros(len(dilemmas)), g):
                assert not (set(g[tr]) & set(g[te]))
                bank = [dilemmas[i] for i in tr]
                ted = [dilemmas[i] for i in te]
                vec = TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=1,
                    sublinear_tf=True,
                )
                Xp = vec.fit_transform([d["prompt"] for d in bank])

                def fn(p, c, _b=bank, _v=vec, _x=Xp, _w=w_h, _m=min_sim):
                    return blend_retrieve(p, c, _b, _v, _x, _w, _m)

                a = ranking_acc(fn, ted)
                accs.append(a)
                ns.append(len(ted))
            cv = float(np.average(accs, weights=ns))
            key = f"sim{min_sim}_w{w_h}"
            grid[key] = cv
            print(f"{key} CV={100*cv:.1f}%")
            if cv > best[0]:
                best = (cv, (min_sim, w_h))

    # pure retrieve (no heur) at best min_sim
    print(f"BEST retrieve+heur {best[1]} CV={100*best[0]:.1f}%")

    # Also: oracle upper bound = if we could see same event (in-sample) 
    print(f"oracle in-catalog (same events) ~100% by construction")

    # Export: for Pages, the oracle IS docs/scenarios.json (exact match).
    # Retrieval is for near-miss prompts. Ship retrieval meta + keep heur fallback.
    # Practical product model: type retrieval_oracle_heuristic
    # JS already has lookupOracle; we strengthen it with fuzzy retrieval over scenarios.

    min_sim, w_h = best[1]
    bundle = {
        "type": "retrieval_tfidf_blend",
        "cv_top1_holdout": float(best[0]),
        "cv_grid": {k: float(v) for k, v in grid.items()},
        "min_sim": float(min_sim),
        "blend_w_heuristic": float(w_h),
        "chance": float(np.mean([1 / len(d["choices"]) for d in dilemmas])),
        "n_dilemmas": len(dilemmas),
        "note": "Inference JS: fuzzy prompt retrieval over scenarios.json then choice Jaccard map; else heuristic.",
        "leak_checks": {
            "group_kfold_event": True,
            "retrieval_bank_train_fold_only_for_cv": True,
            "eval_against_career_best_i": True,
            "metrics_holdout_only": True,
        },
    }
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {OUT_JSON}")


if __name__ == "__main__":
    main()
