"""
Relabel ALL events with the REAL Destiny Eleven Engine (Playwright).

Batches events for progress + reliability.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SCENARIOS = Path("data/game_scenarios.jsonl")
DOCS_SCEN = Path("docs/scenarios.json")
REPORT = Path("docs/engine_cf_report.json")
RAW_RESULTS = Path("data/engine_cf_results.json")

APPEND = r"""
;try{
  window.__D11 = {
    EVENTS, MICRO_EVENTS, ORIGINS, LIFESTYLES, POSITIONS, ENTOURAGES, NATIONALITIES,
    CLUBS: (typeof CLUBS !== 'undefined' ? CLUBS : null)
  };
}catch(e){ window.__D11Err = String(e); }
"""

BATCH_JS = r"""
({ eventIds, nRoll, maxSeasons, objMean, objP90 }) => {
  const pack = window.__D11, E = Engine;
  const byId = {};
  for (const ev of pack.EVENTS) byId[ev.id] = ev;

  const setupBase = () => ({
    name: 'EngineCF',
    nationality: pack.NATIONALITIES.find(x => x.id === 'fr') || pack.NATIONALITIES[0],
    origin: pack.ORIGINS.find(x => x.id === 'quartier') || pack.ORIGINS[0],
    position: pack.POSITIONS.find(x => x.id === 'att') || pack.POSITIONS[0],
    lifestyle: pack.LIFESTYLES.find(x => x.id === 'pro') || pack.LIFESTYLES[0],
    entourage: pack.ENTOURAGES.find(x => /ambit/i.test((x.id||'')+(x.name||''))) || pack.ENTOURAGES[0],
    club: pack.CLUBS.find(c => c.id === 'fr_rennes') || pack.CLUBS.find(c => c.level === 'd1') || pack.CLUBS[0],
  });

  function optionLabel(o) {
    let lab = String(o.label || o.text || '');
    if (o.hint) lab = o.hint + ': ' + lab;
    if (o.tag) lab = o.tag + ': ' + lab;
    return lab;
  }

  function bestOptionIndex(ev) {
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
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

  function continueCareer(g, seed, seasons) {
    E.setSeed(seed);
    for (let s = 0; s < seasons; s++) {
      if (g.careerEnded || g.retiring) break;
      try { E.playSeason(g); } catch (e) {}
      const nEv = 1 + Math.floor(E.rand() * 2);
      for (let k = 0; k < nEv; k++) {
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try { ev = E.pickEvent(g); } catch (e) { break; }
        if (!ev || !ev.options || !ev.options.length) break;
        const opts = ev.options.filter(o => o && (o.label || o.text));
        if (!opts.length) break;
        const oi = bestOptionIndex(ev);
        try { E.resolveOption(g, opts[Math.min(oi, opts.length - 1)]); } catch (e) {}
      }
      const ageBefore = g.age;
      try { E.advanceYear(g); } catch (e) {}
      if (g.age === ageBefore && !g.careerEnded) g.age = ageBefore + 1;
    }
    return E.computeCareerScore(g);
  }

  function forceChoice(ev, choiceI, rollSeed) {
    E.setSeed(rollSeed);
    let g = E.newCareer(setupBase());
    const cond = ev.cond || {};
    const aMin = cond.aMin != null ? cond.aMin : 16;
    const aMax = cond.aMax != null ? cond.aMax : Math.min(32, aMin + 3);
    const targetAge = aMin + Math.floor((Math.max(0, aMax - aMin)) * 0.4);
    let guard = 0;
    while (g.age < targetAge && !g.careerEnded && !g.retiring && guard < 25) {
      try { E.playSeason(g); } catch (e) {}
      const a0 = g.age;
      try { E.advanceYear(g); } catch (e) {}
      if (g.age === a0) g.age = a0 + 1;
      if (cond.minRep != null && g.rep < cond.minRep) g.rep = cond.minRep + 1;
      guard++;
    }
    if (cond.minRep != null && g.rep < cond.minRep) g.rep = Number(cond.minRep) + 2;
    if (cond.minOvr != null) {
      let guard2 = 0;
      while (E.ovr(g) < cond.minOvr && guard2 < 40) {
        g.stats.t += 1; g.stats.p += 1; g.stats.m += 1; g.stats.c += 1;
        guard2++;
      }
    }
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts[choiceI]) return null;
    try { E.resolveOption(g, opts[choiceI]); }
    catch (e) {
      const outs = opts[choiceI].outcomes || [];
      let tw = outs.reduce((s, o) => s + (o.weight || 1), 0) || 1;
      let r = E.rand() * tw, acc = 0, picked = outs[0];
      for (const o of outs) { acc += (o.weight || 1); if (r <= acc) { picked = o; break; } }
      if (picked && picked.fx) E.applyFx(g, picked.fx);
    }
    if (g.careerEnded || g.retiring) return E.computeCareerScore(g);
    return continueCareer(g, rollSeed + 91, maxSeasons);
  }

  function statsOf(arr) {
    arr = arr.filter(x => typeof x === 'number' && isFinite(x));
    if (!arr.length) return {mean:0,p50:0,p90:0,obj:0,n:0};
    arr.sort((a,b)=>a-b);
    const mean = arr.reduce((s,x)=>s+x,0)/arr.length;
    const pct = (p) => arr[Math.min(arr.length-1, Math.floor((p/100)*(arr.length-1)))];
    const p90 = pct(90);
    return {mean, p50:pct(50), p90, obj: objMean*mean + objP90*p90, n:arr.length};
  }

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
        const sc = forceChoice(ev, ci, 200000 + ei * 1009 + ci * 307 + r * 13);
        if (typeof sc === 'number' && isFinite(sc)) scores.push(sc);
      }
      vals.push(statsOf(scores));
    }
    const objs = vals.map(v => v.obj);
    let bestI = 0;
    for (let i = 1; i < objs.length; i++) if (objs[i] > objs[bestI]) bestI = i;
    const sorted = objs.slice().sort((a,b)=>b-a);
    const marg = sorted.length > 1 ? sorted[0] - sorted[1] : 99;
    out.push({
      id: ev.id,
      cat: ev.cat || null,
      text: String(ev.text || ''),
      labels: opts.map(optionLabel),
      vals, objs, best_i: bestI, margin: marg
    });
  }
  return out;
}
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
            n = page.evaluate("() => ({e:window.__D11.EVENTS.length,c:window.__D11.CLUBS.length})")
            print("boot", n)
            return
        page.wait_for_timeout(400)
    raise RuntimeError("Engine boot failed")


