"""
Train 3 specialist oracles + soft-vote ensemble (Engine Monte Carlo).

  A) trophies     — P90(trophyScore|choice)          [1M careers]
  B) immediate    — mean(netImpact EV|choice)        [1M careers]
  C) top career   — P(top mondial|choice)            [1M careers]
  D) soft-vote    — follow A+B+C soft vote, distill
                    with blended career reward       [1M careers]

Accumulation stays in-page (reservoirs) to keep IPC cheap at 1M scale.
Parallel Playwright workers share the load.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
MODELS = DOCS / "models"
SCENARIOS = DATA / "game_scenarios.jsonl"
DOCS_SCEN = DOCS / "scenarios.json"
BACKUP = DOCS / "scenarios_before_softvote.json"
REPORT = DOCS / "triple_softvote_report.json"
TREE = DOCS / "tree_model.json"
TREE_REPORT = DOCS / "tree_train_report.json"

BALLON_WEIGHT = 2.0
SCORE_MIN = 240
RESERVOIR = 384

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
  const SCORE_MIN = {SCORE_MIN};
  const RES = {RESERVOIR};
  const pack = () => window.__D11;
  const Eng = () => Engine;

  function setupBase() {{
    const p = pack();
    return {{
      name: 'SoftVote',
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

  function trophyScore(g) {{
    const t = g.trophies || {{}};
    const known = new Set(['ballon','goldenBoot','league','cup','continental','worldCup']);
    let s = BALLON_W * (t.ballon || 0)
      + (t.goldenBoot || 0) + (t.league || 0) + (t.cup || 0)
      + (t.continental || 0) + (t.worldCup || 0);
    for (const k of Object.keys(t)) {{
      if (known.has(k)) continue;
      const v = t[k];
      if (typeof v === 'number' && isFinite(v) && v > 0) s += v;
    }}
    return s;
  }}

  function isTop(g, score) {{
    const ballon = (g.trophies && g.trophies.ballon) || 0;
    const rank = g.bestBallonRank;
    const ballonWin = ballon >= 1 || (rank != null && rank === 1);
    return !!(ballonWin && score >= SCORE_MIN);
  }}

  function expectedNetImpact(opt) {{
    const E = Eng();
    const outs = opt.outcomes || [];
    if (!outs.length) {{
      try {{ return E.netImpact(opt.fx || {{}}); }} catch (e) {{ return 0; }}
    }}
    let tw = 0, s = 0;
    for (const oc of outs) {{
      const w = oc.weight || 1; tw += w;
      try {{ s += w * E.netImpact(oc.fx || {{}}); }} catch (e) {{}}
    }}
    return tw ? s / tw : 0;
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

  let credits = {{}};
  function ensureBucket(goal, eid, oi) {{
    if (!credits[goal]) credits[goal] = {{}};
    if (!credits[goal][eid]) credits[goal][eid] = {{}};
    const k = String(oi);
    if (!credits[goal][eid][k]) credits[goal][eid][k] = {{n:0, sum:0, samples:[]}};
    return credits[goal][eid][k];
  }}
  function addSample(b, v, rnd) {{
    b.n += 1;
    b.sum += v;
    if (b.samples.length < RES) b.samples.push(v);
    else {{
      const j = Math.floor(rnd() * b.n);
      if (j < RES) b.samples[j] = v;
    }}
  }}
  function resetCredits(goal) {{
    if (goal) delete credits[goal];
    else credits = {{}};
  }}
  function exportCredits(goal) {{
    const src = credits[goal] || {{}};
    const out = {{}};
    for (const eid of Object.keys(src)) {{
      out[eid] = {{}};
      for (const k of Object.keys(src[eid])) {{
        const b = src[eid][k];
        const samp = b.samples.slice().sort((a,c)=>a-c);
        const p90 = samp.length
          ? samp[Math.min(samp.length-1, Math.floor(0.90*(samp.length-1)))]
          : 0;
        out[eid][k] = {{n:b.n, mean: b.n ? b.sum/b.n : 0, p90, sum: b.sum}};
      }}
    }}
    return out;
  }}

  function normScores(arr) {{
    if (!arr || !arr.length) return [];
    let lo = Infinity, hi = -Infinity;
    for (const v of arr) {{
      if (v == null || !isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }}
    if (!isFinite(lo)) return arr.map(() => 0.5);
    if (Math.abs(hi - lo) < 1e-12) return arr.map(() => 0.5);
    return arr.map(v => (v == null || !isFinite(v)) ? 0 : (v - lo) / (hi - lo));
  }}

  let softMaps = null;
  function setSoftMaps(maps) {{ softMaps = maps; }}

  function softVoteScores(eid, n) {{
    if (!softMaps) return null;
    const keys = ['trophy','immediate','top'];
    const acc = new Array(n).fill(0);
    let used = 0;
    for (const k of keys) {{
      const row = softMaps[k] && softMaps[k][eid];
      if (!row || row.length !== n) continue;
      const nn = normScores(row);
      for (let i = 0; i < n; i++) acc[i] += nn[i];
      used += 1;
    }}
    if (!used) return null;
    return acc.map(x => x / used);
  }}

  function pickOi(ev, mode, oracle, eps, rnd) {{
    const opts = (ev.options || []).filter(o => o && (o.label || o.text));
    if (!opts.length) return 0;
    if (mode === 'random' || (eps && rnd() < eps)) {{
      return Math.floor(rnd() * opts.length) % opts.length;
    }}
    if (mode === 'softvote') {{
      const sv = softVoteScores(ev.id, opts.length);
      if (sv) {{
        let best = 0, bestS = -1e99;
        for (let i = 0; i < sv.length; i++) if (sv[i] > bestS) {{ bestS = sv[i]; best = i; }}
        return best;
      }}
      mode = 'oracle';
    }}
    if (mode === 'oracle' && oracle && Object.prototype.hasOwnProperty.call(oracle, ev.id)) {{
      const v = oracle[ev.id]|0;
      return Math.max(0, Math.min(opts.length - 1, v));
    }}
    if (mode === 'always0') return 0;
    let best = 0, bestS = -1e99;
    for (let i = 0; i < opts.length; i++) {{
      const evs = expectedNetImpact(opts[i]);
      if (evs > bestS) {{ bestS = evs; best = i; }}
    }}
    return best;
  }}

  function playCareer(seed, mode, oracle, eps, goal) {{
    const E = Eng();
    E.setSeed(seed >>> 0);
    const rnd = makePrng((seed * 2654435761) >>> 0);
    const g = E.newCareer(setupBase());
    const decisions = [];
    let immSum = 0;
    for (let y = 0; y < 40 && !g.careerEnded && !g.retiring && g.age < 34; y++) {{
      try {{ E.playSeason(g); }} catch (e) {{}}
      for (let k = 0; k < 2; k++) {{
        if (g.careerEnded || g.retiring) break;
        let ev = null;
        try {{ ev = E.pickEvent(g); }} catch (e) {{ break; }}
        if (!ev || !ev.id) break;
        const opts = (ev.options || []).filter(o => o && (o.label || o.text));
        if (opts.length < 2) break;
        const oi = pickOi(ev, mode, oracle, eps, rnd);
        const imm = expectedNetImpact(opts[oi]);
        try {{
          E.resolveOption(g, opts[oi]);
          decisions.push({{ id: ev.id, oi, n: opts.length, imm }});
          immSum += imm;
        }} catch (e) {{}}
      }}
      const a0 = g.age;
      try {{ E.advanceYear(g); }} catch (e) {{}}
      if (g.age === a0 && !g.careerEnded) g.age = a0 + 1;
    }}
    const score = E.computeCareerScore(g);
    const trophies = trophyScore(g);
    const top = isTop(g, score) ? 1 : 0;
    const meanImm = decisions.length ? immSum / decisions.length : 0;

    if (goal === 'trophy' || goal === 'all') {{
      for (const d of decisions) addSample(ensureBucket('trophy', d.id, d.oi), trophies, rnd);
    }}
    if (goal === 'immediate' || goal === 'all') {{
      for (const d of decisions) addSample(ensureBucket('immediate', d.id, d.oi), d.imm, rnd);
    }}
    if (goal === 'top' || goal === 'all') {{
      for (const d of decisions) addSample(ensureBucket('top', d.id, d.oi), top, rnd);
    }}
    if (goal === 'blend') {{
      const blend = Math.min(2, trophies / 15) + top + Math.max(0, Math.min(1, (meanImm + 5) / 20));
      for (const d of decisions) addSample(ensureBucket('blend', d.id, d.oi), blend, rnd);
    }}
    return {{ score, trophies, top, meanImm, nDec: decisions.length }};
  }}

  function runBatch(seeds, mode, oracle, eps, goal) {{
    let sumT = 0, sumTop = 0, sumS = 0, nDec = 0;
    for (let i = 0; i < seeds.length; i++) {{
      const r = playCareer(seeds[i], mode, oracle, eps, goal);
      sumT += r.trophies;
      sumTop += r.top;
      sumS += r.score;
      nDec += r.nDec;
    }}
    const n = seeds.length || 1;
    return {{ n: seeds.length, meanT: sumT/n, topRate: sumTop/n, meanS: sumS/n, nDec }};
  }}

  function bakeStats(seeds, mode, oracle) {{
    const scores = [], trophies = [];
    let tops = 0, nEv = 0;
    for (let i = 0; i < seeds.length; i++) {{
      const r = playCareer(seeds[i], mode, oracle, 0, null);
      scores.push(r.score);
      trophies.push(r.trophies);
      tops += r.top;
      nEv += r.nDec;
    }}
    const sortNum = (a) => a.slice().sort((x,y)=>x-y);
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
      p90Trophy: pct(trophies, 90),
      topRate: tops / (scores.length || 1),
      meanEvents: nEv / (scores.length || 1),
    }};
  }}

  window.__D11SV = {{
    eventCatalog, runBatch, bakeStats, resetCredits, exportCredits, setSoftMaps,
    BALLON_W, SCORE_MIN,
  }};
}})();
"""


