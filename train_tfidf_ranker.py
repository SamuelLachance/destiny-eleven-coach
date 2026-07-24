"""TF-IDF + linear ranker, GroupKFold by event (no leak)."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import FeatureUnion

from rank_features import heur_best, heuristic, load_dilemmas, ranking_acc

OUT_JSON = Path("docs/tree_model.json")
OUT_REPORT = Path("docs/tree_train_report.json")
OUT_JOBLIB = Path("models/choice_tree.joblib")


def text_of(prompt: str, choice: str) -> str:
    return f"CHOICE: {choice}\nPROMPT: {prompt}"


def soft_targets(d):
    scores = np.asarray(
        d.get("scores")
        or [1.0 if i == d["best_i"] else 0.0 for i in range(len(d["choices"]))],
        float,
    )
    t = scores - scores.max()
    t = np.exp(t / (np.std(scores) + 0.5))
    return t / t.sum()


def build_xy(ds, mode="cls"):
    texts, y, g = [], [], []
    for d in ds:
        best = int(d["best_i"])
        scores = d.get("scores") or [
            1.0 if i == best else 0.0 for i in range(len(d["choices"]))
        ]
        for i, ch in enumerate(d["choices"]):
            texts.append(text_of(d["prompt"], ch))
            g.append(d["group"])
            if mode == "cls":
                y.append(1 if i == best else 0)
            else:
                y.append(float(scores[i]))
    return texts, np.asarray(y), np.asarray(g)


def make_vec():
    return FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=4000,
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    max_features=4000,
                    sublinear_tf=True,
                ),
            ),
        ]
    )


def blend_pick(ml, prompt, choices, w_h):
    hs = np.asarray([heuristic(prompt, ch) for ch in choices], float)
    hn = (hs - hs.min()) / (hs.max() - hs.min() + 1e-9)
    ml = np.asarray(ml, float)
    mn = (ml - ml.min()) / (ml.max() - ml.min() + 1e-9)
    return choices[int(np.argmax(w_h * hn + (1 - w_h) * mn))]


def cv_method(dilemmas, mode="cls", whs=(0.0, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)):
    g = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    best = (-1.0, 1.0)
    grid = {}
    for w_h in whs:
        accs, ns = [], []
        for tr, te in GroupKFold(5).split(Zd, np.zeros(len(dilemmas)), g):
            assert not (set(g[tr]) & set(g[te]))
            trd = [dilemmas[i] for i in tr]
            ted = [dilemmas[i] for i in te]
            texts, y, _ = build_xy(trd, mode=mode)
            vec = make_vec()
            X = vec.fit_transform(texts)
            if mode == "cls":
                clf = LogisticRegression(
                    C=1.0,
                    max_iter=4000,
                    class_weight="balanced",
                    random_state=0,
                    solver="liblinear",
                )
                clf.fit(X, y)
                idx = list(clf.classes_).index(1) if 1 in clf.classes_ else -1

                def score_fn(p, c, _vec=vec, _clf=clf, _idx=idx):
                    return _clf.predict_proba(
                        _vec.transform([text_of(p, ch) for ch in c])
                    )[:, _idx]

            else:
                reg = Ridge(alpha=1.0, random_state=0)
                reg.fit(X, y)

                def score_fn(p, c, _vec=vec, _reg=reg):
                    return _reg.predict(_vec.transform([text_of(p, ch) for ch in c]))

            def fn(p, c, _w=w_h, _s=score_fn):
                if _w >= 0.999:
                    return heur_best(p, c)
                ml = _s(p, c)
                if _w <= 0.001:
                    return c[int(np.argmax(ml))]
                return blend_pick(ml, p, c, _w)

            a = ranking_acc(fn, ted)
            accs.append(a)
            ns.append(len(ted))
        cv = float(np.average(accs, weights=ns))
        grid[str(w_h)] = cv
        print(f"{mode} w_h={w_h:.2f} CV={100 * cv:.1f}%")
        if cv > best[0]:
            best = (cv, w_h)
    return best[0], best[1], grid


def export_js_compatible(dilemmas, mode, w_h, cv, grid):
    """
    TF-IDF n'est pas trivial en JS pur. On exporte un modele hybride:
    - type tfidf_sklearn_local pour Python
    - pour Pages: si TF-IDF gagne, on ship aussi un fallback heuristique + note
    Pour Pages on encode les top coefficients word unigram/bigram comme lexique.
    """
    texts, y, _ = build_xy(dilemmas, mode=mode)
    vec = make_vec()
    X = vec.fit_transform(texts)
    if mode == "cls":
        model = LogisticRegression(
            C=1.0,
            max_iter=4000,
            class_weight="balanced",
            random_state=0,
            solver="liblinear",
        )
        model.fit(X, y)
        underlying = "tfidf_logistic"
    else:
        model = Ridge(alpha=1.0, random_state=0)
        model.fit(X, y)
        underlying = "tfidf_ridge"

    # Distill top word features into a sparse JS lexicon (word analyzer only)
    word_vec = vec.transformer_list[0][1]
    # Refit word-only for export lexicon
    word_only = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=2,
        max_features=4000,
        sublinear_tf=True,
    )
    Xw = word_only.fit_transform(texts)
    if mode == "cls":
        m2 = LogisticRegression(
            C=1.0,
            max_iter=4000,
            class_weight="balanced",
            random_state=0,
            solver="liblinear",
        )
        m2.fit(Xw, y)
        coef = m2.coef_[list(m2.classes_).index(1) if 1 in m2.classes_ else 0]
        bias = float(m2.intercept_[0])
    else:
        m2 = Ridge(alpha=1.0, random_state=0)
        m2.fit(Xw, y)
        coef = m2.coef_
        bias = float(m2.intercept_)

    feats = word_only.get_feature_names_out()
    # keep top abs weights
    order = np.argsort(-np.abs(coef))[:800]
    lexicon = {str(feats[i]): float(coef[i]) for i in order if abs(coef[i]) > 1e-6}

    bundle = {
        "type": "tfidf_lexicon_blend",
        "underlying": underlying,
        "blend_w_heuristic": float(w_h),
        "cv_top1_holdout": float(cv),
        "cv_grid": {k: float(v) for k, v in grid.items()},
        "chance": float(np.mean([1 / len(d["choices"]) for d in dilemmas])),
        "n_dilemmas": len(dilemmas),
        "bias": bias,
        "lexicon": lexicon,
        "leak_checks": {
            "group_kfold_event": True,
            "vectorizer_fit_inside_train_fold_for_cv": True,
            "eval_against_career_best_i": True,
            "metrics_holdout_only": True,
        },
    }
    OUT_JSON.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    OUT_REPORT.write_text(json.dumps({k: v for k, v in bundle.items() if k != "lexicon"} | {"lexicon_size": len(lexicon)}, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"vec": vec, "model": model, "meta": bundle, "word_only": word_only, "m2": m2}, OUT_JOBLIB)
    print(f"Saved {OUT_JSON} lexicon={len(lexicon)} cv={100*cv:.1f}%")
    return bundle


def main():
    dilemmas = [d for d in load_dilemmas() if str(d["group"]).startswith("ev:")]
    print(f"game={len(dilemmas)} heur={100*ranking_acc(heur_best, dilemmas):.1f}%")

    results = {}
    for mode in ("cls", "reg"):
        cv, w, grid = cv_method(dilemmas, mode=mode)
        results[mode] = (cv, w, grid)
        print(f"BEST {mode}: {100*cv:.1f}% w_h={w}")

    # pick best vs heuristic
    heur_cv = results["cls"][2].get("1.0", ranking_acc(heur_best, dilemmas))
    # recompute pure heur CV properly
    g = np.asarray([d["group"] for d in dilemmas])
    Zd = np.arange(len(dilemmas)).reshape(-1, 1)
    accs, ns = [], []
    for tr, te in GroupKFold(5).split(Zd, np.zeros(len(dilemmas)), g):
        ted = [dilemmas[i] for i in te]
        a = ranking_acc(heur_best, ted)
        accs.append(a)
        ns.append(len(ted))
    heur_cv = float(np.average(accs, weights=ns))
    print(f"heur CV={100*heur_cv:.1f}%")

    best_mode = max(results, key=lambda m: results[m][0])
    cv, w, grid = results[best_mode]
    if cv < heur_cv + 0.005:
        print("TF-IDF does not beat heuristic enough; keeping heuristic-primary export")
        # still export lexicon at best w if any improvement else heur
        if cv >= heur_cv:
            export_js_compatible(dilemmas, best_mode, w, cv, grid)
        else:
            export_js_compatible(dilemmas, best_mode, 1.0, heur_cv, {**grid, "heur": heur_cv})
    else:
        export_js_compatible(dilemmas, best_mode, w, cv, grid)


if __name__ == "__main__":
    main()
