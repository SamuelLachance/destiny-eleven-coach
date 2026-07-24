"""Extract all Destiny Eleven EVENTS (+ options) via Playwright, then label & train."""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_RAW = Path("data/game_events_raw.json")
OUT_SCEN = Path("data/game_scenarios.jsonl")


EXTRACT_JS = """() => {
  // EVENTS lives in data.js scope; Engine closes over it. Recover via function source
  // or by scanning script globals after forcing reference through Engine.
  // Trick: temporarily patch and walk — better: eval data.js in isolated world? 
  // On the live site, look for exported bundle.
  const candidates = [];
  for (const k of Object.getOwnPropertyNames(window)) {
    try {
      const v = window[k];
      if (v && typeof v === 'object' && Array.isArray(v.EVENTS) && v.EVENTS.length > 10) {
        candidates.push(k);
      }
    } catch (e) {}
  }
  // Also check common names
  const names = ['DATA', 'GameData', 'DB', 'Content', 'DESTINY', 'D11', 'Raw', ...candidates];
  let pack = null;
  for (const n of names) {
    try {
      if (window[n] && Array.isArray(window[n].EVENTS)) { pack = window[n]; break; }
    } catch (e) {}
  }
  if (!pack) {
    // Last resort: Function constructor can't see closure. Return Engine hint.
    return { ok: false, reason: 'no EVENTS export', candidates, engine: typeof Engine !== 'undefined' };
  }
  const events = pack.EVENTS.map(ev => ({
    id: ev.id,
    cat: ev.cat,
    icon: ev.icon,
    w: ev.w,
    text: ev.text,
    cond: ev.cond || null,
    once: ev.once,
    options: (ev.options || []).map(o => ({
      text: o.text,
      tag: o.tag || null,
      fx: o.fx || null,
      cond: o.cond || null,
    })),
  }));
  const micro = (pack.MICRO_EVENTS || []).map(m => ({
    id: m.id, text: m.text, fx: m.fx || null, aMin: m.aMin, aMax: m.aMax, w: m.w,
  }));
  return { ok: true, nEvents: events.length, nMicro: micro.length, events, micro,
           origins: (pack.ORIGINS||[]).length, lifestyles: (pack.LIFESTYLES||[]).length };
}"""


def extract_via_injection() -> dict:
    """Load destinyeleven.com and inject a hook into data.js by re-fetching & wrapping."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Intercept data.js to append: window.__D11 = {EVENTS, MICRO_EVENTS, ...}
        def handle_route(route):
            url = route.request.url
            if "data.js" in url:
                resp = route.fetch()
                body = resp.text()
                # Append export of known consts at end (they exist in data.js scope)
                # data.js ends with an object literal referencing EVENTS — find and export
                appendix = (
                    "\n;try{window.__D11={"
                    "EVENTS:typeof EVENTS!=='undefined'?EVENTS:null,"
                    "MICRO_EVENTS:typeof MICRO_EVENTS!=='undefined'?MICRO_EVENTS:null,"
                    "ORIGINS:typeof ORIGINS!=='undefined'?ORIGINS:null,"
                    "LIFESTYLES:typeof LIFESTYLES!=='undefined'?LIFESTYLES:null,"
                    "POSITIONS:typeof POSITIONS!=='undefined'?POSITIONS:null,"
                    "ENTOURAGES:typeof ENTOURAGES!=='undefined'?ENTOURAGES:null,"
                    "NATIONALITIES:typeof NATIONALITIES!=='undefined'?NATIONALITIES:null,"
                    "};}catch(e){window.__D11Err=String(e);}\n"
                )
                route.fulfill(
                    status=resp.status,
                    headers={**resp.headers, "content-type": "application/javascript"},
                    body=body + appendix,
                )
            else:
                route.continue_()

        page.route("**/*", handle_route)
        page.goto("https://destinyeleven.com/", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(1500)
        data = page.evaluate(
            """() => {
              if (!window.__D11 || !window.__D11.EVENTS) {
                return { ok:false, err: window.__D11Err || 'missing', d11: window.__D11 };
              }
              const pack = window.__D11;
              const events = pack.EVENTS.map(ev => ({
                id: ev.id,
                cat: ev.cat || null,
                icon: ev.icon || null,
                w: ev.w,
                text: typeof ev.text === 'string' ? ev.text : String(ev.text),
                once: ev.once || false,
                cond: ev.cond || null,
                options: (ev.options || []).map(o => ({
                  text: typeof o.text === 'string' ? o.text : String(o.text),
                  tag: o.tag || null,
                  fx: o.fx || null,
                })),
              }));
              return {
                ok: true,
                nEvents: events.length,
                events,
                micro: (pack.MICRO_EVENTS||[]).map(m => ({id:m.id, text:m.text, fx:m.fx})),
                setup: {
                  origins: (pack.ORIGINS||[]).map(o => ({id:o.id, name:o.name, desc:o.desc})),
                  lifestyles: (pack.LIFESTYLES||[]).map(o => ({id:o.id, name:o.name, desc:o.desc})),
                  positions: (pack.POSITIONS||[]).map(o => ({id:o.id, name:o.name})),
                  entourages: (pack.ENTOURAGES||[]).map(o => ({id:o.id, name:o.name})),
                  nationalities: (pack.NATIONALITIES||[]).map(o => ({id:o.id, name:o.name})),
                }
              };
            }"""
        )
        browser.close()
        return data


def main():
    print("Extracting EVENTS from destinyeleven.com …")
    data = extract_via_injection()
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    OUT_RAW.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not data.get("ok"):
        print("FAILED", data)
        raise SystemExit(1)
    print(f"Events: {data['nEvents']} | micro: {len(data.get('micro') or [])}")
    opts = sum(len(e.get("options") or []) for e in data["events"])
    print(f"Total options: {opts}")
    with_opts = sum(1 for e in data["events"] if len(e.get("options") or []) >= 2)
    print(f"Events with >=2 options: {with_opts}")


if __name__ == "__main__":
    main()
