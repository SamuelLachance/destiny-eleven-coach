"""
Simulateur de carriere approx Destiny Eleven.

Impossible d'enumerer 2^100 chemins: on explore via Monte Carlo + CEM
(cross-entropy method) sur une politique par event.

Etat simplifie (assez proche du save `g`):
  stats t/p/m/c, rep, form, moral, age, traits, inj, trophies, flags, usedEvents
"""

from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RAW = Path("data/game_events_raw.json")
SCENARIOS = Path("data/game_scenarios.jsonl")


def ovr(stats: dict) -> float:
    t, p, m, c = stats["t"], stats["p"], stats["m"], stats["c"]
    return 0.4 * t + 0.25 * p + 0.2 * m + 0.15 * c


def career_score(g: dict) -> float:
    """Proxy computeCareerScore: peakOVR + rep + trophies + longevite - ruin."""
    if g.get("careerEnded") and g.get("careerEndReason") == "retire_early":
        # early retire still counts peak but loses seasons
        pass
    peak = float(g.get("peakOvr") or 0)
    rep = float(g.get("rep") or 0)
    tr = g.get("trophies") or {}
    trophies = (
        18 * tr.get("ballon", 0)
        + 14 * tr.get("worldCup", 0)
        + 10 * tr.get("continental", 0)
        + 6 * tr.get("league", 0)
        + 5 * tr.get("goldenBoot", 0)
        + 4 * tr.get("cup", 0)
    )
    seasons = max(0, int(g.get("age", 16) - 16))
    matches = float(g.get("matches") or 0)
    longevity = 1.2 * seasons + 0.02 * matches
    money = 0.01 * float(g.get("money") or 0)
    # ruin penalty already baked if ended early with low peak
    return 2.2 * peak + 0.55 * rep + trophies + longevity + money


@dataclass
class GameData:
    events: list[dict]
    best_by_id: dict[str, int]
    elite_scores: dict[str, list[float]]


def load_game() -> GameData:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    events = [e for e in raw["events"] if len([o for o in (e.get("options") or []) if o.get("label")]) >= 2]
    best, scores = {}, {}
    if SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            eid = s.get("id")
            if not eid:
                continue
            best[eid] = int(s["best_i"])
            scores[eid] = [float(x) for x in (s.get("raw_scores") or [])]
    return GameData(events=events, best_by_id=best, elite_scores=scores)


def new_player(seed_setup: dict | None = None) -> dict:
    setup = seed_setup or {}
    stats = {"t": 42.0, "p": 40.0, "m": 38.0, "c": 36.0}
    # mild origin bonuses
    origin = setup.get("origin", "quartier")
    if origin == "futsal":
        stats["t"] += 3
        stats["c"] += 1
    elif origin == "sportif":
        stats["p"] += 2
        stats["m"] += 2
    elif origin == "quartier":
        stats["t"] += 2
        stats["c"] += 2
    g = {
        "age": 16,
        "year": 0,
        "stats": stats,
        "rep": 8.0,
        "form": 60.0,
        "moral": 60.0,
        "discipline": 50.0,
        "coachRel": 50.0,
        "teamRel": 50.0,
        "money": 5.0,
        "potCap": 92.0,
        "traits": [],
        "injuryWeeks": 0,
        "peakOvr": ovr(stats),
        "position": setup.get("pos", "att"),
        "origin": origin,
        "clubLevel": setup.get("level", "d2"),
        "clubSeasons": 0,
        "abroad": False,
        "flags": {},
        "usedEvents": set(),
        "trophies": {
            "league": 0,
            "cup": 0,
            "continental": 0,
            "worldCup": 0,
            "ballon": 0,
            "goldenBoot": 0,
        },
        "matches": 0,
        "careerEnded": False,
        "careerEndReason": None,
        "retiring": False,
        "history": [],  # (event_id, choice_i, career_after_partial)
    }
    return g


def clamp(g: dict):
    st = g["stats"]
    for k in st:
        st[k] = float(max(1.0, min(g["potCap"], st[k])))
    g["rep"] = float(max(0.0, min(100.0, g["rep"])))
    g["form"] = float(max(0.0, min(100.0, g["form"])))
    g["moral"] = float(max(0.0, min(100.0, g["moral"])))
    g["peakOvr"] = max(float(g["peakOvr"]), ovr(st))


