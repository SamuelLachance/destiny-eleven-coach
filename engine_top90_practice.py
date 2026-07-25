"""
Practice / optimize a choice policy DIRECTLY on the real Destiny Eleven Engine.

Objective: maximize P90 of computeCareerScore across full careers (top ~10% runs).

Steps in one Playwright session:
  1) Bake-off policies (random / netImpact / current oracle) → mean & P90
  2) Relabel every event with PURE P90 Engine CF (obj = p90 only)
     Continuation uses the oracle map (self-consistent top-run policy)
  3) Bake-off again with the new oracle
  4) Write scenarios + report for Pages
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SCENARIOS = Path("data/game_scenarios.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")
REPORT = Path("docs/engine_top90_report.json")
RAW = Path("data/engine_top90_raw.json")
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

# Shared Engine helpers injected once, then called with different modes.
CORE_JS = r"""
(() => {
  if (window.__D11Core) return;
  const pack = () => window.__D11;
  const E = () => Engine;

  function optionLabel(o) {
    let lab = String(o.label || o.text || '');
    if (o.hint) lab = o.hint + ': ' + lab;
    if (o.tag) lab = o.tag + ': ' + lab;
    return lab;
  }

  function setupBase() {
    const p = pack();
    return {
      name: 'Top90',
      nationality: p.NATIONALITIES.find(x => x.id === 'fr') || p.NATIONALITIES[0],
      origin: p.ORIGINS.find(x => x.id === 'quartier') || p.ORIGINS[0],
      position: p.POSITIONS.find(x => x.id === 'att') || p.POSITIONS[0],
      lifestyle: p.LIFESTYLES.find(x => x.id === 'pro') || p.LIFESTYLES[0],
      entourage: p.ENTOURAGES.find(x => /ambit/i.test((x.id||'')+(x.name||''))) || p.ENTOURAGES[0],
      club: p.CLUBS.find(c => c.id === 'fr_rennes') || p.CLUBS.find(c => c.level === 'd1') || p.CLUBS[0],
    };
  }

  function netImpactBest(ev) {
    const Eng = E();
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    let best = 0, bestS = -1e99;
    for (let i = 0; i < opts.length; i++) {
      const outs = opts[i].outcomes || [];
      let tw = 0, s = 0;
      for (const oc of outs) {
        const w = oc.weight || 1; tw += w;
        try { s += w * Eng.netImpact(oc.fx || {}); } catch (e) {}
      }
      const evs = tw ? s / tw : 0;
      if (evs > bestS) { bestS = evs; best = i; }
    }
    return best;
  }

  function pickIndex(ev, mode, oracle) {
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts.length) return 0;
    if (mode === 'random') return Math.floor(E().rand() * opts.length);
    if (mode === 'oracle' && oracle && oracle[ev.id] != null) {
      return Math.min(oracle[ev.id], opts.length - 1);
    }
    return netImpactBest(ev);
  }

  function playCareer(seed, mode, oracle, maxAge) {
    const Eng = E();
    Eng.setSeed(seed);
    const g = Eng.newCareer(setupBase());
    let guard = 0;
    while (!g.careerEnded && !g.retiring && g.age < (maxAge || 34) && guard < 40) {
      guard++;
      try { Eng.playSeason(g); } catch (e) {}
      const nEv = 1 + Math.floor(Eng.rand() * 2);
      for (let k = 0; k < nEv; k++) {
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try { ev = Eng.pickEvent(g); } catch (e) { break; }
        if (!ev || !ev.options || !ev.options.length) break;
        const opts = ev.options.filter(o => o && (o.label || o.text));
        if (!opts.length) break;
        const oi = pickIndex(ev, mode, oracle);
        try { Eng.resolveOption(g, opts[Math.min(oi, opts.length - 1)]); } catch (e) {}
      }
      const a0 = g.age;
      try { Eng.advanceYear(g); } catch (e) {}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }
    return Eng.computeCareerScore(g);
  }

  function pct(arr, p) {
    arr = arr.slice().sort((a,b)=>a-b);
    if (!arr.length) return 0;
    return arr[Math.min(arr.length - 1, Math.floor((p / 100) * (arr.length - 1)))];
  }

  function stats(arr) {
    arr = arr.filter(x => typeof x === 'number' && isFinite(x));
    if (!arr.length) return { n: 0, mean: 0, p50: 0, p90: 0, p95: 0, max: 0 };
    const mean = arr.reduce((s, x) => s + x, 0) / arr.length;
    return {
      n: arr.length,
      mean,
      p50: pct(arr, 50),
      p90: pct(arr, 90),
      p95: pct(arr, 95),
      max: Math.max(...arr),
    };
  }

  function ageToCond(g, ev) {
    const Eng = E();
    const cond = ev.cond || {};
    const aMin = cond.aMin != null ? cond.aMin : 16;
    const aMax = cond.aMax != null ? cond.aMax : Math.min(32, aMin + 3);
    const targetAge = aMin + Math.floor((Math.max(0, aMax - aMin)) * 0.4);
    let guard = 0;
    while (g.age < targetAge && !g.careerEnded && !g.retiring && guard < 25) {
      try { Eng.playSeason(g); } catch (e) {}
      const a0 = g.age;
      try { Eng.advanceYear(g); } catch (e) {}
      if (g.age === a0) g.age = a0 + 1;
      if (cond.minRep != null && g.rep < cond.minRep) g.rep = cond.minRep + 1;
      guard++;
    }
    if (cond.minRep != null && g.rep < cond.minRep) g.rep = Number(cond.minRep) + 2;
    if (cond.minOvr != null) {
      let g2 = 0;
      while (Eng.ovr(g) < cond.minOvr && g2 < 40) {
        g.stats.t += 1; g.stats.p += 1; g.stats.m += 1; g.stats.c += 1;
        g2++;
      }
    }
  }

  function continueCareer(g, seed, seasons, oracle) {
    const Eng = E();
    Eng.setSeed(seed);
    for (let s = 0; s < seasons; s++) {
      if (g.careerEnded || g.retiring) break;
      try { Eng.playSeason(g); } catch (e) {}
      const nEv = 1 + Math.floor(Eng.rand() * 2);
      for (let k = 0; k < nEv; k++) {
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try { ev = Eng.pickEvent(g); } catch (e) { break; }
        if (!ev || !ev.options || !ev.options.length) break;
        const opts = ev.options.filter(o => o && (o.label || o.text));
        if (!opts.length) break;
        const oi = pickIndex(ev, 'oracle', oracle);
        try { Eng.resolveOption(g, opts[Math.min(oi, opts.length - 1)]); } catch (e) {}
      }
      const a0 = g.age;
      try { Eng.advanceYear(g); } catch (e) {}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }
    return Eng.computeCareerScore(g);
  }

  function forceChoice(ev, choiceI, rollSeed, maxSeasons, oracle) {
    const Eng = E();
    Eng.setSeed(rollSeed);
    const g = Eng.newCareer(setupBase());
    ageToCond(g, ev);
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts[choiceI]) return null;
    try { Eng.resolveOption(g, opts[choiceI]); }
    catch (e) {
      const outs = opts[choiceI].outcomes || [];
      let tw = outs.reduce((s, o) => s + (o.weight || 1), 0) || 1;
      let r = Eng.rand() * tw, acc = 0, picked = outs[0];
      for (const o of outs) { acc += (o.weight || 1); if (r <= acc) { picked = o; break; } }
      if (picked && picked.fx) Eng.applyFx(g, picked.fx);
    }
    if (g.careerEnded || g.retiring) return Eng.computeCareerScore(g);
    return continueCareer(g, rollSeed + 91, maxSeasons, oracle);
  }

  window.__D11Core = {
    optionLabel,
    playCareer,
    stats,
    forceChoice,
    pct,
  };
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
        ok = page.evaluate(
            "() => !!(window.__D11 && window.__D11.CLUBS && window.__D11.CLUBS.length && typeof Engine!=='undefined')"
        )
        if ok:
            page.evaluate(CORE_JS)
            n = page.evaluate("() => ({e:window.__D11.EVENTS.length,c:window.__D11.CLUBS.length})")
            print("boot", n, flush=True)
            return
        page.wait_for_timeout(400)
    raise RuntimeError("Engine boot failed")


