"""
Relabel events for TOP-TIER careers (≈ top 10–20% / 'top 90% runs'),
not mean-EV accuracy / safe play.

Objectif: maximiser le plafond elite (upside + trophées + ambition)
tout en gardant une pénalité forte seulement pour ruine (retraite / careerEnd).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

RAW = Path("data/game_events_raw.json")
SCENARIOS = Path("data/game_scenarios.jsonl")
SAMPLES = Path("data/choice_samples.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")

# Soft disaster: blesse une run elite mais n'est pas retire
DISASTER = -22.0


def _norm_label(o: dict) -> str:
    lab = o.get("label") or ""
    if o.get("hint"):
        lab = f"{o['hint']}: {lab}"
    if o.get("tag"):
        lab = f"{o['tag']}: {lab}"
    return lab


def _career_of(oc: dict) -> float:
    if oc.get("career") is not None:
        return float(oc["career"])
    return 0.0


def _is_ruin(oc: dict) -> bool:
    fx = oc.get("fx") or {}
    if fx.get("retire") is True or fx.get("retire") == 1:
        return True
    if fx.get("careerEnd") or fx.get("end"):
        return True
    return False


def _has_trophy(oc: dict) -> bool:
    fx = oc.get("fx") or {}
    return bool(fx.get("trophy") or fx.get("ballon") or fx.get("award"))


def _ambition_bonus(label: str) -> float:
    c = (label or "").lower()
    s = 0.0
    # chase ceiling
    if re.search(r"ambitieux|tout miser|requin|rivale|d1\b|offre|transfert|partir|signer", c):
        s += 4.0
    if re.search(r"poing|prendre le match|votre compte|œil pour œil|oeil pour oeil|forcer le retour|génie|genie", c):
        s += 3.5
    if re.search(r"titulaire|minutes|temps de jeu|garanties|sélection|selection", c):
        s += 3.0
    if re.search(r"dernière danse|derniere danse|repousser|encore", c):
        s += 5.0
    # still avoid career suicide text
    if re.search(r"annoncer la retraite|prendre votre retraite|tête haute|tete haute", c):
        s -= 20.0
    # mild: pure safe/hide often caps ceiling
    if re.search(r"rester fidèle|rester en famille|ombre|études|etudes|protocole jusqu|ignorer royalement|jouer simple", c):
        s -= 1.5
    return s


def weighted_parts(outcomes: list[dict]):
    if not outcomes:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    items = []
    tw = sum(float(o.get("weight") or 1) for o in outcomes) or 1.0
    for o in outcomes:
        w = float(o.get("weight") or 1) / tw
        items.append(( _career_of(o), w, o))
    mean = sum(v * w for v, w, _ in items)
    # upper mass ≈ best 35% probability (elite tail)
    items_desc = sorted(items, key=lambda x: x[0], reverse=True)
    need, got, upper_sum = 0.35, 0.0, 0.0
    for v, w, _ in items_desc:
        take = min(w, need - got)
        if take <= 0:
            break
        upper_sum += v * take
        got += take
    upper = upper_sum / got if got > 0 else mean
    mx = max(v for v, _, _ in items)
    ruin_p = sum(w for v, w, o in items if _is_ruin(o) or v <= -40)
    disaster_p = sum(w for v, w, o in items if (not _is_ruin(o)) and v <= DISASTER)
    trophy_p = sum(w for v, w, o in items if _has_trophy(o))
    return mean, upper, mx, ruin_p, disaster_p, trophy_p


def elite_score(option: dict) -> float:
    """Score risque-intelligent: upside elite > moyenne safe."""
    outs = option.get("outcomes") or []
    mean, upper, mx, ruin_p, disaster_p, trophy_p = weighted_parts(outs)
    # 25% mean (floor) + 50% upper-tail + 25% max jackpot
    base = 0.25 * mean + 0.50 * upper + 0.25 * mx
    base += 8.0 * trophy_p  # trophées = levier top runs
    base -= 90.0 * ruin_p   # retraite / fin = mort pour top 90%
    base -= 12.0 * disaster_p  # blessure grave: coûteux mais pas veto total
    base += _ambition_bonus(_norm_label(option))
    # expectedCareer from scrape as weak prior if no outcomes
    if not outs and option.get("expectedCareer") is not None:
        base = float(option["expectedCareer"]) + _ambition_bonus(_norm_label(option))
    return base


def label_from_scores(s: float, scores: list[float]) -> float:
    lo, hi = min(scores), max(scores)
    if abs(hi - lo) < 1e-9:
        return 72.0
    t = (s - lo) / (hi - lo)
    return 35.0 + 55.0 * t


def rebuild():
    data = json.loads(RAW.read_text(encoding="utf-8"))
    scenarios = []
    rows = []
    flips = 0
    for ev in data.get("events") or []:
        opts = [o for o in (ev.get("options") or []) if (o.get("label") or "").strip()]
        if len(opts) < 2:
            continue
        labels = [_norm_label(o) for o in opts]
        raw = [elite_score(o) for o in opts]
        # old mean for comparison
        old = []
        for o in opts:
            outs = o.get("outcomes") or []
            if not outs:
                old.append(float(o.get("expectedCareer") or 0))
            else:
                tw = sum(float(x.get("weight") or 1) for x in outs) or 1
                old.append(sum(float(x.get("weight") or 1) / tw * _career_of(x) for x in outs))
        best_i = int(max(range(len(raw)), key=lambda i: raw[i]))
        old_i = int(max(range(len(old)), key=lambda i: old[i]))
        if best_i != old_i:
            flips += 1
        quals = [label_from_scores(s, raw) for s in raw]
        quals[best_i] = max(quals[best_i], 90.0)
        # do NOT crush runners-up: near-elite options stay learnable
        for i in range(len(quals)):
            if i != best_i and raw[i] >= sorted(raw, reverse=True)[1] - 1e-9:
                quals[i] = max(quals[i], 75.0)
        prompt = (ev.get("text") or "").replace("{club}", "ton club").replace("{name}", "toi").replace("{Club}", "ton club")
        scenarios.append(
            {
                "id": ev.get("id"),
                "cat": ev.get("cat"),
                "prompt": prompt,
                "choices": labels,
                "best_i": best_i,
                "raw_scores": raw,
                "qualities": quals,
                "label_goal": "elite_top_runs",
                "old_best_i": old_i,
            }
        )
        for i, lab in enumerate(labels):
            rows.append(
                {
                    "prompt": prompt,
                    "choice": lab,
                    "label": quals[i],
                    "is_best": i == best_i,
                    "choices": labels,
                    "source": "game_event",
                    "event_id": ev.get("id"),
                    "cat": ev.get("cat"),
                }
            )

    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    # keep unique scenarios for Pages
    uniq = []
    seen = set()
    for s in scenarios:
        eid = s.get("id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        uniq.append({k: s[k] for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities")})
    DOCS_SCEN.write_text(json.dumps(uniq, ensure_ascii=False), encoding="utf-8")

    # rewrite samples: keep non-game rows if any, replace game_*
    kept = []
    if SAMPLES.exists():
        for line in SAMPLES.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("source") in ("game_event", "game_aug"):
                continue
            kept.append(r)
    with SAMPLES.open("w", encoding="utf-8") as f:
        for r in kept + rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"scenarios={len(scenarios)} flips_vs_meanEV={flips} ({100*flips/max(len(scenarios),1):.0f}%)")
    # show a few flips toward risk
    shown = 0
    for s in scenarios:
        if s["best_i"] == s["old_best_i"]:
            continue
        print(
            f"  {s['id']}: EV='{s['choices'][s['old_best_i']][:42]}' -> ELITE='{s['choices'][s['best_i']][:42]}'"
        )
        shown += 1
        if shown >= 12:
            break


if __name__ == "__main__":
    rebuild()