def apply_fx(g: dict, fx: dict):
    if not fx:
        return
    st = g["stats"]
    for k in ("t", "p", "m", "c"):
        if k in fx and isinstance(fx[k], (int, float)):
            st[k] += float(fx[k])
    if "rep" in fx:
        g["rep"] += float(fx["rep"])
    if "form" in fx:
        g["form"] += float(fx["form"])
    if "mor" in fx:
        g["moral"] += float(fx["mor"])
    if "dis" in fx:
        g["discipline"] += float(fx["dis"])
    if "coach" in fx:
        g["coachRel"] += float(fx["coach"])
    if "team" in fx:
        g["teamRel"] += float(fx["team"])
    if "money" in fx:
        g["money"] += float(fx["money"])
    if "inj" in fx:
        g["injuryWeeks"] = max(g["injuryWeeks"], int(float(fx["inj"])))
    if "trait" in fx:
        t = str(fx["trait"])
        if t and t not in g["traits"]:
            g["traits"].append(t)
    if "flag" in fx:
        g["flags"][str(fx["flag"])] = True
    if "trophy" in fx:
        key = str(fx["trophy"])
        mapping = {
            "league": "league",
            "cup": "cup",
            "continental": "continental",
            "worldCup": "worldCup",
            "wc": "worldCup",
            "ballon": "ballon",
            "goldenBoot": "goldenBoot",
            "golden_boot": "goldenBoot",
        }
        mk = mapping.get(key, key if key in g["trophies"] else None)
        if mk:
            g["trophies"][mk] = g["trophies"].get(mk, 0) + 1
    if "award" in fx:
        a = str(fx["award"]).lower()
        if "ballon" in a:
            g["trophies"]["ballon"] += 1
        if "boot" in a or "golden" in a:
            g["trophies"]["goldenBoot"] += 1
    if fx.get("retire") is True or fx.get("retire") == 1:
        g["retiring"] = True
        g["careerEnded"] = True
        g["careerEndReason"] = "retire"
    if fx.get("careerEnd") or fx.get("end"):
        g["careerEnded"] = True
        g["careerEndReason"] = "end"
    if isinstance(fx.get("transfer"), dict):
        # bump club level roughly
        d = fx["transfer"].get("d")
        levels = ["regional", "d2", "d1", "elite"]
        try:
            i = levels.index(g["clubLevel"])
            g["clubLevel"] = levels[min(len(levels) - 1, i + int(d or 1))]
            g["clubSeasons"] = 0
        except ValueError:
            g["clubLevel"] = "d1"
    clamp(g)


def eligible(g: dict, ev: dict) -> bool:
    if g["careerEnded"]:
        return False
    if ev.get("once") and ev.get("id") in g["usedEvents"]:
        return False
    cond = ev.get("cond") or {}
    if not isinstance(cond, dict):
        return True
    age = g["age"]
    if "aMin" in cond and age < cond["aMin"]:
        return False
    if "aMax" in cond and age > cond["aMax"]:
        return False
    if "minRep" in cond and g["rep"] < cond["minRep"]:
        return False
    if "minOvr" in cond and ovr(g["stats"]) < cond["minOvr"]:
        return False
    if "maxOvr" in cond and ovr(g["stats"]) > cond["maxOvr"]:
        return False
    if "maxForm" in cond and g["form"] > cond["maxForm"]:
        return False
    if "maxMor" in cond and g["moral"] > cond["maxMor"]:
        return False
    if "minMoney" in cond and g["money"] < cond["minMoney"]:
        return False
    if "minClubSeasons" in cond and g["clubSeasons"] < cond["minClubSeasons"]:
        return False
    if "pos" in cond:
        want = cond["pos"]
        if isinstance(want, list):
            if g["position"] not in want:
                return False
        elif g["position"] != want:
            return False
    if "levels" in cond:
        if g["clubLevel"] not in cond["levels"]:
            return False
    if "origin" in cond and g["origin"] != cond["origin"]:
        return False
    if "abroad" in cond and bool(g["abroad"]) != bool(cond["abroad"]):
        return False
    if "flag" in cond:
        fl = cond["flag"]
        if isinstance(fl, str) and not g["flags"].get(fl):
            return False
    if "trait" in cond:
        tr = cond["trait"]
        if isinstance(tr, str) and tr not in g["traits"]:
            return False
    if "chance" in cond:
        # soft gate handled at sampling via weight * chance
        pass
    if "minBallon" in cond and g["trophies"].get("ballon", 0) < cond["minBallon"]:
        return False
    return True


