"""Lookup exact des evenements Destiny Eleven deja labellises."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

SCEN_PATH = Path(__file__).resolve().parent / "data" / "game_scenarios.jsonl"

_cache: list[dict] | None = None


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _load() -> list[dict]:
    global _cache
    if _cache is not None:
        return _cache
    rows = []
    if SCEN_PATH.exists():
        with SCEN_PATH.open(encoding="utf-8") as f:
            for line in f:
                rows.append(json.loads(line))
    _cache = rows
    return rows


def lookup_best(prompt: str, choices: list[str]) -> tuple[str, str] | None:
    """Si on reconnait le dilemme jeu, renvoie (choix, raison)."""
    if len(choices) < 2:
        return None
    rows = _load()
    if not rows:
        return None

    norm_choices = [_norm(c) for c in choices]
    choice_set = set(norm_choices)

    # 1) match exact sur l'ensemble des labels (ignore ordre / tags)
    best_row = None
    best_overlap = 0
    pn = _norm(prompt)

    for row in rows:
        rc = [_norm(c) for c in row.get("choices") or []]
        if len(rc) < 2:
            continue
        overlap = len(choice_set & set(rc))
        if overlap >= 2 and overlap >= best_overlap:
            # bonus si prompt proche
            score = overlap * 10
            if pn and _norm(row.get("prompt") or "")[:60] in pn or pn[:50] in _norm(row.get("prompt") or ""):
                score += 5
            if score >= best_overlap * 10:
                best_overlap = overlap
                best_row = row

    if not best_row or best_overlap < 2:
        # 2) match prompt fort
        for row in rows:
            rp = _norm(row.get("prompt") or "")
            if len(rp) > 40 and (rp[:80] in pn or pn[:80] in rp):
                best_row = row
                break
        else:
            return None

    bi = int(best_row.get("best_i") or 0)
    labeled = best_row.get("choices") or []
    if not labeled:
        return None
    want = _norm(labeled[bi])

    # retrouver le choix UI (peut avoir un tag "Coeur: ...")
    for ch in choices:
        cn = _norm(ch)
        if cn == want or want in cn or cn in want:
            return ch, f"oracle jeu ({best_row.get('id') or 'event'})"

    # fuzzy: meilleur overlap token
    want_toks = set(want.split())
    ranked = sorted(
        choices,
        key=lambda ch: len(want_toks & set(_norm(ch).split())),
        reverse=True,
    )
    if ranked and len(want_toks & set(_norm(ranked[0]).split())) >= 2:
        return ranked[0], f"oracle jeu approx ({best_row.get('id') or 'event'})"
    return None