def load_oracle() -> dict[str, int]:
    oracle: dict[str, int] = {}
    if SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            if s.get("id") is not None and s.get("best_i") is not None:
                oracle[str(s["id"])] = int(s["best_i"])
    elif DOCS_SCEN.exists():
        for s in json.loads(DOCS_SCEN.read_text(encoding="utf-8")):
            oracle[str(s["id"])] = int(s["best_i"])
    return oracle


def bakeoff(page, oracle: dict[str, int], n_careers: int = 80, max_age: int = 34) -> dict:
    return page.evaluate(
        """({ oracle, nCareers, maxAge }) => {
          const C = window.__D11Core;
          const modes = ['random', 'netImpact', 'oracle'];
          const out = {};
          for (const mode of modes) {
            const scores = [];
            for (let i = 0; i < nCareers; i++) {
              scores.push(C.playCareer(900000 + i * 17 + mode.length * 101, mode, oracle, maxAge));
            }
            out[mode] = C.stats(scores);
          }
          return out;
        }""",
        {"oracle": oracle, "nCareers": n_careers, "maxAge": max_age},
    )


def relabel_pure_p90(page, oracle: dict[str, int], n_roll: int = 40, max_seasons: int = 14) -> list[dict]:
    event_ids = page.evaluate(
        """() => window.__D11.EVENTS
          .filter(e => ((e.options||[]).filter(o=>o&&(o.label||o.text))).length>=2)
          .map(e => e.id)"""
    )
    batch_size = 10
    all_results: list[dict] = []
    print(f"relabel PURE P90 events={len(event_ids)} rolls={n_roll} seasons={max_seasons}", flush=True)
    for i in range(0, len(event_ids), batch_size):
        chunk = event_ids[i : i + batch_size]
        print(f"  batch {i//batch_size+1}/{(len(event_ids)+batch_size-1)//batch_size} {chunk[0]}..", flush=True)
        page.set_default_timeout(0)
        part = page.evaluate(
            """({ eventIds, nRoll, maxSeasons, oracle }) => {
              const C = window.__D11Core;
              const byId = {};
              for (const ev of window.__D11.EVENTS) byId[ev.id] = ev;
              const out = [];
              for (let ei = 0; ei < eventIds.length; ei++) {
                const ev = byId[eventIds[ei]];
                if (!ev) continue;
                const opts = (ev.options || []).filter(o => o && (o.label || o.text));
                if (opts.length < 2) continue;
                const vals = [];
                for (let ci = 0; ci < opts.length; ci++) {
                  const scores = [];
                  for (let r = 0; r < nRoll; r++) {
                    const sc = C.forceChoice(
                      ev, ci,
                      300000 + ei * 1009 + ci * 307 + r * 13,
                      maxSeasons, oracle
                    );
                    if (typeof sc === 'number' && isFinite(sc)) scores.push(sc);
                  }
                  // PURE TOP-90%: objective = p90 only
                  const st = C.stats(scores);
                  vals.push({ ...st, obj: st.p90 });
                }
                const objs = vals.map(v => v.obj);
                let bestI = 0;
                for (let j = 1; j < objs.length; j++) if (objs[j] > objs[bestI]) bestI = j;
                const sorted = objs.slice().sort((a,b)=>b-a);
                const marg = sorted.length > 1 ? sorted[0] - sorted[1] : 99;
                out.push({
                  id: ev.id,
                  cat: ev.cat || null,
                  text: String(ev.text || ''),
                  labels: opts.map(C.optionLabel),
                  vals, objs, best_i: bestI, margin: marg
                });
              }
              return out;
            }""",
            {
                "eventIds": chunk,
                "nRoll": n_roll,
                "maxSeasons": max_seasons,
                "oracle": oracle,
            },
        )
        all_results.extend(part)
        RAW.write_text(json.dumps(all_results, ensure_ascii=False), encoding="utf-8")
    return all_results