def sample_event(g: dict, events: list[dict], rng: random.Random) -> dict | None:
    pool = []
    weights = []
    for ev in events:
        if not eligible(g, ev):
            continue
        w = float(ev.get("w") or 1)
        cond = ev.get("cond") or {}
        if isinstance(cond, dict) and "chance" in cond:
            w *= float(cond["chance"])
        if w <= 0:
            continue
        pool.append(ev)
        weights.append(w)
    if not pool:
        return None
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for ev, w in zip(pool, weights):
        acc += w
        if r <= acc:
            return ev
    return pool[-1]


def sample_outcome(option: dict, rng: random.Random) -> dict:
    outs = option.get("outcomes") or []
    if not outs:
        return {"fx": {}, "weight": 1}
    weights = [float(o.get("weight") or 1) for o in outs]
    total = sum(weights) or 1.0
    r = rng.random() * total
    acc = 0.0
    for o, w in zip(outs, weights):
        acc += w
        if r <= acc:
            return o
    return outs[-1]


def n_options(ev: dict) -> int:
    return len([o for o in (ev.get("options") or []) if o.get("label")])


class Policy:
    def choose(self, g: dict, ev: dict, rng: random.Random) -> int:
        raise NotImplementedError


class RandomPolicy(Policy):
    def choose(self, g, ev, rng):
        return rng.randrange(n_options(ev))


class EliteOraclePolicy(Policy):
    def __init__(self, data: GameData):
        self.data = data

    def choose(self, g, ev, rng):
        eid = ev.get("id")
        if eid in self.data.best_by_id:
            bi = self.data.best_by_id[eid]
            if 0 <= bi < n_options(ev):
                return bi
        return 0


class SoftmaxElitePolicy(Policy):
    """Sample among options ~ softmax(elite_scores / T) — explores combinations."""

    def __init__(self, data: GameData, temperature: float = 1.5):
        self.data = data
        self.T = temperature

    def choose(self, g, ev, rng):
        eid = ev.get("id")
        n = n_options(ev)
        scores = self.data.elite_scores.get(eid)
        if not scores or len(scores) != n:
            return rng.randrange(n)
        x = np.asarray(scores, float) / max(self.T, 1e-6)
        x = x - x.max()
        p = np.exp(x)
        p = p / p.sum()
        return int(rng.choices(range(n), weights=p.tolist(), k=1)[0])


class CEMPolicy(Policy):
    """Per-event categorical probs over choices (learned)."""

    def __init__(self, probs: dict[str, np.ndarray]):
        self.probs = probs

    def choose(self, g, ev, rng):
        eid = ev.get("id")
        n = n_options(ev)
        p = self.probs.get(eid)
        if p is None or len(p) != n:
            return rng.randrange(n)
        p = np.asarray(p, float)
        p = np.clip(p, 1e-6, None)
        p = p / p.sum()
        return int(rng.choices(range(n), weights=p.tolist(), k=1)[0])


