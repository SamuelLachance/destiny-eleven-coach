"""
Train a choice policy DIRECTLY on the real Engine.

Objective: maximize P90 of computeCareerScore over full careers.

Method:
  1. Start from pure-P90 Engine CF labels (local counterfactuals)
  2. CEM on the event→choice map, scored by full Engine careers (P90)
  3. Bake-off: random / CF-oracle / CEM-oracle / alwaysFirst
  4. Write scenarios.json for the live coach
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

SCENARIOS = Path("data/game_scenarios.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")
RAW_CF = Path("data/engine_top90_raw.json")
REPORT = Path("docs/engine_cem_report.json")
TREE = Path("docs/tree_model.json")

APPEND = r"""
;try{
  window.__D11 = {
    EVENTS, MICRO_EVENTS, ORIGINS, LIFESTYLES, POSITIONS, ENTOURAGES, NATIONALITIES,
    CLUBS: (typeof CLUBS !== 'undefined' ? CLUBS : null)
  };
}catch(e){ window.__D11Err = String(e); }
"""

BOOT_CORE = r"""
(() => {
  const pack = () => window.__D11;
  const Eng = () => Engine;

  function optionLabel(o) {
    let lab = String(o.label || o.text || '');
    if (o.hint) lab = o.hint + ': ' + lab;
    if (o.tag) lab = o.tag + ': ' + lab;
    return lab;
  }

  function setupBase() {
    const p = pack();
    return {
      name: 'CEM',
      nationality: p.NATIONALITIES.find(x => x.id === 'fr') || p.NATIONALITIES[0],
      origin: p.ORIGINS.find(x => x.id === 'quartier') || p.ORIGINS[0],
      position: p.POSITIONS.find(x => x.id === 'att') || p.POSITIONS[0],
      lifestyle: p.LIFESTYLES.find(x => x.id === 'pro') || p.LIFESTYLES[0],
      entourage: p.ENTOURAGES.find(x => /ambit/i.test((x.id||'')+(x.name||''))) || p.ENTOURAGES[0],
      club: p.CLUBS.find(c => c.id === 'fr_rennes') || p.CLUBS.find(c => c.level === 'd1') || p.CLUBS[0],
    };
  }

  function pickOi(ev, mode, oracle) {
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts.length) return 0;
    if (mode === 'random') return Math.floor(Eng().rand() * opts.length) % opts.length;
    if (mode === 'always0') return 0;
    if (mode === 'alwaysLast') return opts.length - 1;
    if ((mode === 'oracle' || mode === 'cem') && oracle && Object.prototype.hasOwnProperty.call(oracle, ev.id)) {
      const v = oracle[ev.id];
      if (typeof v === 'number' && isFinite(v)) return Math.max(0, Math.min(opts.length - 1, v|0));
    }
    // netImpact fallback
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

  function playCareer(seed, mode, oracle, maxAge) {
    const E = Eng();
    E.setSeed(seed >>> 0);
    const g = E.newCareer(setupBase());
    let nEv = 0;
    for (let y = 0; y < 40 && !g.careerEnded && !g.retiring && g.age < (maxAge || 34); y++) {
      try { E.playSeason(g); } catch (e) {}
      for (let k = 0; k < 2; k++) {
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try { ev = E.pickEvent(g); } catch (e) { break; }
        if (!ev) break;
        const opts = (ev.options || []).filter(o => o && (o.label || o.text));
        if (!opts.length) break;
        const oi = pickOi(ev, mode, oracle);
        try { E.resolveOption(g, opts[oi]); nEv++; } catch (e) {}
      }
      const a0 = g.age;
      try { E.advanceYear(g); } catch (e) {}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }
    return { score: E.computeCareerScore(g), nEv, age: g.age };
  }

  function batchCareers(seeds, mode, oracle, maxAge) {
    const scores = [];
    let nEv = 0;
    for (let i = 0; i < seeds.length; i++) {
      const r = playCareer(seeds[i], mode, oracle, maxAge);
      scores.push(r.score);
      nEv += r.nEv;
    }
    const arr = scores.slice().sort((a,b)=>a-b);
    const pct = (p) => arr[Math.min(arr.length-1, Math.floor((p/100)*(arr.length-1)))];
    const mean = scores.reduce((s,x)=>s+x,0) / (scores.length || 1);
    return {
      n: scores.length,
      mean,
      p50: pct(50),
      p90: pct(90),
      p95: pct(95),
      max: arr.length ? arr[arr.length-1] : 0,
      meanEvents: nEv / (scores.length || 1),
      head: scores.slice(0, 6),
    };
  }

  window.__D11CEM = { optionLabel, playCareer, batchCareers, setupBase };
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
            page.evaluate(BOOT_CORE)
            print("boot ok", page.evaluate("() => window.__D11.EVENTS.length"), flush=True)
            return
        page.wait_for_timeout(400)
    raise RuntimeError("boot failed")


def load_cf_policy() -> tuple[list[str], dict[str, int], dict[str, dict]]:
    """Return (event_ids, best_i map, meta by id) from pure-P90 CF raw or scenarios."""
    meta: dict[str, dict] = {}
    policy: dict[str, int] = {}
    if RAW_CF.exists():
        for r in json.loads(RAW_CF.read_text(encoding="utf-8")):
            eid = r["id"]
            policy[eid] = int(r["best_i"])
            meta[eid] = r
    elif SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            policy[s["id"]] = int(s["best_i"])
            meta[s["id"]] = s
    ids = list(policy.keys())
    return ids, policy, meta


def eval_policy(page, policy: dict[str, int], seeds: list[int], mode: str = "oracle") -> dict:
    page.set_default_timeout(0)
    return page.evaluate(
        """({ seeds, mode, oracle }) => window.__D11CEM.batchCareers(seeds, mode, oracle, 34)""",
        {"seeds": seeds, "mode": mode, "oracle": policy},
    )


def cem_optimize(page, event_ids: list[str], init: dict[str, int], meta: dict[str, dict]) -> tuple[dict[str, int], list[dict]]:
    """
    CEM over Bernoulli probs for each event's best choice (supports 2-way; multi-way via argmax soft).
    For simplicity: only 2-option events get CEM; multi-option keep CF best_i.
    """
    # Focus on binary events (majority)
    binary = []
    n_opts = {}
    for eid in event_ids:
        m = meta.get(eid) or {}
        labels = m.get("labels") or m.get("choices") or []
        n = len(labels) if labels else 2
        n_opts[eid] = n
        if n == 2:
            binary.append(eid)

    # Soft probs of choosing option 1 (init near CF)
    rng = np.random.default_rng(7)
    p = {}
    for eid in binary:
        bi = int(init.get(eid, 0))
        p[eid] = 0.82 if bi == 1 else 0.18

    history = []
    n_samples = 20
    n_elite = 5
    n_careers = 36
    n_iters = 8
    base_seed = 700_000

    print(
        f"CEM binary_events={len(binary)} samples={n_samples} elite={n_elite} "
        f"careers={n_careers} iters={n_iters}",
        flush=True,
    )

    best_policy = dict(init)
    best_p90 = -1.0

    for it in range(n_iters):
        samples = []
        for s in range(n_samples):
            pol = dict(init)
            for eid in binary:
                pol[eid] = 1 if rng.random() < p[eid] else 0
            seeds = [base_seed + it * 10_000 + s * 100 + k * 3 for k in range(n_careers)]
            st = eval_policy(page, pol, seeds, mode="oracle")
            samples.append({"policy": pol, "stats": st, "p90": float(st["p90"]), "mean": float(st["mean"])})

        samples.sort(key=lambda x: (x["p90"], x["mean"]), reverse=True)
        elite = samples[:n_elite]
        # update probs
        for eid in binary:
            avg = float(np.mean([e["policy"][eid] for e in elite]))
            p[eid] = 0.75 * avg + 0.25 * p[eid]
            p[eid] = float(np.clip(p[eid], 0.05, 0.95))

        top = elite[0]
        history.append(
            {
                "iter": it,
                "best_p90": top["p90"],
                "best_mean": top["mean"],
                "elite_p90": [e["p90"] for e in elite],
            }
        )
        print(
            f"  CEM iter {it+1}/{n_iters} best_p90={top['p90']:.1f} mean={top['mean']:.1f} "
            f"elite={[round(e['p90'],1) for e in elite]}",
            flush=True,
        )
        if top["p90"] > best_p90 or (top["p90"] == best_p90 and top["mean"] > best_policy.get("_mean", -1)):
            best_p90 = top["p90"]
            best_policy = dict(top["policy"])
            best_policy["_mean"] = top["mean"]

    best_policy.pop("_mean", None)
    # harden probs to MAP
    final = dict(init)
    for eid in binary:
        final[eid] = 1 if p[eid] >= 0.5 else 0
    # keep CEM best sample if better than MAP under fixed seeds
    seeds = [800_000 + k * 7 for k in range(60)]
    st_map = eval_policy(page, final, seeds)
    st_best = eval_policy(page, best_policy, seeds)
    print(f"  MAP p90={st_map['p90']:.1f} vs elite-sample p90={st_best['p90']:.1f}", flush=True)
    chosen = best_policy if st_best["p90"] >= st_map["p90"] else final
    return chosen, history


def write_scenarios(policy: dict[str, int], meta: dict[str, dict], label_goal: str):
    scenarios = []
    for eid, best_i in policy.items():
        m = meta.get(eid) or {}
        labels = m.get("labels") or m.get("choices")
        if not labels:
            continue
        best_i = int(best_i) % len(labels)
        objs = m.get("objs") or m.get("raw_scores")
        if not objs or len(objs) != len(labels):
            objs = [50.0] * len(labels)
            objs[best_i] = 100.0
        objs = [float(x) for x in objs]
        lo, hi = min(objs), max(objs)
        quals = []
        for v in objs:
            t = 0.5 if abs(hi - lo) < 1e-9 else (v - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 93.0)
        prompt = (
            str(m.get("text") or m.get("prompt") or "")
            .replace("{club}", "ton club")
            .replace("{Club}", "ton club")
            .replace("{name}", "toi")
        )
        scenarios.append(
            {
                "id": eid,
                "cat": m.get("cat"),
                "prompt": prompt,
                "choices": labels,
                "best_i": best_i,
                "raw_scores": objs,
                "qualities": quals,
                "label_goal": label_goal,
                "engine_margin": float(m.get("margin") or m.get("engine_margin") or 0),
                "engine_p90s": [float(v.get("p90", 0)) for v in m["vals"]] if isinstance(m.get("vals"), list) else None,
            }
        )

    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = [
        {k: s[k] for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities") if k in s}
        for s in scenarios
    ]
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return scenarios


def main():
    t0 = time.time()
    event_ids, cf_policy, meta = load_cf_policy()
    if not cf_policy:
        raise SystemExit("No CF policy found — run engine_top90_practice.py first")

    flips_init = 0
    print(f"loaded CF policy events={len(cf_policy)}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)

        seeds_ref = [100_000 + i * 13 for i in range(80)]
        print("=== BAKEOFF reference (80 Engine careers) ===", flush=True)
        before = {
            "random": eval_policy(page, cf_policy, seeds_ref, mode="random"),
            "always0": eval_policy(page, cf_policy, seeds_ref, mode="always0"),
            "alwaysLast": eval_policy(page, cf_policy, seeds_ref, mode="alwaysLast"),
            "cf_oracle": eval_policy(page, cf_policy, seeds_ref, mode="oracle"),
        }
        for k, v in before.items():
            print(
                f"  {k:12s} mean={v['mean']:.1f} p90={v['p90']:.1f} p95={v['p95']:.1f} "
                f"ev/career={v['meanEvents']:.1f} head={v['head']}",
                flush=True,
            )

        cem_policy, history = cem_optimize(page, event_ids, cf_policy, meta)

        seeds_final = [200_000 + i * 17 for i in range(100)]
        print("=== BAKEOFF after CEM (100 careers, fixed seeds) ===", flush=True)
        after = {
            "random": eval_policy(page, cem_policy, seeds_final, mode="random"),
            "always0": eval_policy(page, cem_policy, seeds_final, mode="always0"),
            "cf_oracle": eval_policy(page, cf_policy, seeds_final, mode="oracle"),
            "cem_oracle": eval_policy(page, cem_policy, seeds_final, mode="oracle"),
        }
        for k, v in after.items():
            print(
                f"  {k:12s} mean={v['mean']:.1f} p90={v['p90']:.1f} p95={v['p95']:.1f} head={v['head']}",
                flush=True,
            )
        browser.close()

    n_flip = sum(1 for k, v in cem_policy.items() if cf_policy.get(k) != v)
    scenarios = write_scenarios(cem_policy, meta, label_goal="engine_cem_career_p90")
    if TREE.exists():
        model = json.loads(TREE.read_text(encoding="utf-8"))
        model["label_goal"] = "engine_cem_career_p90"
        model["note"] = (
            "Policy trained DIRECTLY on real Engine full careers; objective = P90 "
            "of computeCareerScore (top ~10% runs). CEM refined pure-P90 CF labels."
        )
        TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")

    report = {
        "source": "real_Engine_CEM_career_P90",
        "objective": "maximize_P90_computeCareerScore_full_careers",
        "n_events": len(scenarios),
        "n_flips_vs_cf": n_flip,
        "bakeoff_before": before,
        "bakeoff_after": after,
        "cem_history": history,
        "elapsed_sec": round(time.time() - t0, 1),
        "gain_p90_vs_random": float(after["cem_oracle"]["p90"] - after["random"]["p90"]),
        "gain_p90_vs_cf": float(after["cem_oracle"]["p90"] - after["cf_oracle"]["p90"]),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE flips_vs_cf={n_flip} cem_p90={after['cem_oracle']['p90']:.1f} "
        f"random_p90={after['random']['p90']:.1f} always0_p90={after['always0']['p90']:.1f} "
        f"elapsed={report['elapsed_sec']}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
