"""
Train coach oracle for MAX TROPHIES (personal OR team).

trophyScore = ballon*2 + goldenBoot + league + cup + continental + worldCup
              (+ any other numeric fields on g.trophies)

Monte Carlo full Engine careers with a separate PRNG for policy exploration
(never starve pickEvent via Engine.rand). Credit each (event, choice) with
the career's final trophyScore; label best_i = argmax P90(trophyScore|choice).
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
BACKUP = Path("docs/scenarios_before_trophy_max.json")
REPORT = Path("docs/trophy_train_report.json")
RAW = Path("data/trophy_train_raw.json")
TREE = Path("docs/tree_model.json")
TREE_REPORT = Path("docs/tree_train_report.json")

# Personal slightly weighted; team trophies still count 1:1
BALLON_WEIGHT = 2.0

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
  const BALLON_W = {BALLON_WEIGHT};
  const pack = () => window.__D11;
  const Eng = () => Engine;

  function setupBase() {{
    const p = pack();
    return {{
      name: 'TrophyMax',
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

  /** Mulberry32 — separate from Engine RNG so exploration does not starve pickEvent. */
  function makePrng(seed) {{
    let a = (seed >>> 0) || 1;
    return function() {{
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }};
  }}

  function trophyScore(g) {{
    const t = g.trophies || {{}};
    const known = new Set(['ballon','goldenBoot','league','cup','continental','worldCup']);
    let s = BALLON_W * (t.ballon || 0)
      + (t.goldenBoot || 0)
      + (t.league || 0)
      + (t.cup || 0)
      + (t.continental || 0)
      + (t.worldCup || 0);
    for (const k of Object.keys(t)) {{
      if (known.has(k)) continue;
      const v = t[k];
      if (typeof v === 'number' && isFinite(v) && v > 0) s += v;
    }}
    return s;
  }}

  function trophyBreakdown(g) {{
    const t = g.trophies || {{}};
    return {{
      ballon: t.ballon || 0,
      goldenBoot: t.goldenBoot || 0,
      league: t.league || 0,
      cup: t.cup || 0,
      continental: t.continental || 0,
      worldCup: t.worldCup || 0,
    }};
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
    // netImpact — does not consume Engine.rand
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
    const trophies = trophyScore(g);
    return {{
      score,
      trophies,
      breakdown: trophyBreakdown(g),
      decisions,
    }};
  }}

  function batchLogged(seeds, mode, oracle, eps) {{
    return seeds.map(s => playCareerLogged(s, mode, oracle, eps, 34));
  }}

  function batchTrophyStats(seeds, mode, oracle) {{
    const scores = [];
    const trophies = [];
    let nEv = 0;
    for (let i = 0; i < seeds.length; i++) {{
      const r = playCareerLogged(seeds[i], mode, oracle, 0, 34);
      scores.push(r.score);
      trophies.push(r.trophies);
      nEv += r.decisions.length;
    }}
    const sortNum = (arr) => arr.slice().sort((a,b)=>a-b);
    const pct = (arr, p) => {{
      const t = sortNum(arr);
      return t[Math.min(t.length-1, Math.floor((p/100)*(t.length-1)))];
    }};
    const mean = (arr) => arr.reduce((s,x)=>s+x,0)/(arr.length||1);
    return {{
      n: scores.length,
      meanScore: mean(scores),
      p90Score: pct(scores, 90),
      meanTrophy: mean(trophies),
      p50Trophy: pct(trophies, 50),
      p90Trophy: pct(trophies, 90),
      maxTrophy: trophies.length ? Math.max(...trophies) : 0,
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

  window.__D11Trophy = {{ batchLogged, batchTrophyStats, eventCatalog, BALLON_W }};
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
            print(
                "boot",
                page.evaluate("() => ({e:window.__D11.EVENTS.length,w:window.__D11Trophy.BALLON_W})"),
                flush=True,
            )
            return
        page.wait_for_timeout(400)
    raise RuntimeError("boot failed")


def load_prev() -> dict[str, dict]:
    if DOCS_SCEN.exists():
        return {r["id"]: r for r in json.loads(DOCS_SCEN.read_text(encoding="utf-8"))}
    return {}


def p90(arr: list[float]) -> float:
    if not arr:
        return 0.0
    a = sorted(arr)
    return float(a[min(len(a) - 1, int(0.90 * (len(a) - 1)))])


def aggregate(catalog, credit, prev, min_n=18, min_gap=0.35):
    """best_i = argmax P90(trophyScore|choice). Keep prev if under-sampled."""
    policy = {}
    scenarios = []
    stats = {"labeled": 0, "kept_prev": 0, "flips": 0}
    for ev in catalog:
        eid = ev["id"]
        labels = ev["labels"]
        n = len(labels)
        by = credit.get(eid, {})
        objs, counts = [], []
        for i in range(n):
            hits = by.get(i, [])
            counts.append(len(hits))
            objs.append(p90(hits) if len(hits) >= max(8, min_n // 3) else None)

        covered = all(c >= min_n for c in counts) and all(o is not None for o in objs)
        prev_row = prev.get(eid)
        prev_i = int(prev_row["best_i"]) % n if prev_row else 0

        if covered:
            objs_f = [float(o) for o in objs]
            best_i = int(np.argmax(objs_f))
            ordered = sorted(objs_f, reverse=True)
            gap = ordered[0] - ordered[1] if len(ordered) > 1 else 99.0
            if gap < min_gap:
                best_i = prev_i
                goal = "trophy_max_tie_keep"
                stats["kept_prev"] += 1
            else:
                goal = "trophy_max"
                stats["labeled"] += 1
                if best_i != prev_i:
                    stats["flips"] += 1
            raw = objs_f
        else:
            best_i = prev_i
            goal = "trophy_max_undersampled"
            stats["kept_prev"] += 1
            if prev_row and prev_row.get("raw_scores") and len(prev_row["raw_scores"]) == n:
                # Previous may be top-mondial % — only reuse if already trophy-ish scale
                # Prefer neutral prior when migrating from % labels
                prev_goal = str(prev_row.get("label_goal") or "")
                if "trophy" in prev_goal:
                    raw = [float(x) for x in prev_row["raw_scores"]]
                else:
                    raw = [1.0] * n
                    raw[best_i] = 3.0
            else:
                raw = [1.0] * n
                raw[best_i] = 3.0

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
                "trophy_p90": [round(float(x), 2) for x in raw],
                "trophy_counts": counts,
                "reward": "trophyScore=ballon*2+goldenBoot+league+cup+continental+worldCup",
            }
        )
    return policy, scenarios, stats


def write_scenarios(scenarios):
    SCENARIOS.parent.mkdir(parents=True, exist_ok=True)
    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = []
    for s in scenarios:
        d = {
            k: s[k]
            for k in ("id", "cat", "prompt", "choices", "best_i", "raw_scores", "qualities")
            if k in s
        }
        d["label_goal"] = "trophy_max"
        d["reward"] = "trophy_max"
        if s.get("trophy_p90"):
            d["trophy_p90"] = s["trophy_p90"]
        docs.append(d)
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def main():
    t0 = time.time()
    # ~5–10 min budget: 12k careers (5k took ~105s for top_mondial)
    n_careers = 12_000
    batch = 250
    prev = load_prev()
    if DOCS_SCEN.exists() and not BACKUP.exists():
        BACKUP.write_text(DOCS_SCEN.read_text(encoding="utf-8"), encoding="utf-8")

    prev_oracle = {k: int(v["best_i"]) for k, v in prev.items()}
    credit: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        page.set_default_timeout(0)
        catalog = page.evaluate("() => window.__D11Trophy.eventCatalog()")
        print(f"catalog={len(catalog)} prev={len(prev)} n_careers={n_careers}", flush=True)

        seeds_ref = [40_000 + i * 11 for i in range(120)]
        before = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'random', {})""",
                {"seeds": seeds_ref},
            ),
            "prev": page.evaluate(
                """({seeds, oracle}) => window.__D11Trophy.batchTrophyStats(seeds, 'oracle', oracle)""",
                {"seeds": seeds_ref, "oracle": prev_oracle},
            ),
            "always0": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'always0', {})""",
                {"seeds": seeds_ref},
            ),
            "netImpact": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'netImpact', {})""",
                {"seeds": seeds_ref},
            ),
        }
        for k, v in before.items():
            print(
                f"before {k:10s} meanT={v['meanTrophy']:.2f} p90T={v['p90Trophy']:.1f} "
                f"p90S={v['p90Score']:.0f} ev={v['meanEvents']:.1f}",
                flush=True,
            )

        # High exploration: many random paths + eps around oracle + always0/netImpact
        schedule = [
            ("random", 1.0, int(n_careers * 0.40)),
            ("oracle", 0.50, int(n_careers * 0.25)),
            ("always0", 0.35, int(n_careers * 0.15)),
            ("netImpact", 0.40, n_careers - int(n_careers * 0.40) - int(n_careers * 0.25) - int(n_careers * 0.15)),
        ]
        seed0 = 3_000_000
        done = 0
        sum_t = 0.0
        n_dec = 0
        for mode, eps, n_mode in schedule:
            print(f"=== sample {mode} eps={eps} n={n_mode} ===", flush=True)
            left = n_mode
            while left > 0:
                take = min(batch, left)
                seeds = [seed0 + done + i for i in range(take)]
                oracle = prev_oracle if mode == "oracle" else {}
                part = page.evaluate(
                    """({seeds, mode, oracle, eps}) => window.__D11Trophy.batchLogged(seeds, mode, oracle, eps)""",
                    {"seeds": seeds, "mode": mode, "oracle": oracle, "eps": float(eps)},
                )
                for career in part:
                    tscore = float(career["trophies"])
                    sum_t += tscore
                    for d in career["decisions"]:
                        credit[d["id"]][int(d["oi"])].append(tscore)
                        n_dec += 1
                done += take
                left -= take
                if done % 1000 == 0 or left == 0:
                    print(
                        f"  careers={done}/{n_careers} meanT={sum_t/max(done,1):.2f} "
                        f"credits={n_dec} events={len(credit)} "
                        f"elapsed={time.time()-t0:.0f}s",
                        flush=True,
                    )

        compact = {
            eid: {
                str(i): {"n": len(v), "meanT": float(np.mean(v)), "p90T": p90(v)}
                for i, v in ch.items()
            }
            for eid, ch in credit.items()
        }
        RAW.write_text(
            json.dumps(
                {
                    "n_careers": done,
                    "decision_credits": n_dec,
                    "ballon_weight": BALLON_WEIGHT,
                    "credit": compact,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        policy, scenarios, stats = aggregate(catalog, credit, prev, min_n=16, min_gap=0.25)
        print(f"aggregate {stats}", flush=True)
        write_scenarios(scenarios)

        seeds_f = [300_000 + i * 13 for i in range(180)]
        after = {
            "random": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'random', {})""",
                {"seeds": seeds_f},
            ),
            "prev": page.evaluate(
                """({seeds, oracle}) => window.__D11Trophy.batchTrophyStats(seeds, 'oracle', oracle)""",
                {"seeds": seeds_f, "oracle": prev_oracle},
            ),
            "trophy": page.evaluate(
                """({seeds, oracle}) => window.__D11Trophy.batchTrophyStats(seeds, 'oracle', oracle)""",
                {"seeds": seeds_f, "oracle": policy},
            ),
            "always0": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'always0', {})""",
                {"seeds": seeds_f},
            ),
            "netImpact": page.evaluate(
                """({seeds}) => window.__D11Trophy.batchTrophyStats(seeds, 'netImpact', {})""",
                {"seeds": seeds_f},
            ),
        }
        for k, v in after.items():
            print(
                f"after  {k:10s} meanT={v['meanTrophy']:.2f} p90T={v['p90Trophy']:.1f} "
                f"meanS={v['meanScore']:.0f} p90S={v['p90Score']:.0f}",
                flush=True,
            )
        browser.close()

    # Ship by P90 trophy (primary), then mean trophy, then career P90
    cands = [
        ("prev", prev_oracle, after["prev"]),
        ("trophy", policy, after["trophy"]),
        ("always0", {e["id"]: 0 for e in catalog}, after["always0"]),
        ("netImpact", {}, after["netImpact"]),
    ]
    # netImpact uses mode not oracle — for shipping we only consider oracle policies
    ship_cands = [c for c in cands if c[0] in ("prev", "trophy", "always0")]
    best_name, best_pol, best_st = max(
        ship_cands,
        key=lambda x: (x[2]["p90Trophy"], x[2]["meanTrophy"], x[2]["p90Score"]),
    )
    print(
        f"SHIP={best_name} p90T={best_st['p90Trophy']:.1f} meanT={best_st['meanTrophy']:.2f}",
        flush=True,
    )
    by = {s["id"]: s for s in scenarios}
    for eid, bi in best_pol.items():
        if eid in by:
            by[eid]["best_i"] = int(bi) % len(by[eid]["choices"])
            by[eid]["label_goal"] = f"ship_{best_name}_trophy_max"
    scenarios = list(by.values())
    write_scenarios(scenarios)

    if TREE.exists():
        model = json.loads(TREE.read_text(encoding="utf-8"))
        model["label_goal"] = "trophy_max"
        model["reward"] = "trophyScore=ballon*2+goldenBoot+league+cup+continental+worldCup"
        model["note"] = (
            "Maximize total trophies (personal OR team). "
            "raw_scores = P90(trophyScore|choice) from Engine MC. "
            "UI shows Upside trophées (P90), not Ballon-only / Top mondial %."
        )
        model["n_careers_sampled"] = done
        model["decision_credits"] = n_dec
        model["engine_trophy"] = {
            k: {"meanTrophy": v["meanTrophy"], "p90Trophy": v["p90Trophy"], "p90Score": v["p90Score"]}
            for k, v in after.items()
        }
        TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        TREE_REPORT.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "reward": "trophyScore = ballon*2 + goldenBoot + league + cup + continental + worldCup (+other)",
        "label_goal": "trophy_max",
        "ballon_weight": BALLON_WEIGHT,
        "n_careers": done,
        "decision_credits": n_dec,
        "mean_trophy_in_sample": sum_t / max(done, 1),
        "aggregate": stats,
        "before": before,
        "after": after,
        "shipped": best_name,
        "shipped_p90_trophy": best_st["p90Trophy"],
        "shipped_mean_trophy": best_st["meanTrophy"],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE ship={best_name} p90T={best_st['p90Trophy']:.1f} "
        f"careers={done} credits={n_dec} elapsed={report['elapsed_sec']}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