def boot(page, retries: int = 4):
    last_err = None
    for attempt in range(retries):
        try:
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

            try:
                page.unroute("**/*")
            except Exception:
                pass
            page.route("**/*", handle_route)
            page.goto("https://destinyeleven.com/", wait_until="domcontentloaded", timeout=180000)
            for _ in range(90):
                ok = page.evaluate(
                    """() => !!(window.__D11 && window.__D11.CLUBS && window.__D11.CLUBS.length
                      && typeof Engine!=='undefined')"""
                )
                if ok:
                    page.evaluate(CORE)
                    ready = page.evaluate("() => !!(window.__D11SV && window.__D11SV.runBatch)")
                    if ready:
                        return
                page.wait_for_timeout(400)
            last_err = RuntimeError("boot timeout waiting for Engine/__D11")
        except Exception as e:
            last_err = e
        page.wait_for_timeout(1000 * (attempt + 1))
    raise RuntimeError(f"boot failed after {retries}: {last_err}")


def load_prev() -> dict[str, dict]:
    if DOCS_SCEN.exists():
        return {r["id"]: r for r in json.loads(DOCS_SCEN.read_text(encoding="utf-8"))}
    return {}


def merge_credits(parts: list[dict]) -> dict:
    """Merge exported credit dicts: weighted mean, max p90 approx via larger n wins + mean p90."""
    out: dict[str, dict[str, dict]] = {}
    for part in parts:
        for eid, ch in part.items():
            if eid not in out:
                out[eid] = {}
            for k, b in ch.items():
                if k not in out[eid]:
                    out[eid][k] = {
                        "n": int(b["n"]),
                        "sum": float(b.get("sum", b["mean"] * b["n"])),
                        "p90s": [float(b["p90"])],
                        "ns": [int(b["n"])],
                    }
                else:
                    o = out[eid][k]
                    o["n"] += int(b["n"])
                    o["sum"] += float(b.get("sum", b["mean"] * b["n"]))
                    o["p90s"].append(float(b["p90"]))
                    o["ns"].append(int(b["n"]))
    compact = {}
    for eid, ch in out.items():
        compact[eid] = {}
        for k, o in ch.items():
            n = o["n"]
            # weighted average of worker P90s
            wsum = sum(p * n_ for p, n_ in zip(o["p90s"], o["ns"]))
            wn = sum(o["ns"]) or 1
            compact[eid][k] = {
                "n": n,
                "mean": o["sum"] / n if n else 0.0,
                "p90": wsum / wn,
                "sum": o["sum"],
            }
    return compact


