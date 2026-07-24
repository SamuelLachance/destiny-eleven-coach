"""Accuracy sur tous les scenarios du jeu (labels = Engine.netImpact)."""

from __future__ import annotations

import json
from pathlib import Path

from advisor import advise
from ml_model import load_model, ml_rank_choices


def main() -> None:
    b = load_model(force=True)
    print(
        f"model n={b.get('n')} holdout_top1={100*b.get('rank_acc_holdout',0):.1f}% "
        f"mae={b.get('mae'):.2f} margin={b.get('margin'):.1f}"
    )
    path = Path("data/game_scenarios.jsonl")
    rows = [json.loads(l) for l in path.open(encoding="utf-8")]
    ml_ok = blend_ok = soft_ok = 0
    for s in rows:
        choices = s["choices"]
        best = choices[s["best_i"]]
        scores = s.get("raw_scores") or []
        ml_pick = ml_rank_choices(s["prompt"], choices)[0][1]
        blend_pick, _ = advise(s["prompt"], choices)
        ml_ok += ml_pick == best
        blend_ok += blend_pick == best
        # soft: pas le pire si >=3 options / ou dans le top si impacts proches
        if scores:
            worst_i = int(min(range(len(scores)), key=lambda i: scores[i]))
            soft_ok += choices.index(ml_pick) != worst_i if ml_pick in choices else 0
        else:
            soft_ok += ml_pick == best
    n = len(rows)
    print(f"game events with choices: {n} / 179 total in data.js")
    print(f"ML top-1 (in-sample):    {ml_ok}/{n} = {100*ml_ok/n:.1f}%")
    print(f"blend top-1 (in-sample): {blend_ok}/{n} = {100*blend_ok/n:.1f}%")
    print(f"ML soft (!=pire):        {soft_ok}/{n} = {100*soft_ok/n:.1f}%")
    print(f"holdout top-1 (unseen events): {100*b.get('rank_acc_holdout',0):.1f}%")


if __name__ == "__main__":
    main()
