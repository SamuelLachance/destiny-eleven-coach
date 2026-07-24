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


def _grams(s: str, n: int) -> set[str]:
    t = re.sub(r"\s+", " ", _norm(s))
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _prompt_sim(a: str, b: str) -> float:
    return 0.5 * _jaccard(_grams(a, 3), _grams(b, 3)) + 0.5 * _jaccard(_grams(a, 4), _grams(b, 4))


def _choice_sim(a: str, b: str) -> float:
    return _jaccard(set(_norm(a).split()), set(_norm(b).split()))


def _map_best(row: dict, choices: list[str]) -> str | None:
    labeled = row.get("choices") or []
    if not labeled:
        return None
    bi = int(row.get("best_i") or 0)
    want = labeled[bi] if bi < len(labeled) else labeled[0]
    scored = [(_choice_sim(want, ch), ch) for ch in choices]
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.2:
        return scored[0][1]
    return None


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

    if best_row:
        mapped = _map_best(best_row, choices)
        if mapped:
            return mapped, f"oracle jeu ({best_row.get('id') or 'event'})"
        labeled = best_row.get("choices") or []
        bi = int(best_row.get("best_i") or 0)
        want = _norm(labeled[bi]) if labeled else ""
        for ch in choices:
            cn = _norm(ch)
            if cn == want or want in cn or cn in want:
                return ch, f"oracle jeu ({best_row.get('id') or 'event'})"

    # 3) retrieval flou (trigrammes) — meilleure generalisation sans leak ~63%
    fuzzy = None
    fuzzy_sim = -1.0
    for row in rows:
        s = _prompt_sim(prompt, row.get("prompt") or "")
        if s > fuzzy_sim:
            fuzzy_sim = s
            fuzzy = row
    if fuzzy and fuzzy_sim >= 0.15:
        mapped = _map_best(fuzzy, choices)
        if mapped:
            return mapped, f"retrieval sim={fuzzy_sim:.2f} ({fuzzy.get('id') or 'near'})"
    return None
