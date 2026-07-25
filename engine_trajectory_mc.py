"""
Train on the CAREER COMBINATORIAL space (≈ 2^100 paths), not single-event CF.

Exact enumeration is impossible. We Monte-Carlo sample full Engine careers,
credit every (event_id, choice_i) with the final computeCareerScore, then:
  - label each event by P90 of scores when that choice was taken
  - CEM-refine the policy for max career P90
  - blend with elite labels where coverage is too thin

This is the correct attack on "train on all career combinations".
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

SCENARIOS = Path("data/game_scenarios.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")
ELITE_SCEN = Path("docs/scenarios_elite_backup.json")
REPORT = Path("docs/trajectory_mc_report.json")
RAW = Path("data/trajectory_mc_raw.json")
TREE = Path("docs/tree_model.json")
TREE_REPORT = Path("docs/tree_train_report.json")

APPEND = r"""
;try{
  window.__D11 = {
    EVENTS, MICRO_EVENTS, ORIGINS, LIFESTYLES, POSITIONS, ENTOURAGES, NATIONALITIES,
    CLUBS: (typeof CLUBS !== 'undefined' ? CLUBS : null)
  };
}catch(e){ window.__D11Err = String(e); }
"""

CORE = r"""
(() => {
  const pack = () => window.__D11;
  const Eng = () => Engine;

  function setupBase() {
    const p = pack();
    return {
      name: 'TrajMC',
      nationality: p.NATIONALITIES.find(x => x.id === 'fr') || p.NATIONALITIES[0],
      origin: p.ORIGINS.find(x => x.id === 'quartier') || p.ORIGINS[0],
      position: p.POSITIONS.find(x => x.id === 'att') || p.POSITIONS[0],
      lifestyle: p.LIFESTYLES.find(x => x.id === 'pro') || p.LIFESTYLES[0],
      entourage: p.ENTOURAGES.find(x => /ambit/i.test((x.id||'')+(x.name||''))) || p.ENTOURAGES[0],
      club: p.CLUBS.find(c => c.id === 'fr_rennes') || p.CLUBS.find(c => c.level === 'd1') || p.CLUBS[0],
    };
  }

  function optionLabel(o) {
    let lab = String(o.label || o.text || '');
    if (o.hint) lab = o.hint + ': ' + lab;
    if (o.tag) lab = o.tag + ': ' + lab;
    return lab;
  }

  function nOpts(ev) {
    return (ev.options || []).filter(o => o && (o.label || o.text)).length;
  }

  /** Mulberry32 — separate from Engine RNG so exploration does not starve pickEvent. */
  function makePrng(seed) {
    let a = (seed >>> 0) || 1;
    return function() {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  function pickOi(ev, mode, oracle, eps, rnd) {
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts.length) return 0;
    const roll = rnd || Math.random;
    if (mode === 'random' || (eps && roll() < eps)) {
      return Math.floor(roll() * opts.length) % opts.length;
    }
    if (mode === 'oracle' && oracle && Object.prototype.hasOwnProperty.call(oracle, ev.id)) {
      const v = oracle[ev.id]|0;
      return Math.max(0, Math.min(opts.length - 1, v));
    }
    if (mode === 'always0') return 0;
    // netImpact — does not consume Engine.rand
    const E = Eng();
    let best = 0, bestS = -1e99;
    for (let i = 0; i < opts.length; i++) {
      const outs = opts[i].outcomes || [];
      let tw = 0, s = 0;
      for (const oc of outs) {
        const w = oc.weight || 1; tw += w;
        try { s += w * E.netImpact(oc.fx || {}); } catch (e) {}
      }
      const evs = tw ? s / tw : 0;
      if (evs > bestS) { bestS = evs; best = i; }
    }
    return best;
  }

  /** One full career; returns final score + list of decisions taken. */
  function playCareerLogged(seed, mode, oracle, eps, maxAge) {
    const E = Eng();
    E.setSeed(seed >>> 0);
    const rnd = makePrng((seed * 2654435761) >>> 0);
    const g = E.newCareer(setupBase());
    const decisions = [];
    for (let y = 0; y < 40 && !g.careerEnded && !g.retiring && g.age < (maxAge || 34); y++) {
      try { E.playSeason(g); } catch (e) {}
      for (let k = 0; k < 2; k++) {
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try { ev = E.pickEvent(g); } catch (e) { break; }
        if (!ev || !ev.id) break;
        const opts = (ev.options || []).filter(o => o && (o.label || o.text));
        if (opts.length < 2) break;
        const oi = pickOi(ev, mode, oracle, eps, rnd);
        try {
          E.resolveOption(g, opts[oi]);
          decisions.push({ id: ev.id, oi, n: opts.length, age: g.age });
        } catch (e) {}
      }
      const a0 = g.age;
      try { E.advanceYear(g); } catch (e) {}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }
    return { score: E.computeCareerScore(g), decisions, age: g.age };
  }

  function batchLogged(seeds, mode, oracle, eps, maxAge) {
    const out = [];
    for (let i = 0; i < seeds.length; i++) {
      out.push(playCareerLogged(seeds[i], mode, oracle, eps, maxAge));
    }
    return out;
  }

  function batchScores(seeds, mode, oracle, maxAge) {
    const scores = [];
    let nEv = 0;
    for (let i = 0; i < seeds.length; i++) {
      const r = playCareerLogged(seeds[i], mode, oracle, 0, maxAge);
      scores.push(r.score);
      nEv += r.decisions.length;
    }
    const arr = scores.slice().sort((a,b)=>a-b);
    const pct = (p) => arr[Math.min(arr.length-1, Math.floor((p/100)*(arr.length-1)))];
    const mean = scores.reduce((s,x)=>s+x,0)/(scores.length||1);
    return {
      n: scores.length, mean, p50: pct(50), p90: pct(90), p95: pct(95),
      max: arr.length ? arr[arr.length-1] : 0,
      meanEvents: nEv/(scores.length||1),
      head: scores.slice(0, 5),
    };
  }

  function eventCatalog() {
    return pack().EVENTS.filter(e => nOpts(e) >= 2).map(e => ({
      id: e.id,
      cat: e.cat || null,
      text: String(e.text || ''),
      labels: (e.options || []).filter(o => o && (o.label || o.text)).map(optionLabel),
    }));
  }

  window.__D11Traj = { batchLogged, batchScores, eventCatalog, playCareerLogged };
})();
"""


def boot(page):
    def handle_route(route):
        if "data.js" in route.request.url:
            resp = route.fetch()
            route.fulfill(
                status=resp.status,
                headers={**resp.headers, "content-type": "application/javascript"},
                body=resp.text() + APPEND,
            )
        else:
            route.continue_()

    page.route("**/*", handle_route)
    page.goto("https://destinyeleven.com/", wait_until="domcontentloaded", timeout=180000)
    for _ in range(60):
        if page.evaluate(
            "() => !!(window.__D11 && window.__D11.CLUBS && window.__D11.CLUBS.length && typeof Engine!=='undefined')"
        ):
            page.evaluate(CORE)
            print("boot", page.evaluate("() => window.__D11.EVENTS.length"), flush=True)
            return
        page.wait_for_timeout(400)
    raise RuntimeError("boot failed")


def load_elite() -> dict[str, dict]:
    """Prefer committed elite scenarios."""
    path = DOCS_SCEN if DOCS_SCEN.exists() else None
    # try git elite backup if present
    rows = []
    if ELITE_SCEN.exists():
        rows = json.loads(ELITE_SCEN.read_text(encoding="utf-8"))
    elif path:
        rows = json.loads(path.read_text(encoding="utf-8"))
    return {r["id"]: r for r in rows}


def p90(arr: list[float]) -> float:
    if not arr:
        return 0.0
    a = sorted(arr)
    return float(a[min(len(a) - 1, int(0.90 * (len(a) - 1)))])


def aggregate_labels(
    catalog: list[dict],
    credit: dict[str, dict[int, list[float]]],
    elite: dict[str, dict],
    min_n: int = 25,
    margin: float = 3.0,
) -> tuple[dict[str, int], list[dict], dict]:
    """
    For each event: best choice = argmax P90(final scores | choice).
    If under-sampled, keep elite label.
    """
    policy: dict[str, int] = {}
    scenarios: list[dict] = []
    stats = {"traj_labeled": 0, "elite_kept": 0, "flips_vs_elite": 0}

    for ev in catalog:
        eid = ev["id"]
        labels = ev["labels"]
        n = len(labels)
        by = credit.get(eid, {})
        objs = []
        counts = []
        for i in range(n):
            scores = by.get(i, [])
            counts.append(len(scores))
            objs.append(p90(scores) if len(scores) >= max(8, min_n // 3) else None)

        covered = all(c >= min_n for c in counts) and all(o is not None for o in objs)
        elite_row = elite.get(eid)
        elite_i = int(elite_row["best_i"]) if elite_row and elite_row.get("best_i") is not None else 0
        elite_i = elite_i % n

        if covered:
            # fill None shouldn't happen
            objs_f = [float(o) for o in objs]
            best_i = int(np.argmax(objs_f))
            sorted_o = sorted(objs_f, reverse=True)
            marg = sorted_o[0] - sorted_o[1] if len(sorted_o) > 1 else 99.0
            if marg < margin:
                # weak signal → keep elite
                best_i = elite_i
                goal = "traj_mc_p90_weak_keep_elite"
                stats["elite_kept"] += 1
            else:
                goal = "traj_mc_p90"
                stats["traj_labeled"] += 1
                if best_i != elite_i:
                    stats["flips_vs_elite"] += 1
            raw = objs_f
        else:
            best_i = elite_i
            goal = "elite_undersampled"
            stats["elite_kept"] += 1
            if elite_row and elite_row.get("raw_scores"):
                raw = [float(x) for x in elite_row["raw_scores"]]
                if len(raw) != n:
                    raw = [50.0] * n
                    raw[best_i] = 100.0
            else:
                raw = [50.0] * n
                raw[best_i] = 100.0

        lo, hi = min(raw), max(raw)
        quals = []
        for v in raw:
            t = 0.5 if abs(hi - lo) < 1e-9 else (v - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 93.0)

        prompt = (
            (ev.get("text") or (elite_row or {}).get("prompt") or "")
            .replace("{club}", "ton club")
            .replace("{Club}", "ton club")
            .replace("{name}", "toi")
        )
        if not prompt and elite_row:
            prompt = elite_row.get("prompt") or ""

        policy[eid] = best_i
        scenarios.append(
            {
                "id": eid,
                "cat": ev.get("cat") or (elite_row or {}).get("cat"),
                "prompt": prompt,
                "choices": labels if labels else (elite_row or {}).get("choices") or [],
                "best_i": best_i,
                "raw_scores": raw,
                "qualities": quals,
                "label_goal": goal,
                "traj_counts": counts if covered or eid in credit else [0] * n,
                "traj_p90s": [float(o) if o is not None else None for o in (objs if covered else [None] * n)],
            }
        )

    return policy, scenarios, stats


def write_scenarios(scenarios: list[dict]):
    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = [
        {k: s[k] for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities") if k in s}
        for s in scenarios
    ]
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def cem_refine(page, init: dict[str, int], catalog: list[dict], n_iters=6, n_samples=16, n_careers=40):
    binary = [e["id"] for e in catalog if len(e["labels"]) == 2]
    rng = np.random.default_rng(11)
    p = {eid: (0.8 if init.get(eid, 0) == 1 else 0.2) for eid in binary}
    history = []
    best_pol = dict(init)
    best_p90 = -1.0

    print(f"CEM refine binary={len(binary)} iters={n_iters} samples={n_samples} careers={n_careers}", flush=True)
    for it in range(n_iters):
        scored = []
        for s in range(n_samples):
            pol = dict(init)
            for eid in binary:
                pol[eid] = 1 if rng.random() < p[eid] else 0
            seeds = [900_000 + it * 50_000 + s * 200 + k * 5 for k in range(n_careers)]
            st = page.evaluate(
                """({seeds, oracle}) => window.__D11Traj.batchScores(seeds, 'oracle', oracle, 34)""",
                {"seeds": seeds, "oracle": pol},
            )
            scored.append({"pol": pol, "p90": float(st["p90"]), "mean": float(st["mean"])})
        scored.sort(key=lambda x: (x["p90"], x["mean"]), reverse=True)
        elite = scored[:5]
        for eid in binary:
            avg = float(np.mean([e["pol"][eid] for e in elite]))
            p[eid] = float(np.clip(0.7 * avg + 0.3 * p[eid], 0.05, 0.95))
        top = elite[0]
        history.append({"iter": it, "best_p90": top["p90"], "elite": [e["p90"] for e in elite]})
        print(f"  CEM {it+1}/{n_iters} p90={top['p90']:.1f} elite={[round(e['p90'],1) for e in elite]}", flush=True)
        if top["p90"] > best_p90:
            best_p90 = top["p90"]
            best_pol = dict(top["pol"])
    return best_pol, history


def main():
    t0 = time.time()
    # Coverage of combinatorial space: many careers × ~35 decisions ≈ path samples
    n_careers = 4000
    batch = 200
    eps_schedule = [
        ("random", 1.0, n_careers // 2),
        ("oracle", 0.35, n_careers // 4),  # explore around elite
        ("netImpact", 0.25, n_careers // 4),
    ]

    # backup elite before overwrite
    if DOCS_SCEN.exists() and not ELITE_SCEN.exists():
        ELITE_SCEN.write_text(DOCS_SCEN.read_text(encoding="utf-8"), encoding="utf-8")

    elite = load_elite()
    elite_oracle = {k: int(v["best_i"]) for k, v in elite.items()}

    credit: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    all_raw = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        page.set_default_timeout(0)
        catalog = page.evaluate("() => window.__D11Traj.eventCatalog()")
        print(f"catalog_events={len(catalog)} elite={len(elite)}", flush=True)

        seeds_ref = [50_000 + i * 11 for i in range(80)]
        before = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Traj.batchScores(seeds, 'random', {}, 34)""",
                {"seeds": seeds_ref},
            ),
            "elite": page.evaluate(
                """({seeds, oracle}) => window.__D11Traj.batchScores(seeds, 'oracle', oracle, 34)""",
                {"seeds": seeds_ref, "oracle": elite_oracle},
            ),
        }
        for k, v in before.items():
            print(f"before {k:8s} mean={v['mean']:.1f} p90={v['p90']:.1f} ev={v['meanEvents']:.1f}", flush=True)

        seed0 = 1_000_000
        done = 0
        for mode, eps, n_mode in eps_schedule:
            print(f"=== sample mode={mode} eps={eps} n={n_mode} ===", flush=True)
            left = n_mode
            while left > 0:
                take = min(batch, left)
                seeds = [seed0 + done + i for i in range(take)]
                oracle = elite_oracle if mode in ("oracle", "netImpact") else {}
                # netImpact encoded as mode without oracle
                js_mode = "oracle" if mode == "oracle" else ("random" if mode == "random" else "netImpact")
                if mode == "netImpact":
                    js_mode = "netImpact"
                    oracle = {}
                part = page.evaluate(
                    """({seeds, mode, oracle, eps}) => window.__D11Traj.batchLogged(seeds, mode, oracle, eps, 34)""",
                    {"seeds": seeds, "mode": js_mode, "oracle": oracle, "eps": float(eps) if mode != "random" else 1.0},
                )
                for career in part:
                    sc = float(career["score"])
                    all_raw.append({"score": sc, "n": len(career["decisions"]), "mode": mode})
                    for d in career["decisions"]:
                        credit[d["id"]][int(d["oi"])].append(sc)
                done += take
                left -= take
                if done % 400 == 0 or left == 0:
                    n_ev = len(credit)
                    n_pairs = sum(len(v) for v in credit.values())
                    print(f"  careers={done}/{n_careers} events_seen={n_ev} pairs={n_pairs}", flush=True)

        # persist raw credit counts (compact)
        compact = {
            eid: {str(i): {"n": len(scores), "p90": p90(scores), "mean": float(np.mean(scores))} for i, scores in ch.items()}
            for eid, ch in credit.items()
        }
        RAW.write_text(json.dumps({"n_careers": done, "credit": compact}, ensure_ascii=False), encoding="utf-8")

        policy, scenarios, stats = aggregate_labels(catalog, credit, elite, min_n=30, margin=2.5)
        print(f"aggregate {stats}", flush=True)

        # CEM on top of traj labels
        cem_pol, cem_hist = cem_refine(page, policy, catalog)
        # apply CEM flips onto scenarios
        by_id = {s["id"]: s for s in scenarios}
        n_cem_flip = 0
        for eid, bi in cem_pol.items():
            if eid in by_id and by_id[eid]["best_i"] != bi:
                by_id[eid]["best_i"] = int(bi)
                by_id[eid]["label_goal"] = "traj_mc_p90_cem"
                n_cem_flip += 1
        scenarios = list(by_id.values())
        write_scenarios(scenarios)

        seeds_final = [200_000 + i * 13 for i in range(120)]
        after = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Traj.batchScores(seeds, 'random', {}, 34)""",
                {"seeds": seeds_final},
            ),
            "elite": page.evaluate(
                """({seeds, oracle}) => window.__D11Traj.batchScores(seeds, 'oracle', oracle, 34)""",
                {"seeds": seeds_final, "oracle": elite_oracle},
            ),
            "traj": page.evaluate(
                """({seeds, oracle}) => window.__D11Traj.batchScores(seeds, 'oracle', oracle, 34)""",
                {"seeds": seeds_final, "oracle": policy},
            ),
            "traj_cem": page.evaluate(
                """({seeds, oracle}) => window.__D11Traj.batchScores(seeds, 'oracle', oracle, 34)""",
                {"seeds": seeds_final, "oracle": cem_pol},
            ),
        }
        for k, v in after.items():
            print(f"after  {k:8s} mean={v['mean']:.1f} p90={v['p90']:.1f}", flush=True)

        # Ship policy with best Engine P90 among elite / traj / cem
        candidates = [
            ("elite", elite_oracle, after["elite"]["p90"]),
            ("traj", policy, after["traj"]["p90"]),
            ("traj_cem", cem_pol, after["traj_cem"]["p90"]),
        ]
        best_name, best_pol, best_p90 = max(candidates, key=lambda x: x[2])
        print(f"SHIP_POLICY={best_name} p90={best_p90}", flush=True)

        # rewrite scenarios to best policy choices
        for s in scenarios:
            if s["id"] in best_pol:
                s["best_i"] = int(best_pol[s["id"]]) % len(s["choices"])
                s["label_goal"] = f"ship_{best_name}_career_p90"
        write_scenarios(scenarios)
        browser.close()

    # update tree note (keep retrieval type; oracle is scenarios)
    if TREE.exists():
        model = json.loads(TREE.read_text(encoding="utf-8"))
        model["label_goal"] = f"trajectory_mc_{best_name}"
        model["note"] = (
            f"Trained on Engine Monte Carlo over career path space (~2^100), not single-event CF. "
            f"Sampled {n_careers} full careers; shipped policy={best_name} (Engine P90={best_p90}). "
            f"Exact 2^100 enumeration impossible — MC covers the distribution."
        )
        model["engine_career_p90"] = {k: v["p90"] for k, v in after.items()}
        TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        TREE_REPORT.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "space": "career_paths_approx_2^100",
        "exact_enumeration": False,
        "n_careers_sampled": done,
        "approx_decision_points": done * float(np.mean([r["n"] for r in all_raw])) if all_raw else 0,
        "aggregate_stats": stats,
        "cem_flips": n_cem_flip,
        "cem_history": cem_hist,
        "bakeoff_before": before,
        "bakeoff_after": after,
        "shipped_policy": best_name,
        "shipped_p90": best_p90,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE ship={best_name} p90={best_p90} careers={done} "
        f"decision_credits~{report['approx_decision_points']:.0f} elapsed={report['elapsed_sec']}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
