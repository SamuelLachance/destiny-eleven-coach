"""
Relabel events by counterfactual career value.

Pour chaque event / chaque choix:
  1) spawn joueur a un age eligible
  2) forcer l'event + choix i (sample outcome)
  3) continuer la carriere avec politique elite oracle
  4) mesurer score final (mean + P90)

best_i = argmax(0.35*mean + 0.65*p90)  → objectif top runs
"""

from __future__ import annotations

import json
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from career_sim import (
    EliteOraclePolicy,
    apply_fx,
    career_score,
    load_game,
    new_player,
    n_options,
    sample_event,
    sample_outcome,
    season_tick,
)

RAW = Path("data/game_events_raw.json")
SCENARIOS = Path("data/game_scenarios.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")
OUT_REPORT = Path("docs/counterfactual_report.json")

N_ROLL = 80  # rollouts per (event, choice)
EVENTS_PER_YEAR = 3
MAX_AGE = 38
OBJ_MEAN = 0.35
OBJ_P90 = 0.65


def _norm_label(o: dict) -> str:
    lab = o.get("label") or ""
    if o.get("hint"):
        lab = f"{o['hint']}: {lab}"
    if o.get("tag"):
        lab = f"{o['tag']}: {lab}"
    return lab


def continue_career(g: dict, data, policy, rng: random.Random):
    while not g["careerEnded"] and g["age"] <= MAX_AGE:
        for _ in range(EVENTS_PER_YEAR):
            if g["careerEnded"]:
                break
            if g["injuryWeeks"] > 12:
                break
            ev = sample_event(g, data.events, rng)
            if ev is None:
                break
            opts = [o for o in (ev.get("options") or []) if o.get("label")]
            ci = policy.choose(g, ev, rng)
            ci = max(0, min(ci, len(opts) - 1))
            apply_fx(g, (sample_outcome(opts[ci], rng).get("fx") or {}))
            eid = ev.get("id")
            if ev.get("once") or rng.random() < 0.7:
                g["usedEvents"].add(eid)
            if g.get("retiring"):
                g["careerEnded"] = True
                g["careerEndReason"] = g.get("careerEndReason") or "retire"
                break
        season_tick(g, rng)
        if g.get("retiring"):
            g["careerEnded"] = True
            break
    return career_score(g)


