"""
Explore l'espace des carrieres sans enumerer 2^N:

1) Monte Carlo: N carrieres sous differentes politiques
2) CEM: optimise une politique stochastique pour maximiser P90
3) (option) counterfactual local pour relabel quelques events

Usage:
  python explore_careers.py
"""

from __future__ import annotations

import json
from pathlib import Path

from career_sim import (
    CEMPolicy,
    EliteOraclePolicy,
    RandomPolicy,
    SoftmaxElitePolicy,
    cem_optimize,
    eval_policy,
    init_cem_probs,
    load_game,
)

OUT = Path("docs/career_explore_report.json")
OUT_PROBS = Path("models/cem_policy.json")


def main():
    data = load_game()
    print(f"events={len(data.events)}")

    baselines = {
        "random": RandomPolicy(),
        "elite_oracle": EliteOraclePolicy(data),
        "softmax_explore_T1.5": SoftmaxElitePolicy(data, temperature=1.5),
        "softmax_explore_T3": SoftmaxElitePolicy(data, temperature=3.0),
    }

    report = {"method": "monte_carlo+CEM", "n_events": len(data.events), "baselines": {}}
    for name, pol in baselines.items():
        st = eval_policy(data, pol, n=500, seed0=17)
        report["baselines"][name] = st
        print(
            f"{name:24s} mean={st['mean']:.1f} p50={st['p50']:.1f} "
            f"p90={st['p90']:.1f} p95={st['p95']:.1f} max={st['max']:.1f}"
        )

    print("\n=== CEM optimize for top runs (0.35*mean + 0.65*p90) ===")
    cem_pol, hist = cem_optimize(
        data,
        iters=6,
        pop=80,
        elite_frac=0.25,
        careers_per_indiv=30,
        seed=3,
    )
    cem_stats = eval_policy(data, cem_pol, n=800, seed0=12345)
    report["cem"] = {"history": hist, "final": cem_stats}
    print(
        f"{'cem_final':24s} mean={cem_stats['mean']:.1f} p50={cem_stats['p50']:.1f} "
        f"p90={cem_stats['p90']:.1f} p95={cem_stats['p95']:.1f} max={cem_stats['max']:.1f}"
    )

    # save policy probs
    probs = {eid: p.tolist() for eid, p in cem_pol.probs.items()}
    OUT_PROBS.parent.mkdir(parents=True, exist_ok=True)
    OUT_PROBS.write_text(json.dumps({"probs": probs, "stats": cem_stats}, ensure_ascii=False), encoding="utf-8")

    # Compare vs elite oracle: how many events disagree on argmax
    flips = 0
    examples = []
    for ev in data.events:
        eid = ev["id"]
        if eid not in data.best_by_id or eid not in cem_pol.probs:
            continue
        cem_i = int(cem_pol.probs[eid].argmax())
        if cem_i != data.best_by_id[eid]:
            flips += 1
            if len(examples) < 15:
                opts = [o.get("label") for o in ev.get("options") or [] if o.get("label")]
                examples.append(
                    {
                        "id": eid,
                        "elite": opts[data.best_by_id[eid]] if data.best_by_id[eid] < len(opts) else "?",
                        "cem": opts[cem_i] if cem_i < len(opts) else "?",
                        "probs": cem_pol.probs[eid].tolist(),
                    }
                )
    report["cem_vs_elite_flips"] = flips
    report["flip_examples"] = examples
    report["note"] = (
        "Combinatorial career space explored via Monte Carlo sampling + Cross-Entropy Method; "
        "not full 2^N enumeration. Objective favors P90 (top runs)."
    )
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nflips CEM vs elite oracle: {flips}")
    for ex in examples[:8]:
        print(f"  {ex['id']}: elite='{ex['elite'][:40]}' -> cem='{ex['cem'][:40]}'")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
