"""
Reward the coach ONLY for top-world careers (not local choice 'success').

Top mondial := Ballon d'Or (>=1) AND career score >= SCORE_MIN
  (world-class individual + elite computeCareerScore).

Monte Carlo full Engine careers → credit each (event, choice) with 0/1 top flag
→ best_i = argmax P(top mondial | choice). UI uses those rates as "Top mondial %".
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
BACKUP = Path("docs/scenarios_before_top_mondial.json")
REPORT = Path("docs/top_mondial_report.json")
RAW = Path("data/top_mondial_raw.json")
TREE = Path("docs/tree_model.json")
TREE_REPORT = Path("docs/tree_train_report.json")

# Tuned from probe_top_world: p90~231 p95~247 on strong policy; ballon~27%
SCORE_MIN = 240

APPEND = r"""
;try{
  window.__D11 = {
    EVENTS, MICRO_EVENTS, ORIGINS, LIFESTYLES, POSITIONS, ENTOURAGES, NATIONALITIES,
    CLUBS: (typeof CLUBS !== 'undefined' ? CLUBS : null)
  };
}catch(e){ window.__D11Err = String(e); }
"""

CORE = f"""
(() => {{
  const SCORE_MIN = {SCORE_MIN};
  const pack = () => window.__D11;
  const Eng = () => Engine;

  function setupBase() {{
    const p = pack();
    return {{
      name: 'TopMondial',
      nationality: p.NATIONALITIES.find(x => x.id === 'fr') || p.NATIONALITIES[0],
      origin: p.ORIGINS.find(x => x.id === 'quartier') || p.ORIGINS[0],
      position: p.POSITIONS.find(x => x.id === 'att') || p.POSITIONS[0],
      lifestyle: p.LIFESTYLES.find(x => x.id === 'pro') || p.LIFESTYLES[0],
      entourage: p.ENTOURAGES.find(x => /ambit/i.test((x.id||'')+(x.name||''))) || p.ENTOURAGES[0],
      club: p.CLUBS.find(c => c.id === 'fr_rennes') || p.CLUBS.find(c => c.level === 'd1') || p.CLUBS[0],
    }};
  }}

  function optionLabel(o) {{
    let lab = String(o.label || o.text || '');
    if (o.hint) lab = o.hint + ': ' + lab;
    if (o.tag) lab = o.tag + ': ' + lab;
    return lab;
  }}

  function makePrng(seed) {{
    let a = (seed >>> 0) || 1;
    return function() {{
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }};
  }}

  function isTopMondial(g, score) {{
    const ballon = (g.trophies && g.trophies.ballon) || 0;
    const rank = g.bestBallonRank;
    // Reward ONLY world-top signal — not average "good career"
    const ballonWin = ballon >= 1 || (rank != null && rank === 1);
    return !!(ballonWin && score >= SCORE_MIN);
  }}

  function pickOi(ev, mode, oracle, eps, rnd) {{
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts.length) return 0;
    const roll = rnd || Math.random;
    if (mode === 'random' || (eps && roll() < eps)) {{
      return Math.floor(roll() * opts.length) % opts.length;
    }}
    if (mode === 'oracle' && oracle && Object.prototype.hasOwnProperty.call(oracle, ev.id)) {{
      const v = oracle[ev.id]|0;
      return Math.max(0, Math.min(opts.length - 1, v));
    }}
    if (mode === 'always0') return 0;
    const E = Eng();
    let best = 0, bestS = -1e99;
    for (let i = 0; i < opts.length; i++) {{
      const outs = opts[i].outcomes || [];
      let tw = 0, s = 0;
      for (const oc of outs) {{
        const w = oc.weight || 1; tw += w;
        try {{ s += w * E.netImpact(oc.fx || {{}}); }} catch (e) {{}}
      }}
      const evs = tw ? s / tw : 0;
      if (evs > bestS) {{ bestS = evs; best = i; }}
    }}
    return best;
  }}

  function playCareerLogged(seed, mode, oracle, eps, maxAge) {{
    const E = Eng();
    E.setSeed(seed >>> 0);
    const rnd = makePrng((seed * 2654435761) >>> 0);
    const g = E.newCareer(setupBase());
    const decisions = [];
    for (let y = 0; y < 40 && !g.careerEnded && !g.retiring && g.age < (maxAge || 34); y++) {{
      try {{ E.playSeason(g); }} catch (e) {{}}
      for (let k = 0; k < 2; k++) {{
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try {{ ev = E.pickEvent(g); }} catch (e) {{ break; }}
        if (!ev || !ev.id) break;
        const opts = (ev.options || []).filter(o => o && (o.label || o.text));
        if (opts.length < 2) break;
        const oi = pickOi(ev, mode, oracle, eps, rnd);
        try {{
          E.resolveOption(g, opts[oi]);
          decisions.push({{ id: ev.id, oi, n: opts.length }});
        }} catch (e) {{}}
      }}
      const a0 = g.age;
      try {{ E.advanceYear(g); }} catch (e) {{}}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }}
    const score = E.computeCareerScore(g);
    const top = isTopMondial(g, score) ? 1 : 0;
    return {{
      score, top,
      ballon: (g.trophies && g.trophies.ballon) || 0,
      bestBallonRank: g.bestBallonRank,
      decisions,
    }};
  }}

  function batchLogged(seeds, mode, oracle, eps) {{
    return seeds.map(s => playCareerLogged(s, mode, oracle, eps, 34));
  }}

  function batchTopRate(seeds, mode, oracle) {{
    let tops = 0, nEv = 0;
    const scores = [];
    for (let i = 0; i < seeds.length; i++) {{
      const r = playCareerLogged(seeds[i], mode, oracle, 0, 34);
      scores.push(r.score);
      tops += r.top;
      nEv += r.decisions.length;
    }}
    const arr = scores.slice().sort((a,b)=>a-b);
    const pct = (p) => arr[Math.min(arr.length-1, Math.floor((p/100)*(arr.length-1)))];
    return {{
      n: scores.length,
      topRate: tops / (scores.length || 1),
      topN: tops,
      mean: scores.reduce((s,x)=>s+x,0)/(scores.length||1),
      p90: pct(90),
      meanEvents: nEv/(scores.length||1),
    }};
  }}

  function eventCatalog() {{
    return pack().EVENTS
      .filter(e => ((e.options||[]).filter(o=>o&&(o.label||o.text))).length >= 2)
      .map(e => ({{
        id: e.id,
        cat: e.cat || null,
        text: String(e.text || ''),
        labels: (e.options || []).filter(o => o && (o.label || o.text)).map(optionLabel),
      }}));
  }}

  window.__D11Top = {{ batchLogged, batchTopRate, eventCatalog, SCORE_MIN }};
}})();
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
            print("boot", page.evaluate("() => ({e:window.__D11.EVENTS.length,S:window.__D11Top.SCORE_MIN})"), flush=True)
            return
        page.wait_for_timeout(400)
    raise RuntimeError("boot failed")


