"""Features + dilemmes partages pour le ranker carriere (sans leak)."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

SAMPLES = Path("data/choice_samples.jsonl")
SCENARIOS = Path("data/game_scenarios.jsonl")

KEYWORDS = [
    "collectif", "hygiene", "repos", "soigner", "medecin", "travailler",
    "verifier", "licence", "payer", "panenka", "force", "autorite",
    "legendaire", "promettre", "refuser", "rester", "accepter", "signer",
    "transfert", "offre", "salaire", "bless", "douleur", "soiree", "alcool",
    "coach", "presse", "agent", "contrat", "titulaire", "banc", "selection",
    "penalty", "derby", "clash", "prudent", "investir", "boite", "pret",
    "reseaux", "sponsor", "medical", "garanties", "focus", "staff", "inapte",
    "rentrer", "dormir", "minutes", "retraite", "danse", "repousser",
    "ambitieux", "fidele", "diplomatique",
]

CLUBS = ["Rennes", "Metz", "Lyon", "Lille", "Monaco", "Paris", "Marseille", "Padoue", "Ajax"]


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _has(pat: str, text: str) -> float:
    return 1.0 if re.search(pat, text) else 0.0


def heuristic(prompt: str, choice: str) -> float:
    """Heuristique ELITE: upside / ambition > safe accuracy."""
    c, p = _norm(choice), _norm(prompt)
    s = 0.0
    # plafond carriere
    s += 6 * _has(
        r"ambitieux|titulaire|minutes|garant|transfert|offre|d1|selection|"
        r"requin|rivale|tout miser|prendre le match|votre compte|poing|"
        r"danse|repousser|encore|clutch",
        c,
    )
    s += 4 * _has(
        r"travailler|soigner|verif|licence|focus|collectif|ecout|hygiene",
        c,
    )
    # ruine seulement (pas tout risque)
    s -= 10 * _has(
        r"annoncer la retraite|prendre votre retraite|dopage|casino|alcool|"
        r"soiree|boite|fete|tiktok|buzz|banc",
        c,
    )
    s -= 3 * _has(r"panenka|legendaire|insult|engueul", c)
    if _has(r"bless|douleur|medical|kine|radios", p):
        # top runs: protocol souvent meilleur que all-in glass
        s += 5 * _has(r"repos|soigner|medical|inapte|suivre|protocole|repousser", c)
        s -= 4 * _has(r"forcer|cacher|anti-douleur|annoncer la retraite", c)
    if _has(r"agent|frais|sponsor|entourage", p):
        s += 6 * _has(r"ambitieux|requin|international|verif|licence", c)
        s -= 4 * _has(r"^payer|donner", c)
        s -= 2 * _has(r"rester en famille|famille", c)
    if _has(r"penalty", p):
        s += 4 * _has(r"force", c)
        s -= 5 * _has(r"panenka", c)
    if _has(r"retrait|radios|reverence", p):
        s += 12 * _has(r"danse|repousser|encore|battre|reconqu", c)
        s -= 14 * _has(r"annoncer la retraite|prendre votre retraite|tete haute", c)
    if _has(r"soir|boite|fete|nuit", p):
        s += 5 * _has(r"rentrer|refuser|dormir", c)
        s -= 6 * _has(r"accepter|profiter|verre", c)
    if _has(r"coach|staff|entrain|banc|titulaire|ombre", p):
        s += 5 * _has(r"poing|titulaire|minutes|ambitieux|discut", c)
        s += 2 * _has(r"ecout|travaill|respect", c)
        s -= 3 * _has(r"ombre|patienter|silence", c)
    if _has(r"finale|derby|decisif|grand match", p):
        s += 6 * _has(r"prendre le match|votre compte|assumer|clutch|force", c)
        s -= 2 * _has(r"jouer simple|passer|effacer", c)
    if _has(r"club formateur|poach|structure|etudes|etude|football", p):
        s += 5 * _has(r"ambitieux|rivale|tout miser|football", c)
        s -= 2 * _has(r"fidele|etudes|etude|parallele", c)
    return s


def features(prompt: str, choice: str) -> np.ndarray:
    p, c = _norm(prompt), _norm(choice)
    feats: list[float] = []
    for kw in KEYWORDS:
        feats.append(1.0 if kw in c else 0.0)
        feats.append(1.0 if kw in p else 0.0)
    feats.append(min(len(c), 200) / 100.0)
    feats.append(_has(r"collectif", c))
    feats.append(1.0 if "legendaire" in c else 0.0)
    feats.append(_has(r"prudent|sagesse|ambitieux", c))
    feats.append(
        _has(
            r"soigner|repos|verif|travailler|ecout|discret|prudent|hygiene|rentrer|"
            r"medical|garant|collectif|excus|focus|licence|danse|repousser|titulaire",
            c,
        )
    )
    feats.append(
        _has(
            r"panenka|clash|insult|soiree|boite|alcool|fete|tiktok|buzz|forcer|"
            r"legendaire|retraite|banc",
            c,
        )
    )
    h = heuristic(prompt, choice)
    feats.append(h / 20.0)
    feats.append(1.0 if h > 0 else 0.0)
    feats.append(1.0 if h < 0 else 0.0)
    return np.asarray(feats, dtype=np.float64)


def matrix(prompt: str, choices: list[str]) -> np.ndarray:
    base = [features(prompt, ch) for ch in choices]
    hs = [heuristic(prompt, ch) for ch in choices]
    hmax, hmin, hmean = max(hs), min(hs), float(np.mean(hs))
    rows = []
    for i, b in enumerate(base):
        second = sorted(hs)[-2] if len(hs) > 1 else hs[0]
        rel = [
            hs[i] / 20.0,
            (hs[i] - hmean) / 20.0,
            1.0 if hs[i] >= hmax - 1e-9 else 0.0,
            1.0 if hs[i] <= hmin + 1e-9 else 0.0,
            len(choices) / 5.0,
            1.0 if abs(hs[i] - second) < 1e-9 and hs[i] < hmax - 1e-9 else 0.0,
        ]
        rows.append(np.concatenate([b, np.asarray(rel, float)]))
    return np.vstack(rows)


def load_dilemmas() -> list[dict]:
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
            scores = s.get("raw_scores") or s.get("qualities")
            dilemmas.append(
                {
                    "group": f"ev:{eid}",
                    "id": eid,
                    "prompt": s["prompt"],
                    "choices": ch,
                    "best_i": int(s["best_i"]),
                    "scores": [float(x) for x in scores] if scores else None,
                }
            )
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
        choices, labels = [], []
        for r in rs:
            if r["choice"] in choices:
                continue
            choices.append(r["choice"])
            labels.append(float(r["label"]))
        if len(choices) < 2:
            continue
        dilemmas.append(
            {
                "group": g,
                "id": g,
                "prompt": rs[0]["prompt"],
                "choices": choices,
                "best_i": int(np.argmax(labels)),
                "scores": labels,
            }
        )
    return dilemmas


def resolve_best(d: dict) -> int:
    choices = d["choices"]
    scores = d.get("scores")
    if not scores:
        return int(d["best_i"])
    scores = np.asarray(scores, float)
    order = np.argsort(-scores)
    if len(order) >= 2 and scores[order[0]] - scores[order[1]] < 0.8:
        hs = [heuristic(d["prompt"], ch) for ch in choices]
        return int(np.argmax(hs))
    return int(np.argmax(scores))


def heur_best(prompt: str, choices: list[str]) -> str:
    hs = [heuristic(prompt, ch) for ch in choices]
    return choices[int(np.argmax(hs))]


def ranking_acc(fn, dilemmas: list[dict]) -> float:
    if not dilemmas:
        return 0.0
    ok = sum(
        1
        for d in dilemmas
        if fn(d["prompt"], d["choices"]) == d["choices"][int(d["best_i"])]
    )
    return ok / len(dilemmas)