def write_scenarios(results, margin):
    old = {}
    if SCENARIOS.exists():
        for line in SCENARIOS.open(encoding="utf-8"):
            s = json.loads(line)
            if s.get("id") is not None:
                old[s["id"]] = int(s["best_i"])

    scenarios, flips = [], []
    for r in results:
        labels = r["labels"]
        objs = [float(x) for x in r["objs"]]
        strong = float(r["margin"]) >= margin
        if strong:
            best_i = int(r["best_i"])
            goal = "engine_cf_p90"
        else:
            best_i = old.get(r["id"], int(r["best_i"]))
            if best_i >= len(labels):
                best_i = int(r["best_i"])
            goal = "engine_cf_tie_keep"
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
                "engine_means": [float(v["mean"]) for v in r["vals"]],
                "engine_p90s": [float(v["p90"]) for v in r["vals"]],
            }
        )
        if strong and old.get(r["id"]) is not None and old[r["id"]] != best_i:
            flips.append(
                {
                    "id": r["id"],
                    "old": labels[old[r["id"]]] if old[r["id"]] < len(labels) else "?",
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


def main():
    n_roll = 24
    max_seasons = 12
    margin = 2.5
    batch_size = 12
    t0 = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        event_ids = page.evaluate(
            """() => window.__D11.EVENTS
              .filter(e => ((e.options||[]).filter(o=>o&&(o.label||o.text))).length>=2)
              .map(e => e.id)"""
        )
        print(f"events={len(event_ids)} rolls={n_roll} seasons={max_seasons}")
        all_results = []
        for i in range(0, len(event_ids), batch_size):
            chunk = event_ids[i : i + batch_size]
            print(f"batch {i//batch_size+1}/{(len(event_ids)+batch_size-1)//batch_size} ({chunk[0]}..)")
            page.set_default_timeout(0)
            part = page.evaluate(
                BATCH_JS,
                {
                    "eventIds": chunk,
                    "nRoll": n_roll,
                    "maxSeasons": max_seasons,
                    "objMean": 0.35,
                    "objP90": 0.65,
                },
            )
            all_results.extend(part)
            # checkpoint
            RAW_RESULTS.write_text(json.dumps(all_results, ensure_ascii=False), encoding="utf-8")
        browser.close()

    scenarios, flips = write_scenarios(all_results, margin)
    strong = sum(1 for r in all_results if float(r["margin"]) >= margin)
    report = {
        "source": "real_Engine_playwright",
        "n_events": len(scenarios),
        "n_roll": n_roll,
        "max_seasons": max_seasons,
        "margin": margin,
        "n_strong": strong,
        "n_flips_vs_prev": len(flips),
        "flips": flips[:60],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE events={len(scenarios)} strong={strong} flips={len(flips)} elapsed={report['elapsed_sec']}s"
    )
    for f in flips[:12]:
        old = (f["old"] or "").encode("ascii", "replace").decode("ascii")[:40]
        new = (f["new"] or "").encode("ascii", "replace").decode("ascii")[:40]
        print(f"  {f['id']}: '{old}' -> '{new}' marg={f['margin']:.1f}")


if __name__ == "__main__":
    main()