def load_prev() -> dict[str, dict]:
    if DOCS_SCEN.exists():
        return {r["id"]: r for r in json.loads(DOCS_SCEN.read_text(encoding="utf-8"))}
    return {}


def aggregate(catalog, credit, prev, min_n=20, min_gap=0.03):
    """best_i = argmax P(top|choice). Keep prev if under-sampled."""
    policy = {}
    scenarios = []
    stats = {"labeled": 0, "kept_prev": 0, "flips": 0}
    for ev in catalog:
        eid = ev["id"]
        labels = ev["labels"]
        n = len(labels)
        by = credit.get(eid, {})
        rates, counts = [], []
        for i in range(n):
            hits = by.get(i, [])  # list of 0/1
            counts.append(len(hits))
            rates.append(float(np.mean(hits)) if hits else None)

        covered = all(c >= min_n for c in counts) and all(r is not None for r in rates)
        prev_row = prev.get(eid)
        prev_i = int(prev_row["best_i"]) % n if prev_row else 0

        if covered:
            rates_f = [float(r) for r in rates]
            best_i = int(np.argmax(rates_f))
            ordered = sorted(rates_f, reverse=True)
            gap = ordered[0] - ordered[1] if len(ordered) > 1 else 1.0
            if gap < min_gap:
                best_i = prev_i
                goal = "top_mondial_tie_keep"
                stats["kept_prev"] += 1
            else:
                goal = "top_mondial_rate"
                stats["labeled"] += 1
                if best_i != prev_i:
                    stats["flips"] += 1
            raw = [100.0 * r for r in rates_f]  # store as %
        else:
            best_i = prev_i
            goal = "top_mondial_undersampled"
            stats["kept_prev"] += 1
            if prev_row and prev_row.get("raw_scores") and len(prev_row["raw_scores"]) == n:
                raw = [float(x) for x in prev_row["raw_scores"]]
            else:
                raw = [10.0] * n
                raw[best_i] = 40.0

        lo, hi = min(raw), max(raw)
        quals = []
        for v in raw:
            t = 0.5 if abs(hi - lo) < 1e-9 else (v - lo) / (hi - lo)
            quals.append(35.0 + 55.0 * t)
        quals[best_i] = max(quals[best_i], 93.0)

        prompt = (ev.get("text") or (prev_row or {}).get("prompt") or "")
        prompt = prompt.replace("{club}", "ton club").replace("{Club}", "ton club").replace("{name}", "toi")
        if not prompt and prev_row:
            prompt = prev_row.get("prompt") or ""

        policy[eid] = best_i
        scenarios.append(
            {
                "id": eid,
                "cat": ev.get("cat") or (prev_row or {}).get("cat"),
                "prompt": prompt,
                "choices": labels,
                "best_i": best_i,
                "raw_scores": raw,
                "qualities": quals,
                "label_goal": goal,
                "top_mondial_rates": rates if covered else None,
                "top_mondial_counts": counts,
                "reward": "ballon>=1_and_score>=" + str(SCORE_MIN),
            }
        )
    return policy, scenarios, stats