def spawn_for_event(ev: dict, rng: random.Random) -> dict:
    cond = ev.get("cond") or {}
    a_min = int(cond.get("aMin") or 16)
    a_max = int(cond.get("aMax") or min(34, a_min + 4))
    age = rng.randint(a_min, max(a_min, a_max))
    g = new_player()
    # fast-forward age with light growth
    while g["age"] < age and not g["careerEnded"]:
        season_tick(g, rng)
    # satisfy soft conds roughly
    if "minRep" in cond:
        g["rep"] = max(g["rep"], float(cond["minRep"]) + rng.uniform(0, 5))
    if "minOvr" in cond:
        need = float(cond["minOvr"])
        while (0.4 * g["stats"]["t"] + 0.25 * g["stats"]["p"] + 0.2 * g["stats"]["m"] + 0.15 * g["stats"]["c"]) < need:
            for k in g["stats"]:
                g["stats"][k] += 1.5
    if "levels" in cond and isinstance(cond["levels"], list) and cond["levels"]:
        g["clubLevel"] = cond["levels"][len(cond["levels"]) // 2]
    if "origin" in cond:
        g["origin"] = cond["origin"]
    if "pos" in cond:
        g["position"] = cond["pos"] if isinstance(cond["pos"], str) else cond["pos"][0]
    g["peakOvr"] = max(g["peakOvr"], 0.4 * g["stats"]["t"] + 0.25 * g["stats"]["p"] + 0.2 * g["stats"]["m"] + 0.15 * g["stats"]["c"])
    return g


def value_choice(ev: dict, choice_i: int, data, n_roll: int, seed: int) -> dict:
    policy = EliteOraclePolicy(data)
    opts = [o for o in (ev.get("options") or []) if o.get("label")]
    scores = []
    for i in range(n_roll):
        rng = random.Random(seed + i * 1009 + choice_i * 17)
        g = spawn_for_event(ev, rng)
        out = sample_outcome(opts[choice_i], rng)
        apply_fx(g, out.get("fx") or {})
        g["usedEvents"].add(ev.get("id"))
        if g.get("retiring") or g.get("careerEnded"):
            scores.append(career_score(g))
            continue
        scores.append(continue_career(g, data, policy, rng))
    arr = np.asarray(scores, float)
    mean = float(arr.mean())
    p90 = float(np.percentile(arr, 90))
    return {
        "mean": mean,
        "p90": p90,
        "p50": float(np.percentile(arr, 50)),
        "obj": OBJ_MEAN * mean + OBJ_P90 * p90,
    }


def _worker(payload: dict) -> dict:
    """Process worker: evaluate one event fully."""
    data = load_game()
    ev = payload["ev"]
    n_roll = payload["n_roll"]
    seed = payload["seed"]
    n = n_options(ev)
    vals = [value_choice(ev, i, data, n_roll, seed) for i in range(n)]
    objs = [v["obj"] for v in vals]
    best_i = int(np.argmax(objs))
    return {
        "id": ev.get("id"),
        "vals": vals,
        "best_i": best_i,
        "objs": objs,
    }


def rebuild_scenarios(cf: dict[str, dict]):
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    old_best = {}
    if SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            if s.get("id") is not None:
                old_best[s["id"]] = int(s["best_i"])

    scenarios = []
    flips = []
    for ev in raw.get("events") or []:
        opts = [o for o in (ev.get("options") or []) if (o.get("label") or "").strip()]
        if len(opts) < 2:
            continue
        eid = ev.get("id")
        info = cf.get(eid)
        if not info:
            continue
        labels = [_norm_label(o) for o in opts]
        objs = info["objs"]
        best_i = int(info["best_i"])
        # qualities from objs
        lo, hi = min(objs), max(objs)
        quals = []
        for s in objs:
            t = 0.5 if abs(hi - lo) < 1e-9 else (s - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 92.0)
        prompt = (
            (ev.get("text") or "")
            .replace("{club}", "ton club")
            .replace("{Club}", "ton club")
            .replace("{name}", "toi")
        )
        row = {
            "id": eid,
            "cat": ev.get("cat"),
            "prompt": prompt,
            "choices": labels,
            "best_i": best_i,
            "raw_scores": objs,
            "qualities": quals,
            "label_goal": "counterfactual_career_p90",
            "cf_means": [v["mean"] for v in info["vals"]],
            "cf_p90s": [v["p90"] for v in info["vals"]],
        }
        scenarios.append(row)
        if old_best.get(eid) is not None and old_best[eid] != best_i:
            flips.append(
                {
                    "id": eid,
                    "old": labels[old_best[eid]] if old_best[eid] < len(labels) else "?",
                    "new": labels[best_i],
                    "objs": objs,
                }
            )

    SCENARIOS.parent.mkdir(parents=True, exist_ok=True)
    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = [
        {k: s[k] for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities")}
        for s in scenarios
    ]
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return scenarios, flips


def main():
    data = load_game()
    print(f"events={len(data.events)} rolls/choice={N_ROLL}")

    payloads = [
        {"ev": ev, "n_roll": N_ROLL, "seed": 1000 + i * 13}
        for i, ev in enumerate(data.events)
    ]

    cf = {}
    # parallel by event
    workers = max(1, min(6, (Path.cwd().anchor and 6) or 4))
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_worker, p): p["ev"].get("id") for p in payloads}
            done = 0
            for fut in as_completed(futs):
                r = fut.result()
                cf[r["id"]] = r
                done += 1
                if done % 20 == 0 or done == len(payloads):
                    print(f"  progress {done}/{len(payloads)}")
    except Exception as e:
        print("parallel failed, sequential:", e)
        for i, p in enumerate(payloads):
            r = _worker(p)
            cf[r["id"]] = r
            if (i + 1) % 20 == 0:
                print(f"  progress {i+1}/{len(payloads)}")

    scenarios, flips = rebuild_scenarios(cf)
    report = {
        "n_events": len(scenarios),
        "n_flips_vs_elite": len(flips),
        "n_roll": N_ROLL,
        "objective": f"{OBJ_MEAN}*mean + {OBJ_P90}*p90",
        "flips": flips[:40],
        "note": "Counterfactual MC: force choice then elite continuation; labels = career value.",
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"scenarios={len(scenarios)} flips_vs_previous_elite={len(flips)}")
    for f in flips[:12]:
        old = (f["old"] or "")[:36].encode("ascii", "replace").decode("ascii")
        new = (f["new"] or "")[:36].encode("ascii", "replace").decode("ascii")
        print(f"  {f['id']}: '{old}' -> '{new}' objs={[round(x,1) for x in f['objs']]}")
    print(f"Saved {SCENARIOS}, {DOCS_SCEN}, {OUT_REPORT}")

    # quick policy compare after relabel
    data2 = load_game()
    from career_sim import eval_policy, RandomPolicy

    for name, pol in [
        ("random", RandomPolicy()),
        ("cf_oracle", EliteOraclePolicy(data2)),
    ]:
        st = eval_policy(data2, pol, n=400, seed0=99)
        print(f"eval {name}: mean={st['mean']:.1f} p90={st['p90']:.1f} p95={st['p95']:.1f}")
        report[f"eval_{name}"] = st
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