def scores_from_credit(credit: dict, catalog, metric: str) -> dict[str, list[float]]:
    """metric in mean|p90|rate (rate uses mean of 0/1)."""
    soft = {}
    for ev in catalog:
        eid = ev["id"]
        n = len(ev["labels"])
        by = credit.get(eid, {})
        row = []
        for i in range(n):
            b = by.get(str(i)) or by.get(i)
            if not b or b["n"] < 1:
                row.append(0.0)
            elif metric == "p90":
                row.append(float(b["p90"]))
            else:
                row.append(float(b["mean"]))
        soft[eid] = row
    return soft


def aggregate_specialist(
    catalog,
    credit: dict,
    prev: dict,
    goal: str,
    metric: str,
    min_n: int = 24,
    min_gap: float = 0.02,
):
    """Build scenarios + policy for one specialist."""
    policy = {}
    scenarios = []
    stats = {"labeled": 0, "kept_prev": 0, "flips": 0}
    soft = scores_from_credit(credit, catalog, metric)

    for ev in catalog:
        eid = ev["id"]
        labels = ev["labels"]
        n = len(labels)
        by = credit.get(eid, {})
        counts = []
        objs = []
        for i in range(n):
            b = by.get(str(i)) or by.get(i)
            c = int(b["n"]) if b else 0
            counts.append(c)
            if c >= max(8, min_n // 3) and b:
                objs.append(float(b["p90"] if metric == "p90" else b["mean"]))
            else:
                objs.append(None)

        covered = all(c >= min_n for c in counts) and all(o is not None for o in objs)
        prev_row = prev.get(eid)
        prev_i = int(prev_row["best_i"]) % n if prev_row else 0

        if covered:
            objs_f = [float(o) for o in objs]
            best_i = int(np.argmax(objs_f))
            ordered = sorted(objs_f, reverse=True)
            gap = ordered[0] - ordered[1] if len(ordered) > 1 else 99.0
            # scale gap for rate metrics (0-1) vs trophy (~0-20)
            gap_ok = gap >= min_gap
            if not gap_ok:
                best_i = prev_i
                goal_tag = f"{goal}_tie_keep"
                stats["kept_prev"] += 1
            else:
                goal_tag = goal
                stats["labeled"] += 1
                if best_i != prev_i:
                    stats["flips"] += 1
            raw = objs_f
        else:
            best_i = prev_i
            goal_tag = f"{goal}_undersampled"
            stats["kept_prev"] += 1
            raw = soft.get(eid) or ([1.0] * n)
            if len(raw) != n:
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
        row = {
            "id": eid,
            "cat": ev.get("cat") or (prev_row or {}).get("cat"),
            "prompt": prompt,
            "choices": labels,
            "best_i": best_i,
            "raw_scores": [float(x) for x in raw],
            "qualities": quals,
            "label_goal": goal_tag,
            "counts": counts,
        }
        if goal == "trophy":
            row["trophy_p90"] = [round(float(x), 2) for x in raw]
        if goal == "top":
            row["top_mondial_pct"] = [round(100.0 * float(x), 1) for x in raw]
        if goal == "immediate":
            row["immediate_mean"] = [round(float(x), 3) for x in raw]
        scenarios.append(row)

    return policy, scenarios, stats, soft


def soft_vote_policy(catalog, soft_trophy, soft_imm, soft_top, prev):
    """Equal-weight soft vote of normalized specialist scores."""
    policy = {}
    soft_sv = {}
    scenarios = []
    stats = {"labeled": 0, "kept_prev": 0, "flips": 0}

    def norm(arr):
        a = np.asarray(arr, dtype=float)
        lo, hi = float(np.min(a)), float(np.max(a))
        if abs(hi - lo) < 1e-12:
            return np.full_like(a, 0.5)
        return (a - lo) / (hi - lo)

    for ev in catalog:
        eid = ev["id"]
        labels = ev["labels"]
        n = len(labels)
        parts = []
        for soft in (soft_trophy, soft_imm, soft_top):
            row = soft.get(eid)
            if row and len(row) == n:
                parts.append(norm(row))
        if parts:
            avg = np.mean(np.stack(parts, axis=0), axis=0)
            best_i = int(np.argmax(avg))
            raw = [float(x) for x in avg]
            goal_tag = "softvote"
            stats["labeled"] += 1
        else:
            prev_row = prev.get(eid)
            best_i = int(prev_row["best_i"]) % n if prev_row else 0
            raw = [0.3] * n
            raw[best_i] = 1.0
            goal_tag = "softvote_fallback"
            stats["kept_prev"] += 1

        prev_row = prev.get(eid)
        prev_i = int(prev_row["best_i"]) % n if prev_row else 0
        if best_i != prev_i and goal_tag == "softvote":
            stats["flips"] += 1

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
        soft_sv[eid] = raw
        scenarios.append(
            {
                "id": eid,
                "cat": ev.get("cat") or (prev_row or {}).get("cat"),
                "prompt": prompt,
                "choices": labels,
                "best_i": best_i,
                "raw_scores": raw,
                "qualities": quals,
                "label_goal": goal_tag,
                "softvote_scores": [round(float(x), 4) for x in raw],
                "trophy_p90": soft_trophy.get(eid),
                "immediate_mean": soft_imm.get(eid),
                "top_mondial_pct": [
                    round(100.0 * float(x), 1) for x in soft_top.get(eid, [0] * n)
                ]
                if soft_top.get(eid)
                else None,
            }
        )
    return policy, scenarios, stats, soft_sv


def write_model(name: str, scenarios: list, soft: dict, meta: dict):
    MODELS.mkdir(parents=True, exist_ok=True)
    path = MODELS / f"{name}.json"
    payload = {
        "name": name,
        "meta": meta,
        "soft_scores": soft,
        "scenarios": scenarios,
        "oracle": {s["id"]: s["best_i"] for s in scenarios},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def write_live_scenarios(scenarios: list, label_goal: str = "softvote_ensemble"):
    DATA.mkdir(parents=True, exist_ok=True)
    SCENARIOS.write_text(
        "\n".join(json.dumps(s, ensure_ascii=False) for s in scenarios) + "\n",
        encoding="utf-8",
    )
    docs = []
    for s in scenarios:
        d = {
            k: s[k]
            for k in (
                "id",
                "cat",
                "prompt",
                "choices",
                "best_i",
                "raw_scores",
                "qualities",
                "trophy_p90",
                "immediate_mean",
                "top_mondial_pct",
                "softvote_scores",
            )
            if k in s and s[k] is not None
        }
        d["label_goal"] = label_goal
        d["reward"] = "softvote_ensemble"
        docs.append(d)
    DOCS_SCEN.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def _mode_for_index(schedule, n_careers: int, idx: int) -> tuple[str, float]:
    """Return (mode, eps) for career index idx given fractional schedule."""
    assigned = 0
    cuts = []
    for mode, eps, frac in schedule[:-1]:
        n = int(n_careers * frac)
        cuts.append((mode, eps, assigned, assigned + n))
        assigned += n
    last = schedule[-1]
    cuts.append((last[0], last[1], assigned, n_careers))
    for mode, eps, a, b in cuts:
        if a <= idx < b:
            return mode, float(eps)
    mode, eps, _, _ = cuts[-1]
    return mode, float(eps)


def worker_sample(args: dict) -> dict:
    """One Playwright worker with periodic checkpoint + browser reboot."""
    worker_id = args["worker_id"]
    n_careers = args["n_careers"]
    seed0 = args["seed0"]
    goal = args["goal"]
    batch = args["batch"]
    schedule = args["schedule"]
    oracle = args.get("oracle") or {}
    soft_maps = args.get("soft_maps")
    ckpt_dir = Path(args["ckpt_dir"])
    reboot_every = int(args.get("reboot_every", 20_000))
    t0 = time.time()
    export_goal = "blend" if goal == "blend" else goal
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # Resume: count existing checkpoint careers for this worker/goal
    done = 0
    credit_parts: list[dict] = []
    for p in sorted(ckpt_dir.glob(f"{goal}_w{worker_id}_*.json")):
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
            credit_parts.append(blob["credit"])
            done = max(done, int(blob.get("done_end", 0)))
        except Exception:
            pass

    sum_t = 0.0
    sum_top = 0.0
    n_dec = 0
    part_i = len(credit_parts)

    def open_browser(pw):
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        page.set_default_timeout(0)
        page.evaluate("() => window.__D11SV.resetCredits()")
        if soft_maps:
            page.evaluate("(m) => window.__D11SV.setSoftMaps(m)", soft_maps)
        return browser, page

    with sync_playwright() as p:
        browser, page = open_browser(p)
        since_reboot = 0
        while done < n_careers:
            take = min(batch, n_careers - done)
            mode, eps = _mode_for_index(schedule, n_careers, done)
            seeds = [seed0 + done + i for i in range(take)]
            use_oracle = oracle if mode in ("oracle", "softvote") else {}
            try:
                part = page.evaluate(
                    """({seeds, mode, oracle, eps, goal}) =>
                        window.__D11SV.runBatch(seeds, mode, oracle, eps, goal)""",
                    {
                        "seeds": seeds,
                        "mode": mode,
                        "oracle": use_oracle,
                        "eps": float(eps),
                        "goal": goal,
                    },
                )
            except Exception as e:
                print(f"  [w{worker_id}] evaluate fail at {done}: {e}; reboot", flush=True)
                try:
                    browser.close()
                except Exception:
                    pass
                time.sleep(2)
                browser, page = open_browser(p)
                since_reboot = 0
                continue

            sum_t += part["meanT"] * part["n"]
            sum_top += part["topRate"] * part["n"]
            n_dec += part["nDec"]
            done += take
            since_reboot += take

            if worker_id == 0 and (done % 5000 < batch or done >= n_careers):
                print(
                    f"  [w0] {goal} careers={done}/{n_careers} "
                    f"meanT={sum_t/max(done,1):.2f} top={sum_top/max(done,1):.3f} "
                    f"dec={n_dec} t={time.time()-t0:.0f}s",
                    flush=True,
                )

            if since_reboot >= reboot_every or done >= n_careers:
                try:
                    chunk = page.evaluate("(g) => window.__D11SV.exportCredits(g)", export_goal)
                    page.evaluate("() => window.__D11SV.resetCredits()")
                except Exception as e:
                    print(f"  [w{worker_id}] export fail: {e}; reboot keep going", flush=True)
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser, page = open_browser(p)
                    since_reboot = 0
                    continue

                ckpt_path = ckpt_dir / f"{goal}_w{worker_id}_{part_i:04d}.json"
                ckpt_path.write_text(
                    json.dumps(
                        {"done_end": done, "credit": chunk, "n_dec": part.get("nDec", 0)},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                credit_parts.append(chunk)
                part_i += 1
                since_reboot = 0
                if done < n_careers:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser, page = open_browser(p)

        try:
            browser.close()
        except Exception:
            pass

    credit = merge_credits(credit_parts) if credit_parts else {}
    return {
        "worker_id": worker_id,
        "n_careers": done,
        "n_dec": n_dec,
        "mean_t": sum_t / max(done, 1),
        "top_rate": sum_top / max(done, 1),
        "credit": credit,
        "elapsed": time.time() - t0,
    }


def sample_phase(
    name: str,
    goal: str,
    n_careers: int,
    workers: int,
    batch: int,
    seed_base: int,
    oracle: dict | None = None,
    soft_maps: dict | None = None,
    schedule=None,
    ckpt_root: Path | None = None,
) -> dict:
    if schedule is None:
        schedule = [
            ("random", 1.0, 0.40),
            ("oracle", 0.45, 0.25),
            ("always0", 0.35, 0.15),
            ("netImpact", 0.40, 0.20),
        ]
    if goal == "blend":
        schedule = [
            ("softvote", 0.35, 0.45),
            ("random", 1.0, 0.30),
            ("oracle", 0.40, 0.15),
            ("netImpact", 0.35, 0.10),
        ]

    ckpt_dir = (ckpt_root or (DATA / "sv_ckpt")) / goal
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    per = n_careers // workers
    rem = n_careers - per * workers
    jobs = []
    for w in range(workers):
        n_w = per + (rem if w == workers - 1 else 0)
        jobs.append(
            {
                "worker_id": w,
                "n_careers": n_w,
                "seed0": seed_base + w * (n_careers + 10_000),
                "goal": goal,
                "batch": batch,
                "schedule": schedule,
                "oracle": oracle or {},
                "soft_maps": soft_maps,
                "ckpt_dir": str(ckpt_dir),
                "reboot_every": 15_000,
            }
        )

    print(
        f"\n===== PHASE {name} goal={goal} careers={n_careers} workers={workers} =====",
        flush=True,
    )
    t0 = time.time()
    parts = []
    # Stagger parallel boots so destinyeleven.com is less likely to flake
    if workers <= 1:
        for j in jobs:
            r = worker_sample(j)
            parts.append(r)
            print(
                f"  worker {r['worker_id']} done careers={r['n_careers']} "
                f"dec={r['n_dec']} t={r['elapsed']:.0f}s",
                flush=True,
            )
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = []
            for i, j in enumerate(jobs):
                time.sleep(1.5 * i)
                futs.append(ex.submit(worker_sample, j))
            for fut in as_completed(futs):
                r = fut.result()
                parts.append(r)
                print(
                    f"  worker {r['worker_id']} done careers={r['n_careers']} "
                    f"dec={r['n_dec']} t={r['elapsed']:.0f}s",
                    flush=True,
                )

    credit = merge_credits([p["credit"] for p in parts])
    total_n = sum(p["n_careers"] for p in parts)
    total_dec = sum(p["n_dec"] for p in parts)
    mean_t = sum(p["mean_t"] * p["n_careers"] for p in parts) / max(total_n, 1)
    top_rate = sum(p["top_rate"] * p["n_careers"] for p in parts) / max(total_n, 1)
    print(
        f"===== END {name}: careers={total_n} credits={total_dec} "
        f"meanT={mean_t:.2f} top={top_rate:.3f} elapsed={time.time()-t0:.0f}s =====",
        flush=True,
    )
    return {
        "n_careers": total_n,
        "n_dec": total_dec,
        "mean_t": mean_t,
        "top_rate": top_rate,
        "credit": credit,
        "elapsed": time.time() - t0,
    }


def bakeoff_oracles(page, oracles: dict[str, dict], n: int = 160) -> dict:
    seeds = [700_000 + i * 19 for i in range(n)]
    out = {}
    for name, oracle in oracles.items():
        if name == "random":
            st = page.evaluate(
                """({seeds}) => window.__D11SV.bakeStats(seeds, 'random', {})""",
                {"seeds": seeds},
            )
        elif name == "softvote_live":
            st = page.evaluate(
                """({seeds}) => window.__D11SV.bakeStats(seeds, 'softvote', {})""",
                {"seeds": seeds},
            )
        else:
            st = page.evaluate(
                """({seeds, oracle}) => window.__D11SV.bakeStats(seeds, 'oracle', oracle)""",
                {"seeds": seeds, "oracle": oracle},
            )
        out[name] = st
        print(
            f"bake {name:16s} meanT={st['meanTrophy']:.2f} p90T={st['p90Trophy']:.1f} "
            f"top={st['topRate']:.3f} p90S={st['p90Score']:.0f}",
            flush=True,
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1_000_000, help="careers per phase")
    ap.add_argument("--workers", type=int, default=None, help="parallel browsers (default 6, smoke 2)")
    ap.add_argument("--batch", type=int, default=400)
    ap.add_argument("--smoke", action="store_true", help="tiny run for validation")
    args = ap.parse_args()

    n = 2_000 if args.smoke else args.n
    if args.workers is None:
        workers = 2 if args.smoke else 6
    else:
        workers = max(1, args.workers)
    batch = 100 if args.smoke else args.batch

    t_all = time.time()
    prev = load_prev()
    if DOCS_SCEN.exists() and not BACKUP.exists():
        BACKUP.write_text(DOCS_SCEN.read_text(encoding="utf-8"), encoding="utf-8")
    prev_oracle = {k: int(v["best_i"]) for k, v in prev.items()}

    MODELS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    # catalog via one short boot
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        catalog = page.evaluate("() => window.__D11SV.eventCatalog()")
        browser.close()
    print(f"catalog={len(catalog)} prev={len(prev)} n={n} workers={workers}", flush=True)

    report: dict = {
        "n_per_phase": n,
        "workers": workers,
        "phases": {},
    }

    # ----- Phase A: trophies -----
    r_t = sample_phase(
        "A_trophy",
        "trophy",
        n,
        workers,
        batch,
        seed_base=10_000_000,
        oracle=prev_oracle,
    )
    pol_t, scen_t, st_t, soft_t = aggregate_specialist(
        catalog, r_t["credit"], prev, "trophy", "p90", min_n=20 if args.smoke else 40, min_gap=0.2
    )
    write_model(
        "trophy",
        scen_t,
        soft_t,
        {"stats": st_t, "n_careers": r_t["n_careers"], "n_dec": r_t["n_dec"], "metric": "p90_trophy"},
    )
    report["phases"]["trophy"] = {
        "n_careers": r_t["n_careers"],
        "n_dec": r_t["n_dec"],
        "aggregate": st_t,
        "elapsed": r_t["elapsed"],
    }
    print(f"trophy aggregate {st_t}", flush=True)

    # ----- Phase B: immediate -----
    r_i = sample_phase(
        "B_immediate",
        "immediate",
        n,
        workers,
        batch,
        seed_base=20_000_000,
        oracle=prev_oracle,
    )
    pol_i, scen_i, st_i, soft_i = aggregate_specialist(
        catalog,
        r_i["credit"],
        prev,
        "immediate",
        "mean",
        min_n=20 if args.smoke else 40,
        min_gap=0.05,
    )
    write_model(
        "immediate",
        scen_i,
        soft_i,
        {
            "stats": st_i,
            "n_careers": r_i["n_careers"],
            "n_dec": r_i["n_dec"],
            "metric": "mean_netImpact",
        },
    )
    report["phases"]["immediate"] = {
        "n_careers": r_i["n_careers"],
        "n_dec": r_i["n_dec"],
        "aggregate": st_i,
        "elapsed": r_i["elapsed"],
    }
    print(f"immediate aggregate {st_i}", flush=True)

    # ----- Phase C: top career -----
    r_c = sample_phase(
        "C_top",
        "top",
        n,
        workers,
        batch,
        seed_base=30_000_000,
        oracle=prev_oracle,
    )
    pol_c, scen_c, st_c, soft_c = aggregate_specialist(
        catalog,
        r_c["credit"],
        prev,
        "top",
        "mean",
        min_n=20 if args.smoke else 40,
        min_gap=0.005,
    )
    write_model(
        "top",
        scen_c,
        soft_c,
        {
            "stats": st_c,
            "n_careers": r_c["n_careers"],
            "n_dec": r_c["n_dec"],
            "metric": "top_rate",
            "score_min": SCORE_MIN,
        },
    )
    report["phases"]["top"] = {
        "n_careers": r_c["n_careers"],
        "n_dec": r_c["n_dec"],
        "aggregate": st_c,
        "elapsed": r_c["elapsed"],
    }
    print(f"top aggregate {st_c}", flush=True)

    # Soft maps for JS softvote policy
    soft_maps = {"trophy": soft_t, "immediate": soft_i, "top": soft_c}
    pol_sv0, scen_sv0, st_sv0, soft_sv0 = soft_vote_policy(
        catalog, soft_t, soft_i, soft_c, prev
    )
    write_model(
        "softvote_static",
        scen_sv0,
        soft_sv0,
        {"stats": st_sv0, "note": "equal-weight soft vote of 3 specialists (pre-distill)"},
    )

    # ----- Phase D: train soft-vote distill on blend reward -----
    r_b = sample_phase(
        "D_softvote",
        "blend",
        n,
        workers,
        batch,
        seed_base=40_000_000,
        oracle=pol_sv0,
        soft_maps=soft_maps,
    )
    pol_b, scen_b, st_b, soft_b = aggregate_specialist(
        catalog,
        r_b["credit"],
        {s["id"]: s for s in scen_sv0},
        "softvote_blend",
        "p90",
        min_n=20 if args.smoke else 40,
        min_gap=0.02,
    )
    # Enrich distilled rows with specialist views
    by_sv0 = {s["id"]: s for s in scen_sv0}
    for s in scen_b:
        eid = s["id"]
        base = by_sv0.get(eid, {})
        s["trophy_p90"] = soft_t.get(eid)
        s["immediate_mean"] = soft_i.get(eid)
        s["top_mondial_pct"] = base.get("top_mondial_pct")
        s["softvote_scores"] = soft_sv0.get(eid)
        # Ship score = blend of specialist soft vote (stable) averaged with distill raw
        if soft_sv0.get(eid) and s.get("raw_scores"):
            a = np.asarray(soft_sv0[eid], dtype=float)
            b = np.asarray(s["raw_scores"], dtype=float)
            # normalize each then average
            def _n(x):
                lo, hi = float(x.min()), float(x.max())
                if abs(hi - lo) < 1e-12:
                    return np.full_like(x, 0.5)
                return (x - lo) / (hi - lo)

            mix = 0.5 * _n(a) + 0.5 * _n(b)
            s["raw_scores"] = [float(x) for x in mix]
            s["best_i"] = int(np.argmax(mix))
            pol_b[eid] = s["best_i"]
            lo, hi = min(s["raw_scores"]), max(s["raw_scores"])
            s["qualities"] = [
                35.0 + 55.0 * ((v - lo) / (hi - lo + 1e-12)) for v in s["raw_scores"]
            ]
            s["qualities"][s["best_i"]] = max(s["qualities"][s["best_i"]], 93.0)
            s["label_goal"] = "softvote_ensemble"

    write_model(
        "softvote",
        scen_b,
        {s["id"]: s["raw_scores"] for s in scen_b},
        {
            "stats": st_b,
            "n_careers": r_b["n_careers"],
            "n_dec": r_b["n_dec"],
            "metric": "softvote_distill_blend",
        },
    )
    report["phases"]["softvote"] = {
        "n_careers": r_b["n_careers"],
        "n_dec": r_b["n_dec"],
        "aggregate": st_b,
        "elapsed": r_b["elapsed"],
        "static_softvote": st_sv0,
    }
    print(f"softvote distill aggregate {st_b}", flush=True)

    write_live_scenarios(scen_b, label_goal="softvote_ensemble")

    # Bakeoff
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        boot(page)
        page.set_default_timeout(0)
        page.evaluate("""(m) => window.__D11SV.setSoftMaps(m)""", soft_maps)
        bake_n = 80 if args.smoke else 200
        bake = bakeoff_oracles(
            page,
            {
                "random": {},
                "prev": prev_oracle,
                "trophy": pol_t,
                "immediate": pol_i,
                "top": pol_c,
                "softvote_static": pol_sv0,
                "softvote": pol_b,
                "softvote_live": pol_sv0,
            },
            n=bake_n,
        )
        browser.close()

    report["bakeoff"] = bake
    # Ship softvote if it beats prev on (topRate, p90Trophy, meanTrophy)
    ship_name = "softvote"
    ship_st = bake["softvote"]
    if bake["prev"]["topRate"] > ship_st["topRate"] + 0.01 and bake["prev"]["p90Trophy"] >= ship_st[
        "p90Trophy"
    ]:
        # keep softvote anyway as user requested ensemble ship; note in report
        report["ship_note"] = "softvote shipped by request; prev competitive on some metrics"
    report["shipped"] = ship_name
    report["elapsed_sec"] = round(time.time() - t_all, 1)

    if TREE.exists():
        model = json.loads(TREE.read_text(encoding="utf-8"))
        model["label_goal"] = "softvote_ensemble"
        model["reward"] = "softvote(trophy,immediate,top)+blend_distill"
        model["note"] = (
            "Ensemble soft-vote of 3 specialists (trophies P90, immediate netImpact, "
            "top-career %). Distilled on blended career reward. UI: Soft vote / Ensemble."
        )
        model["n_careers_sampled"] = n * 4
        model["specialists"] = {
            "trophy": report["phases"]["trophy"],
            "immediate": report["phases"]["immediate"],
            "top": report["phases"]["top"],
        }
        model["engine_softvote_bakeoff"] = {
            k: {
                "meanTrophy": v["meanTrophy"],
                "p90Trophy": v["p90Trophy"],
                "topRate": v["topRate"],
                "p90Score": v["p90Score"],
            }
            for k, v in bake.items()
        }
        TREE.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
        TREE_REPORT.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE shipped={ship_name} n={n}x4 elapsed={report['elapsed_sec']}s "
        f"report={REPORT}",
        flush=True,
    )


if __name__ == "__main__":
    main()
