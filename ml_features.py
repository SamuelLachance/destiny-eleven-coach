"""Features texte pour scorer / ranger les choix Destiny Eleven."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable

import numpy as np

KEYWORDS = [
    "collectif", "hygiene", "hygiène", "repos", "soigner", "medecin", "médecin",
    "travailler", "entrain", "entraî", "verifier", "vérifier", "licence",
    "federation", "fédération", "payer", "panenka", "force", "autorite", "autorité",
    "legendaire", "légendaire", "promettre", "refuser", "rester", "accepter",
    "signer", "transfert", "offre", "salaire", "indemnite", "indemnité", "bless",
    "douleur", "sortie", "soiree", "soirée", "alcool", "coach", "presse", "media",
    "média", "agent", "contrat", "titulaire", "banc", "selection", "sélection",
    "penalty", "derby", "finale", "clash", "insulter", "excuser", "prudent",
    "investir", "boite", "boîte", "pret", "prêt", "reseaux", "réseaux", "sponsor",
    "kine", "kiné", "medical", "médical", "garanties", "diplomatique", "respect",
    "focus", "staff", "inapte", "rentrer", "dormir", "minutes", "attaquant",
    "gardien", "rennes", "paris", "dopage", "mentir", "casino", "buzz", "tiktok",
    "avocat", "financier", "leader", "rotation", "fatigue", "jet-lag", "provoc",
]

# Patterns sémantiques (signaux stables hors lexique exact)
_SAFE_PAT = re.compile(
    r"soigner|repos|vérif|verif|travailler|écouter|ecouter|discret|prudent|"
    r"hygiène|hygiene|rentrer|médical|medical|présent|present|garanties|"
    r"collectif|diplomat|excuser|focus|licence|fédération|federation",
    re.I,
)
_RISK_PAT = re.compile(
    r"panenka|clash|insulter|engueuler|soirée|soiree|boîte|boite|alcool|"
    r"fêter|feter|fete|tiktok|buzz|forcer|cacher|payer|dopage|casino|"
    r"légendaire|legendaire|drama|humilier|menacer",
    re.I,
)

N_HASH = 48
# keyword*2 + struct(10) + interactions(14) + hash(48) + heuristic(1)
FEATURE_DIM = len(KEYWORDS) * 2 + 10 + 14 + N_HASH + 1


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def _hash_bag(text: str, n: int = N_HASH) -> list[float]:
    """Char 3-grams hashés (OOV-friendly, dense)."""
    vec = [0.0] * n
    t = f"  {_norm(text)}  "
    for i in range(max(0, len(t) - 2)):
        gram = t[i : i + 3]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        vec[h % n] += 1.0
    s = sum(vec) or 1.0
    return [v / s for v in vec]


def _heuristic_feat(prompt: str, choice: str) -> float:
    try:
        from advisor import _score_choice

        return float(_score_choice(choice, prompt)) / 20.0
    except Exception:
        return 0.0


def choice_features(prompt: str, choice: str) -> np.ndarray:
    p, c = _norm(prompt), _norm(choice)
    feats: list[float] = []

    for kw in KEYWORDS:
        kw_n = _norm(kw)
        feats.append(1.0 if kw_n in c else 0.0)
        feats.append(1.0 if kw_n in p else 0.0)

    # structural
    feats.append(min(len(c), 200) / 100.0)
    feats.append(min(len(p), 400) / 200.0)
    feats.append(1.0 if re.search(r"^\s*collectif\b", c) else 0.0)
    feats.append(1.0 if re.search(r"^\s*autorite\b", c) else 0.0)
    feats.append(1.0 if "legendaire" in c else 0.0)
    feats.append(1.0 if re.search(r"^\s*prudent\b|^\s*sagesse\b|^\s*pro\b", c) else 0.0)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*k€", c)
    feats.append(float(m.group(1).replace(",", ".")) / 100.0 if m else 0.0)
    m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*m€", c)
    feats.append(float(m2.group(1).replace(",", ".")) / 10.0 if m2 else 0.0)
    feats.append(1.0 if _SAFE_PAT.search(c) else 0.0)
    feats.append(1.0 if _RISK_PAT.search(c) else 0.0)

    # prompt × choice interactions
    feats.append(1.0 if ("agent" in p and ("verif" in c or "licence" in c)) else 0.0)
    feats.append(1.0 if ("bless" in p and ("repos" in c or "soigner" in c or "medical" in c or "inapte" in c)) else 0.0)
    feats.append(1.0 if (("temps de jeu" in p or "banc" in p) and "rester" in c) else 0.0)
    feats.append(1.0 if ("penalty" in p and "force" in c) else 0.0)
    feats.append(1.0 if ("penalty" in p and "panenka" in c) else 0.0)
    feats.append(1.0 if (("soir" in p or "boite" in p or "fete" in p) and ("rentrer" in c or "refuser" in c or "dormir" in c)) else 0.0)
    feats.append(1.0 if (("coach" in p or "staff" in p) and ("ecout" in c or "travaill" in c)) else 0.0)
    feats.append(1.0 if (("coach" in p or "staff" in p) and ("clash" in c or "insult" in c or "engueul" in c)) else 0.0)
    feats.append(1.0 if (("presse" in p or "journal" in p or "interview" in p) and ("discret" in c or "collectif" in c or "diplomat" in c)) else 0.0)
    feats.append(1.0 if (("selection" in p or "convoq" in p or "national" in p) and ("present" in c or "honor" in c or "accept" in c)) else 0.0)
    feats.append(1.0 if (("invest" in p or "argent" in p or "boite de nuit" in p) and ("refus" in c or "prudent" in c or "focus" in c)) else 0.0)
    feats.append(1.0 if (("dopage" in p or "mentir" in p) and "refus" in c) else 0.0)
    feats.append(1.0 if (("transfert" in p or "offre" in p or "contrat" in p) and ("titulaire" in c or "minutes" in c or "garant" in c)) else 0.0)
    feats.append(1.0 if (("reseaux" in p or "polemique" in p or "polémique" in prompt.lower()) and ("excus" in c or "ignor" in c or "pas repond" in c)) else 0.0)

    feats.extend(_hash_bag(c + " || " + p[:120]))
    feats.append(_heuristic_feat(prompt, choice))

    arr = np.asarray(feats, dtype=np.float64)
    if arr.shape[0] != FEATURE_DIM:
        # garde-fou si KEYWORDS change
        out = np.zeros(FEATURE_DIM, dtype=np.float64)
        n = min(FEATURE_DIM, arr.shape[0])
        out[:n] = arr[:n]
        return out
    return arr


def matrix_for_choices(prompt: str, choices: Iterable[str]) -> np.ndarray:
    rows = [choice_features(prompt, ch) for ch in choices]
    if not rows:
        return np.zeros((0, FEATURE_DIM), dtype=np.float64)
    return np.vstack(rows)
