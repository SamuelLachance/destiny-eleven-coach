"""Garde les flips counterfactual seulement si marge d'objectif >= seuil."""

from __future__ import annotations

import json
from pathlib import Path

from relabel_elite import elite_score, _norm_label
from rank_features import heuristic

RAW = Path("data/game_events_raw.json")
SCEN = Path("data/game_scenarios.jsonl")
DOCS = Path("docs/scenarios.json")
REPORT = Path("docs/counterfactual_report.json")

MARGIN = 2.0  # points d'obj carrière (0.35*mean+0.65*p90)


def main():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in raw["events"] if e.get("id")}
    scenarios = [json.loads(l) for l in SCEN.open(encoding="utf-8")]
    kept_cf = 0
    reverted = 0
    for s in scenarios:
        eid = s["id"]
        objs = [float(x) for x in s.get("raw_scores") or []]
        if len(objs) < 2:
            continue
        order = sorted(range(len(objs)), key=lambda i: -objs[i])
        margin = objs[order[0]] - objs[order[1]]
        ev = by_id.get(eid)
        if not ev:
            continue
        opts = [o for o in (ev.get("options") or []) if (o.get("label") or "").strip()]
        elite_scores = [elite_score(o) for o in opts]
        elite_i = int(max(range(len(elite_scores)), key=lambda i: elite_scores[i]))
        if margin >= MARGIN:
            # keep CF best
            best_i = int(order[0])
            kept_cf += 1
            scores = objs
            goal = "counterfactual_career_p90"
        else:
            # tie / noise -> elite upside label, soft blend with CF
            best_i = elite_i
            scores = [
                0.7 * elite_scores[i] + 0.3 * (objs[i] - min(objs))
                for i in range(len(opts))
            ]
            best_i = int(max(range(len(scores)), key=lambda i: scores[i]))
            reverted += 1
            goal = "elite_with_cf_tiebreak"
        lo, hi = min(scores), max(scores)
        quals = []
        for v in scores:
            t = 0.5 if abs(hi - lo) < 1e-9 else (v - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 92.0)
        # heuristic soft tie if still tiny
        if abs(scores[order[0]] - scores[order[1]]) < 0.5:
            hs = [heuristic(s["prompt"], ch) for ch in s["choices"]]
            if max(hs) - min(hs) > 1:
                best_i = int(max(range(len(hs)), key=lambda i: hs[i]))
                quals[best_i] = max(quals[best_i], 92.0)
        s["best_i"] = best_i
        s["raw_scores"] = scores
        s["qualities"] = quals
        s["label_goal"] = goal
        s["cf_margin"] = margin

    SCEN.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in scenarios) + "\n", encoding="utf-8")
    docs = [
        {k: s[k] for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities") if k in s}
        for s in scenarios
    ]
    DOCS.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    rep = {}
    if REPORT.exists():
        rep = json.loads(REPORT.read_text(encoding="utf-8"))
    rep["margin_filter"] = MARGIN
    rep["kept_strong_cf"] = kept_cf
    rep["reverted_ties_to_elite"] = reverted
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"kept_strong_cf={kept_cf} reverted_ties={reverted} margin>={MARGIN}")


if __name__ == "__main__":
    main()