def write_scenarios(results: list[dict], margin: float, old_oracle: dict[str, int]):
    scenarios, flips = [], []
    for r in results:
        labels = r["labels"]
        objs = [float(x) for x in r["objs"]]
        strong = float(r["margin"]) >= margin
        if strong:
            best_i = int(r["best_i"])
            goal = "engine_pure_p90"
        else:
            best_i = old_oracle.get(r["id"], int(r["best_i"]))
            if best_i >= len(labels):
                best_i = int(r["best_i"])
            goal = "engine_pure_p90_tie_keep"
        lo, hi = min(objs), max(objs)
        quals = []
        for v in objs:
            t = 0.5 if abs(hi - lo) < 1e-9 else (v - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 93.0)
        prompt = (
            (r.get("text") or "")
            .replace("{club}", "ton club")
            .replace("{Club}", "ton club")
            .replace("{name}", "toi")
        )
        scenarios.append(
            {
                "id": r["id"],
                "cat": r.get("cat"),
                "prompt": prompt,
                "choices": labels,
                "best_i": best_i,
                "raw_scores": objs,
                "qualities": quals,
                "label_goal": goal,
                "engine_margin": float(r["margin"]),
                "engine_means": [float(v.get("mean", 0)) for v in r["vals"]],
                "engine_p90s": [float(v.get("p90", 0)) for v in r["vals"]],
            }
        )
        old_i = old_oracle.get(r["id"])
        if strong and old_i is not None and old_i != best_i:
            flips.append(
                {
                    "id": r["id"],
                    "old": labels[old_i] if old_i < len(labels) else "?",
                    "new": labels[best_i],
                    "margin": float(r["margin"]),
                    "objs": [round(x, 2) for x in objs],
                }
            )

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