def season_tick(g: dict, rng: random.Random):
    """Passive season progression between events."""
    if g["injuryWeeks"] > 0:
        g["injuryWeeks"] = max(0, g["injuryWeeks"] - 8)
        g["form"] -= 2
    else:
        # matches + small growth
        played = rng.randint(18, 38)
        g["matches"] += played
        growth = 0.35 + 0.01 * max(0, g["form"] - 50) / 10
        for k in g["stats"]:
            g["stats"][k] += growth * rng.uniform(0.6, 1.3)
        g["form"] += rng.uniform(-4, 5)
        g["moral"] += rng.uniform(-3, 4)
        g["money"] += 1.5 + 0.05 * g["rep"]
    g["clubSeasons"] += 1
    g["age"] += 1
    g["year"] += 1
    # aging decline late career
    if g["age"] >= 32:
        for k in g["stats"]:
            g["stats"][k] -= rng.uniform(0.3, 1.2)
    if g["age"] >= 36 and rng.random() < 0.25:
        g["retiring"] = True
    if g["age"] >= 40:
        g["careerEnded"] = True
        g["careerEndReason"] = "age"
    clamp(g)


def simulate_career(
    data: GameData,
    policy: Policy,
    seed: int = 0,
    events_per_year: int = 4,
    max_age: int = 38,
    record_history: bool = False,
) -> dict:
    rng = random.Random(seed)
    g = new_player()
    while not g["careerEnded"] and g["age"] <= max_age:
        for _ in range(events_per_year):
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
            out = sample_outcome(opts[ci], rng)
            apply_fx(g, out.get("fx") or {})
            if ev.get("once"):
                g["usedEvents"].add(ev.get("id"))
            else:
                # soft once for spam
                if rng.random() < 0.7:
                    g["usedEvents"].add(ev.get("id"))
            if record_history:
                g["history"].append((ev.get("id"), ci, career_score(g)))
            if g["retiring"]:
                g["careerEnded"] = True
                g["careerEndReason"] = g.get("careerEndReason") or "retire"
                break
        season_tick(g, rng)
        if g["retiring"]:
            g["careerEnded"] = True
            break
    g["finalScore"] = career_score(g)
    # convert set for JSON
    g["usedEvents"] = list(g["usedEvents"])
    return g


def eval_policy(data: GameData, policy: Policy, n: int = 400, seed0: int = 0) -> dict:
    scores = []
    for i in range(n):
        g = simulate_career(data, policy, seed=seed0 + i)
        scores.append(g["finalScore"])
    arr = np.asarray(scores, float)
    return {
        "n": n,
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
    }


def init_cem_probs(data: GameData, prior: str = "elite") -> dict[str, np.ndarray]:
    probs = {}
    for ev in data.events:
        eid = ev["id"]
        n = n_options(ev)
        if prior == "elite" and eid in data.elite_scores and len(data.elite_scores[eid]) == n:
            s = np.asarray(data.elite_scores[eid], float)
            s = s - s.max()
            p = np.exp(s / 2.0)
            p = p / p.sum()
        elif prior == "oracle" and eid in data.best_by_id:
            p = np.full(n, 0.08 / max(n - 1, 1))
            bi = data.best_by_id[eid]
            if 0 <= bi < n:
                p[bi] = 0.92
            p = p / p.sum()
        else:
            p = np.ones(n) / n
        probs[eid] = p
    return probs


def cem_optimize(
    data: GameData,
    iters: int = 8,
    pop: int = 120,
    elite_frac: float = 0.2,
    careers_per_indiv: int = 25,
    seed: int = 0,
) -> tuple[CEMPolicy, list[dict]]:
    """
    Cross-Entropy Method: sample policies, keep top by P90 career score,
    update categorical probs. Explores combination space without 2^N enum.
    """
    rng = random.Random(seed)
    probs = init_cem_probs(data, prior="elite")
    hist = []
    n_elite = max(2, int(pop * elite_frac))

    for it in range(iters):
        scored = []
        for k in range(pop):
            # sample a hard policy from probs
            sampled = {}
            for eid, p in probs.items():
                n = len(p)
                # Dirichlet-like jitter
                jitter = np.array([rng.random() for _ in range(n)])
                pp = 0.85 * p + 0.15 * (jitter / jitter.sum())
                pp = pp / pp.sum()
                sampled[eid] = pp
            pol = CEMPolicy(sampled)
            # evaluate by mean of P90 proxy: average of career scores, track p90 across seeds
            stats = eval_policy(
                data,
                pol,
                n=careers_per_indiv,
                seed0=seed + it * 10000 + k * 100,
            )
            # objective = top-run oriented
            obj = 0.35 * stats["mean"] + 0.65 * stats["p90"]
            scored.append((obj, stats, sampled))
        scored.sort(key=lambda x: -x[0])
        elites = scored[:n_elite]
        # update probs = average of elite distributions
        new_probs = {}
        for eid in probs:
            acc = np.zeros_like(probs[eid])
            for _, _, samp in elites:
                acc += samp[eid]
            acc /= len(elites)
            # smooth toward previous
            new_probs[eid] = 0.7 * acc + 0.3 * probs[eid]
            new_probs[eid] = new_probs[eid] / new_probs[eid].sum()
        probs = new_probs
        best_obj, best_stats, _ = elites[0]
        hist.append({"iter": it, "best_obj": best_obj, **best_stats})
        print(
            f"CEM iter {it}: obj={best_obj:.1f} mean={best_stats['mean']:.1f} "
            f"p90={best_stats['p90']:.1f} p95={best_stats['p95']:.1f}"
        )
    return CEMPolicy(probs), hist