def write_scenarios(scenarios):
    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = [
        {
            k: s[k]
            for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities")
            if k in s
        }
        for s in scenarios
    ]
    # attach top rates into docs for UI (optional fields ok)
    for d, s in zip(docs, scenarios):
        if s.get("top_mondial_rates"):
            d["top_mondial_pct"] = [round(100 * float(x), 1) for x in s["top_mondial_rates"]]
        d["label_goal"] = s.get("label_goal")
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def main():
    t0 = time.time()
    n_careers = 5000
    batch = 250
    prev = load_prev()
    if DOCS_SCEN.exists() and not BACKUP.exists():
        BACKUP.write_text(DOCS_SCEN.read_text(encoding="utf-8"), encoding="utf-8")

    prev_oracle = {k: int(v["best_i"]) for k, v in prev.items()}
    credit: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        page.set_default_timeout(0)
        catalog = page.evaluate("() => window.__D11Top.eventCatalog()")
        print(f"catalog={len(catalog)} prev={len(prev)} SCORE_MIN={SCORE_MIN}", flush=True)

        seeds_ref = [40_000 + i * 11 for i in range(100)]
        before = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Top.batchTopRate(seeds, 'random', {})""",
                {"seeds": seeds_ref},
            ),
            "prev": page.evaluate(
                """({seeds, oracle}) => window.__D11Top.batchTopRate(seeds, 'oracle', oracle)""",
                {"seeds": seeds_ref, "oracle": prev_oracle},
            ),
            "always0": page.evaluate(
                """({seeds}) => window.__D11Top.batchTopRate(seeds, 'always0', {})""",
                {"seeds": seeds_ref},
            ),
        }
        for k, v in before.items():
            print(
                f"before {k:8s} topRate={100*v['topRate']:.1f}% p90={v['p90']:.0f} mean={v['mean']:.0f}",
                flush=True,
            )

        schedule = [
            ("random", 1.0, n_careers // 2),
            ("oracle", 0.4, n_careers // 4),
            ("always0", 0.2, n_careers // 4),
        ]
        seed0 = 2_000_000
        done = 0
        top_hits = 0
        for mode, eps, n_mode in schedule:
            print(f"=== sample {mode} eps={eps} n={n_mode} ===", flush=True)
            left = n_mode
            while left > 0:
                take = min(batch, left)
                seeds = [seed0 + done + i for i in range(take)]
                oracle = prev_oracle if mode == "oracle" else {}
                js_mode = mode if mode != "oracle" else "oracle"
                part = page.evaluate(
                    """({seeds, mode, oracle, eps}) => window.__D11Top.batchLogged(seeds, mode, oracle, eps)""",
                    {"seeds": seeds, "mode": js_mode, "oracle": oracle, "eps": float(eps)},
                )
                for career in part:
                    top = int(career["top"])
                    top_hits += top
                    for d in career["decisions"]:
                        credit[d["id"]][int(d["oi"])].append(top)
                done += take
                left -= take
                if done % 500 == 0 or left == 0:
                    print(
                        f"  careers={done}/{n_careers} top_hits={top_hits} "
                        f"rate={100*top_hits/max(done,1):.1f}% events={len(credit)}",
                        flush=True,
                    )

        compact = {
            eid: {
                str(i): {"n": len(v), "topRate": float(np.mean(v)) if v else 0.0}
                for i, v in ch.items()
            }
            for eid, ch in credit.items()
        }
        RAW.write_text(
            json.dumps(
                {"n_careers": done, "top_hits": top_hits, "score_min": SCORE_MIN, "credit": compact},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        policy, scenarios, stats = aggregate(catalog, credit, prev, min_n=18, min_gap=0.02)
        print(f"aggregate {stats}", flush=True)
        write_scenarios(scenarios)

        seeds_f = [300_000 + i * 13 for i in range(150)]
        after = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Top.batchTopRate(seeds, 'random', {})""",
                {"seeds": seeds_f},
            ),
            "prev": page.evaluate(
                """({seeds, oracle}) => window.__D11Top.batchTopRate(seeds, 'oracle', oracle)""",
                {"seeds": seeds_f, "oracle": prev_oracle},
            ),
            "top_mondial": page.evaluate(
                """({seeds, oracle}) => window.__D11Top.batchTopRate(seeds, 'oracle', oracle)""",
                {"seeds": seeds_f, "oracle": policy},
            ),
            "always0": page.evaluate(
                """({seeds}) => window.__D11Top.batchTopRate(seeds, 'always0', {})""",
                {"seeds": seeds_f},
            ),
        }
        for k, v in after.items():
            print(
                f"after  {k:12s} topRate={100*v['topRate']:.1f}% p90={v['p90']:.0f}",
                flush=True,
            )
        browser.close()

    # ship best by topRate
    cands = [
        ("prev", prev_oracle, after["prev"]["topRate"]),
        ("top_mondial", policy, after["top_mondial"]["topRate"]),
        ("always0", {e["id"]: 0 for e in catalog}, after["always0"]["topRate"]),
    ]
    best_name, best_pol, best_rate = max(cands, key=lambda x: x[2])
    print(f"SHIP={best_name} topRate={100*best_rate:.1f}%", flush=True)
    by = {s["id"]: s for s in scenarios}
    for eid, bi in best_pol.items():
        if eid in by:
            by[eid]["best_i"] = int(bi) % len(by[eid]["choices"])
            by[eid]["label_goal"] = f"ship_{best_name}_top_mondial"
    scenarios = list(by.values())
    write_scenarios(scenarios)

    if TREE.exists():
        model = json.loads(TREE.read_text(encoding="utf-8"))
        model["label_goal"] = "top_mondial_binary_reward"
        model["reward"] = f"ballon>=1 AND score>={SCORE_MIN}"
        model["note"] = (
            "Model rewarded ONLY for top-world careers (Ballon d'Or + high career score). "
            "Not local choice success/netImpact. Labels = P(top mondial | choice) from Engine MC."
        )
        model["engine_top_mondial"] = {k: v["topRate"] for k, v in after.items()}
        TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        TREE_REPORT.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "reward": f"ballon>=1 AND computeCareerScore>={SCORE_MIN}",
        "n_careers": done,
        "top_hits_in_sample": top_hits,
        "sample_top_rate": top_hits / max(done, 1),
        "aggregate": stats,
        "before": before,
        "after": after,
        "shipped": best_name,
        "shipped_top_rate": best_rate,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE ship={best_name} topRate={100*best_rate:.1f}% "
        f"careers={done} elapsed={report['elapsed_sec']}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