def refresh_retrieval_note(cv: float | None = None):
    if not TREE.exists():
        return
    model = json.loads(TREE.read_text(encoding="utf-8"))
    model["label_goal"] = "engine_pure_p90_careers"
    model["note"] = (
        "Labels from REAL Engine full-career CF with PURE P90 objective "
        "(top ~10% runs). Continuation uses oracle policy on Engine."
    )
    if cv is not None:
        model["cv_top1_holdout"] = float(cv)
    TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")


def main():
    t0 = time.time()
    n_roll = 40
    max_seasons = 14
    margin = 2.0  # slightly softer: P90 is noisier
    n_careers = 100

    old_oracle = load_oracle()
    print(f"oracle_size={len(old_oracle)}", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)

        print("=== BAKEOFF before (Engine careers, obj=P90) ===", flush=True)
        before = bakeoff(page, old_oracle, n_careers=n_careers)
        for k, v in before.items():
            print(
                f"  {k:10s} mean={v['mean']:.1f} p50={v['p50']:.1f} p90={v['p90']:.1f} p95={v['p95']:.1f}",
                flush=True,
            )

        results = relabel_pure_p90(page, old_oracle, n_roll=n_roll, max_seasons=max_seasons)
        scenarios, flips = write_scenarios(results, margin, old_oracle)
        new_oracle = {s["id"]: int(s["best_i"]) for s in scenarios}

        print("=== BAKEOFF after pure-P90 oracle ===", flush=True)
        after = bakeoff(page, new_oracle, n_careers=n_careers)
        for k, v in after.items():
            print(
                f"  {k:10s} mean={v['mean']:.1f} p50={v['p50']:.1f} p90={v['p90']:.1f} p95={v['p95']:.1f}",
                flush=True,
            )
        browser.close()

    strong = sum(1 for r in results if float(r["margin"]) >= margin)
    report = {
        "source": "real_Engine_playwright_pure_p90",
        "objective": "maximize_P90_computeCareerScore",
        "n_events": len(scenarios),
        "n_roll": n_roll,
        "max_seasons": max_seasons,
        "margin": margin,
        "n_strong": strong,
        "n_flips_vs_prev": len(flips),
        "flips": flips[:80],
        "bakeoff_before": before,
        "bakeoff_after": after,
        "n_careers_bakeoff": n_careers,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    refresh_retrieval_note()
    print(
        f"DONE strong={strong}/{len(scenarios)} flips={len(flips)} elapsed={report['elapsed_sec']}s",
        flush=True,
    )
    print(
        f"career P90: oracle {before['oracle']['p90']:.1f} -> {after['oracle']['p90']:.1f} "
        f"(random {after['random']['p90']:.1f})",
        flush=True,
    )


if __name__ == "__main__":
    main()