def counterfactual_relabel(
    data: GameData,
    policy: Policy,
    n_careers: int = 200,
    seed: int = 0,
) -> dict[str, dict]:
    """
    Pour chaque event vu, compare le score final moyen quand on force choix i
    (rollout avec policy ensuite). Approx value des choix dans le contexte carriere.
    """
    # Gather contexts: list of (seed, year_index event occurrence) is hard;
    # simpler: for each event_id, run paired sims that force choice when event first appears.
    results = {}
    for ev in data.events:
        eid = ev["id"]
        n = n_options(ev)
        if n < 2:
            continue
        means = []
        for ci in range(n):

            class ForceThenPolicy(Policy):
                def __init__(self, base, eid, forced):
                    self.base = base
                    self.eid = eid
                    self.forced = forced
                    self.done = False

                def choose(self, g, ev2, rng):
                    if (not self.done) and ev2.get("id") == self.eid:
                        self.done = True
                        return self.forced
                    return self.base.choose(g, ev2, rng)

            scores = []
            hits = 0
            for i in range(n_careers):
                pol = ForceThenPolicy(policy, eid, ci)
                g = simulate_career(data, pol, seed=seed + i + ci * 10007)
                # only count if event actually fired
                if eid in g["usedEvents"] or any(h[0] == eid for h in g.get("history") or []):
                    scores.append(g["finalScore"])
                    hits += 1
                else:
                    # force-fire once at start of career for coverage
                    pass
            if len(scores) < max(20, n_careers // 5):
                # dedicated micro-sims: start, fire event immediately
                for i in range(n_careers):
                    rng = random.Random(seed + 999 + i)
                    g = new_player()
                    opts = [o for o in (ev.get("options") or []) if o.get("label")]
                    out = sample_outcome(opts[ci], rng)
                    apply_fx(g, out.get("fx") or {})
                    g["usedEvents"].add(eid)

                    class Cont(Policy):
                        def choose(self, g2, ev2, rng2, _b=policy):
                            return _b.choose(g2, ev2, rng2)

                    # continue career
                    for age in range(g["age"], 38):
                        if g["careerEnded"]:
                            break
                        for _ in range(3):
                            if g["careerEnded"]:
                                break
                            ev2 = sample_event(g, data.events, rng)
                            if not ev2:
                                break
                            opts2 = [o for o in (ev2.get("options") or []) if o.get("label")]
                            cj = policy.choose(g, ev2, rng)
                            cj = max(0, min(cj, len(opts2) - 1))
                            apply_fx(g, (sample_outcome(opts2[cj], rng).get("fx") or {}))
                            if ev2.get("once"):
                                g["usedEvents"].add(ev2.get("id"))
                        season_tick(g, rng)
                    scores.append(career_score(g))
            means.append(float(np.mean(scores)))
        best_i = int(np.argmax(means))
        results[eid] = {
            "means": means,
            "best_i": best_i,
            "oracle_elite_i": data.best_by_id.get(eid),
            "flip": data.best_by_id.get(eid) is not None and data.best_by_id.get(eid) != best_i,
        }
    return results
