"""Scrape ALL Destiny Eleven event collections from live data.js via Playwright.

Exposes window.__D11 by appending to data.js (same pattern as engine_smoke / probes),
discovers every event-like array, and writes full + compact JSON for the coach.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT_FULL = ROOT / "data" / "game_events_full.json"
OUT_RAW = ROOT / "data" / "game_events_raw.json"
OUT_DOCS = ROOT / "docs" / "event_outcomes.json"
OUT_META = ROOT / "data" / "game_events_meta.json"

# Known + speculative identifiers in data.js scope (obfuscated file still uses these names).
KNOWN_EXPORTS = [
    "EVENTS",
    "MICRO_EVENTS",
    "STORY_EVENTS",
    "TWILIGHT_EVENTS",
    "SCHEDULED_EVENTS",
    "CAREER_EVENTS",
    "RANDOM_EVENTS",
    "SPECIAL_EVENTS",
    "LEGACY_EVENTS",
    "BONUS_EVENTS",
    "TUTORIAL_EVENTS",
    "INTRO_EVENTS",
    "ENDGAME_EVENTS",
    "ORIGIN_EVENTS",
    "CLUB_EVENTS",
    "MEDIA_EVENTS",
    "TRANSFER_EVENTS",
    "INJURY_EVENTS",
    "OFFSEASON_EVENTS",
    "WEEKLY_EVENTS",
    "MONTHLY_EVENTS",
    "YEARLY_EVENTS",
    "FLAVOR_EVENTS",
    "NARRATIVE_EVENTS",
    "QUEST_EVENTS",
    "CHAIN_EVENTS",
    "EVENT_POOLS",
    "EVENT_CHAINS",
    "DILEMMAS",
    "MICRO_DILEMMAS",
    "ORIGINS",
    "LIFESTYLES",
    "POSITIONS",
    "ENTOURAGES",
    "NATIONALITIES",
    "CLUBS",
    "TRAJECTORIES",
    "BALANCE",
    "TRAITS",
    "TAGS",
]

APPEND = r"""
;try{
  const __names = %NAMES%;
  const __pack = {};
  const __avail = [];
  const __err = [];
  for (const n of __names) {
    try {
      // eslint-disable-next-line no-eval
      const v = (0, eval)(n);
      if (typeof v !== 'undefined') {
        __pack[n] = v;
        __avail.push(n);
      }
    } catch (e) {
      __err.push(n + ':' + String(e).slice(0, 80));
    }
  }
  // Also try common unlisted identifiers that look like EVENT arrays in this scope
  // by scanning local bindings is impossible; rely on known names + later source scan.
  window.__D11 = __pack;
  window.__D11Avail = __avail;
  window.__D11ErrList = __err;
}catch(e){ window.__D11Err = String(e); }
"""


DISCOVER_AND_EXTRACT = r"""
() => {
  const pack = window.__D11 || {};
  const avail = window.__D11Avail || Object.keys(pack);
  const err = window.__D11Err || null;
  const errList = window.__D11ErrList || [];

  function isPlainObject(x) {
    return x && typeof x === 'object' && !Array.isArray(x);
  }

  function looksLikeOutcome(o) {
    if (!isPlainObject(o)) return false;
    return ('fx' in o) || ('weight' in o) || ('w' in o) || ('chips' in o) || ('tone' in o) || ('text' in o);
  }

  function looksLikeOption(o) {
    if (!isPlainObject(o)) return false;
    if (Array.isArray(o.outcomes) || Array.isArray(o.results)) return true;
    if ('label' in o || 'hint' in o || 'tag' in o) return true;
    if (('text' in o) && (o.fx || o.outcomes || o.cond)) return true;
    return false;
  }

  function looksLikeDilemmaEvent(e) {
    // Main EVENTS: id + text/prompt + options[]
    if (!isPlainObject(e)) return false;
    return !!(e.id && (e.text || e.prompt) && Array.isArray(e.options));
  }

  function looksLikeMicroEvent(e) {
    // MICRO_EVENTS: id + text + fx, no player options
    if (!isPlainObject(e)) return false;
    if (Array.isArray(e.options) && e.options.length) return false;
    if (e.name && e.desc && !e.text) return false; // lifestyles / origins / entourages
    if (e.label && e.desc && !e.text) return false; // trajectories
    return !!(e.id && e.text && e.fx);
  }

  function looksLikeEvent(e) {
    return looksLikeDilemmaEvent(e) || looksLikeMicroEvent(e);
  }

  const SETUP_NAMES = new Set([
    'ORIGINS','LIFESTYLES','POSITIONS','ENTOURAGES','NATIONALITIES','CLUBS',
    'TRAJECTORIES','BALANCE','TRAITS','TAGS'
  ]);
  const FORCE_EVENT_NAMES = new Set(['EVENTS','MICRO_EVENTS']);

  function serializeFx(fx) {
    if (fx == null) return null;
    if (typeof fx !== 'object') return fx;
    try { return JSON.parse(JSON.stringify(fx)); } catch (e) { return String(fx); }
  }

  function serializeOutcome(oc) {
    if (!oc || typeof oc !== 'object') return { raw: oc };
    return {
      weight: oc.weight != null ? oc.weight : (oc.w != null ? oc.w : null),
      w: oc.w != null ? oc.w : null,
      text: oc.text != null ? String(oc.text) : null,
      tone: oc.tone != null ? oc.tone : null,
      chips: oc.chips != null ? oc.chips : null,
      fx: serializeFx(oc.fx),
      cond: oc.cond != null ? oc.cond : null,
      // keep any extra keys that look useful
      extra: (() => {
        const skip = new Set(['weight','w','text','tone','chips','fx','cond']);
        const out = {};
        for (const k of Object.keys(oc)) {
          if (skip.has(k)) continue;
          try { out[k] = JSON.parse(JSON.stringify(oc[k])); } catch (e) { out[k] = String(oc[k]); }
        }
        return Object.keys(out).length ? out : null;
      })(),
    };
  }

  function serializeOption(o) {
    if (!o || typeof o !== 'object') return { raw: o };
    const outcomesSrc = o.outcomes || o.results || null;
    const outcomes = Array.isArray(outcomesSrc) ? outcomesSrc.map(serializeOutcome) : null;
    // Some options have direct fx (no outcomes array)
    const directFx = (!outcomes || !outcomes.length) ? serializeFx(o.fx) : null;
    return {
      label: o.label != null ? String(o.label) : (o.text != null ? String(o.text) : null),
      text: o.text != null ? String(o.text) : null,
      hint: o.hint != null ? String(o.hint) : null,
      tag: o.tag != null ? o.tag : null,
      tags: o.tags != null ? o.tags : null,
      cond: o.cond != null ? o.cond : null,
      w: o.w != null ? o.w : null,
      weight: o.weight != null ? o.weight : null,
      fx: directFx,
      outcomes: outcomes,
      extra: (() => {
        const skip = new Set(['label','text','hint','tag','tags','cond','w','weight','fx','outcomes','results']);
        const out = {};
        for (const k of Object.keys(o)) {
          if (skip.has(k)) continue;
          try { out[k] = JSON.parse(JSON.stringify(o[k])); } catch (e) { out[k] = String(o[k]); }
        }
        return Object.keys(out).length ? out : null;
      })(),
    };
  }

  function serializeEvent(ev) {
    if (!ev || typeof ev !== 'object') return { raw: ev };
    const opts = Array.isArray(ev.options) ? ev.options.map(serializeOption) : null;
    return {
      id: ev.id != null ? ev.id : null,
      cat: ev.cat != null ? ev.cat : (ev.category != null ? ev.category : null),
      icon: ev.icon != null ? ev.icon : null,
      text: ev.text != null ? String(ev.text) : (ev.prompt != null ? String(ev.prompt) : null),
      prompt: ev.prompt != null ? String(ev.prompt) : null,
      desc: ev.desc != null ? String(ev.desc) : null,
      cond: ev.cond != null ? ev.cond : null,
      w: ev.w != null ? ev.w : null,
      weight: ev.weight != null ? ev.weight : null,
      once: ev.once != null ? !!ev.once : null,
      scheduledOnly: ev.scheduledOnly != null ? !!ev.scheduledOnly : null,
      aMin: ev.aMin != null ? ev.aMin : null,
      aMax: ev.aMax != null ? ev.aMax : null,
      fx: serializeFx(ev.fx),
      options: opts,
      // preserve unknown top-level keys
      extra: (() => {
        const skip = new Set([
          'id','cat','category','icon','text','prompt','desc','cond','w','weight',
          'once','scheduledOnly','aMin','aMax','fx','options'
        ]);
        const out = {};
        for (const k of Object.keys(ev)) {
          if (skip.has(k)) continue;
          try { out[k] = JSON.parse(JSON.stringify(ev[k])); } catch (e) { out[k] = String(ev[k]); }
        }
        return Object.keys(out).length ? out : null;
      })(),
    };
  }

  function classifyArray(arr) {
    if (!Array.isArray(arr) || !arr.length) return { kind: 'empty_or_nonarray', n: Array.isArray(arr) ? arr.length : 0 };
    let eventish = 0, optionish = 0, outcomeish = 0, microish = 0, otherObj = 0;
    const sample = arr.slice(0, Math.min(arr.length, 8));
    for (const item of sample) {
      if (looksLikeEvent(item)) {
        eventish++;
        if (item.fx && !item.options) microish++;
      } else if (looksLikeOption(item)) optionish++;
      else if (looksLikeOutcome(item)) outcomeish++;
      else if (isPlainObject(item)) otherObj++;
    }
    let kind = 'other';
    if (eventish >= Math.ceil(sample.length * 0.5)) {
      kind = microish >= Math.ceil(sample.length * 0.5) && eventish === microish ? 'micro_events' : 'events';
    } else if (optionish >= Math.ceil(sample.length * 0.5)) kind = 'options';
    else if (outcomeish >= Math.ceil(sample.length * 0.5)) kind = 'outcomes';
    else if (otherObj) kind = 'objects';
    else kind = 'primitives';
    return { kind, n: arr.length, sampleKeys: sample.filter(isPlainObject).slice(0,3).map(o => Object.keys(o).slice(0,12)) };
  }

  // Inventory every exported key
  const inventory = {};
  for (const name of avail) {
    const v = pack[name];
    if (Array.isArray(v)) {
      inventory[name] = { type: 'array', ...classifyArray(v) };
    } else if (isPlainObject(v)) {
      // nested arrays?
      const nested = {};
      for (const [k, nv] of Object.entries(v)) {
        if (Array.isArray(nv)) nested[k] = classifyArray(nv);
      }
      inventory[name] = {
        type: 'object',
        keys: Object.keys(v).slice(0, 40),
        nestedArrays: nested,
      };
    } else {
      inventory[name] = { type: typeof v };
    }
  }

  // Also scan window for accidental globals that look like event packs
  const windowHits = [];
  for (const k of Object.getOwnPropertyNames(window)) {
    try {
      const v = window[k];
      if (!v || typeof v !== 'object') continue;
      if (Array.isArray(v) && v.length > 5 && looksLikeEvent(v[0])) {
        windowHits.push({ name: k, via: 'array', n: v.length });
      } else if (v.EVENTS && Array.isArray(v.EVENTS) && v.EVENTS.length > 10) {
        windowHits.push({ name: k, via: 'pack.EVENTS', n: v.EVENTS.length });
      }
    } catch (e) {}
  }

  // Extract all event-like collections from pack (not setup catalogues)
  const collections = {};
  function putCollection(name, arr, kindHint) {
    if (!Array.isArray(arr)) return;
    if (SETUP_NAMES.has(name.split('.')[0])) return;
    const cls = classifyArray(arr);
    let kind = kindHint || cls.kind;
    const force = FORCE_EVENT_NAMES.has(name) || /EVENT|DILEMMA/i.test(name);
    if (!force && kind !== 'events' && kind !== 'micro_events') return;
    // Require majority dilemma/micro shape unless forced known name
    if (!FORCE_EVENT_NAMES.has(name)) {
      const sample = arr.slice(0, Math.min(arr.length, 12));
      const ok = sample.filter(x => looksLikeDilemmaEvent(x) || looksLikeMicroEvent(x)).length;
      if (ok < Math.ceil(sample.length * 0.5)) return;
    }
    if (FORCE_EVENT_NAMES.has(name) && name === 'MICRO_EVENTS') kind = 'micro_events';
    if (FORCE_EVENT_NAMES.has(name) && name === 'EVENTS') kind = 'events';
    if (kind === 'other' || kind === 'objects' || kind === 'primitives') {
      kind = arr.some(looksLikeDilemmaEvent) ? 'events' : 'micro_events';
    }
    collections[name] = {
      kind,
      count: arr.length,
      items: arr.map(serializeEvent),
    };
  }

  for (const name of avail) {
    const v = pack[name];
    if (Array.isArray(v)) {
      putCollection(name, v, null);
    } else if (isPlainObject(v) && !SETUP_NAMES.has(name)) {
      for (const [k, nv] of Object.entries(v)) {
        if (Array.isArray(nv) && (k.includes('EVENT') || k.includes('event') || classifyArray(nv).kind.includes('event'))) {
          putCollection(name + '.' + k, nv, null);
        }
      }
    }
  }

  // Always include EVENTS / MICRO_EVENTS even if classifier is unsure
  if (Array.isArray(pack.EVENTS) && !collections.EVENTS) {
    collections.EVENTS = { kind: 'events', count: pack.EVENTS.length, items: pack.EVENTS.map(serializeEvent) };
  }
  if (Array.isArray(pack.MICRO_EVENTS) && !collections.MICRO_EVENTS) {
    collections.MICRO_EVENTS = { kind: 'micro_events', count: pack.MICRO_EVENTS.length, items: pack.MICRO_EVENTS.map(serializeEvent) };
  }

  // Setup catalogues (not dilemmas) — keep structured for reference
  const setup = {};
  function mapSetup(arr, mapper) {
    return Array.isArray(arr) ? arr.map(mapper) : null;
  }
  if (pack.ORIGINS) setup.origins = mapSetup(pack.ORIGINS, o => ({id:o.id,name:o.name,desc:o.desc,startStats:o.startStats||null}));
  if (pack.LIFESTYLES) setup.lifestyles = mapSetup(pack.LIFESTYLES, o => ({id:o.id,name:o.name,desc:o.desc,fx:serializeFx(o.fx),potBonus:o.potBonus||null,icon:o.icon||null}));
  if (pack.POSITIONS) setup.positions = mapSetup(pack.POSITIONS, o => ({id:o.id,name:o.name}));
  if (pack.ENTOURAGES) setup.entourages = mapSetup(pack.ENTOURAGES, o => ({id:o.id,name:o.name,desc:o.desc,fx:serializeFx(o.fx),academy:o.academy||null,flag:o.flag||null,icon:o.icon||null}));
  if (pack.NATIONALITIES) setup.nationalities = mapSetup(pack.NATIONALITIES, o => ({id:o.id,name:o.name}));
  if (pack.TRAJECTORIES) setup.trajectories = mapSetup(pack.TRAJECTORIES, o => ({id:o.id,w:o.w,label:o.label,desc:o.desc}));
  if (pack.TRAITS) {
    try { setup.traits = JSON.parse(JSON.stringify(pack.TRAITS)); } catch (e) { setup.traits = null; }
  }
  if (pack.BALANCE) {
    try { setup.balance = JSON.parse(JSON.stringify(pack.BALANCE)); } catch (e) { setup.balance = null; }
  }
  if (pack.CLUBS) setup.clubsCount = pack.CLUBS.length;

  // Counts
  const counts = {};
  let totalOptions = 0;
  let totalOutcomes = 0;
  for (const [name, col] of Object.entries(collections)) {
    let opts = 0, outs = 0;
    for (const ev of col.items || []) {
      const olist = ev.options || [];
      opts += olist.length;
      for (const o of olist) {
        outs += (o.outcomes || []).length;
        if ((!o.outcomes || !o.outcomes.length) && o.fx) outs += 1; // direct fx as implicit outcome
      }
      // micro: event-level fx
      if ((!olist || !olist.length) && ev.fx) outs += 1;
    }
    counts[name] = { events: (col.items || []).length, options: opts, outcomes: outs, kind: col.kind };
    totalOptions += opts;
    totalOutcomes += outs;
  }

  // Compact coach map: eventId -> options with outcomes (for bookmarklet / docs)
  // Duplicate ids (game has one) become arrays under that key.
  const compact = {};
  const dupIds = [];
  const main = collections.EVENTS;
  if (main) {
    for (const ev of main.items) {
      if (!ev.id) continue;
      const entry = {
        id: ev.id,
        cat: ev.cat,
        text: ev.text,
        cond: ev.cond,
        w: ev.w,
        once: ev.once,
        scheduledOnly: ev.scheduledOnly,
        options: (ev.options || []).map(o => ({
          label: o.label,
          hint: o.hint,
          tag: o.tag,
          outcomes: (o.outcomes || []).map(oc => ({
            weight: oc.weight,
            text: oc.text,
            tone: oc.tone,
            chips: oc.chips,
            fx: oc.fx,
          })),
        })),
      };
      if (compact[ev.id]) {
        dupIds.push(ev.id);
        if (!Array.isArray(compact[ev.id])) compact[ev.id] = [compact[ev.id]];
        compact[ev.id].push(entry);
      } else {
        compact[ev.id] = entry;
      }
    }
  }

  const scheduledStory = (main && main.items || []).filter(e => e.scheduledOnly);

  // Sample first event keys for schema verification
  const schemaSample = {};
  if (pack.EVENTS && pack.EVENTS[0]) {
    const e0 = pack.EVENTS[0];
    schemaSample.eventKeys = Object.keys(e0);
    if (e0.options && e0.options[0]) {
      schemaSample.optionKeys = Object.keys(e0.options[0]);
      const oc0 = (e0.options[0].outcomes || [])[0];
      if (oc0) schemaSample.outcomeKeys = Object.keys(oc0);
    }
  }
  if (pack.MICRO_EVENTS && pack.MICRO_EVENTS[0]) {
    schemaSample.microKeys = Object.keys(pack.MICRO_EVENTS[0]);
  }

  return {
    ok: true,
    err,
    errList: errList.slice(0, 30),
    avail,
    inventory,
    windowHits,
    schemaSample,
    counts,
    totalOptions,
    totalOutcomes,
    collections,
    setup,
    compact,
    scheduledStoryCount: scheduledStory.length,
    scheduledStoryIds: scheduledStory.map(e => e.id),
    duplicateEventIds: dupIds,
    engine: typeof Engine !== 'undefined',
  };
}
"""


def build_appendix() -> str:
    names_json = json.dumps(KNOWN_EXPORTS)
    return APPEND.replace("%NAMES%", names_json)


def scrape() -> dict:
    appendix = build_appendix()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route):
            if "data.js" in route.request.url:
                resp = route.fetch()
                route.fulfill(
                    status=resp.status,
                    headers={**resp.headers, "content-type": "application/javascript"},
                    body=resp.text() + appendix,
                )
            else:
                route.continue_()

        page.route("**/*", handle_route)
        page.goto("https://destinyeleven.com/", wait_until="domcontentloaded", timeout=180000)
        for _ in range(60):
            ready = page.evaluate(
                "() => !!(window.__D11 && (window.__D11.EVENTS || window.__D11Avail))"
            )
            if ready:
                break
            page.wait_for_timeout(400)
        else:
            browser.close()
            return {"ok": False, "err": "boot timeout", "d11err": page.evaluate("() => window.__D11Err || null")}

        # Also scan data.js source text for *EVENTS* identifiers we might have missed
        data_js_url = page.evaluate(
            """() => {
              const s = [...document.scripts].map(x => x.src).find(u => u && u.includes('data.js'));
              return s || null;
            }"""
        )
        extra_names = []
        if data_js_url:
            # Re-fetch via page to reuse cookies / CDN
            src = page.evaluate(
                """async (url) => {
                  const r = await fetch(url);
                  return await r.text();
                }""",
                data_js_url,
            )
            # Find identifier-like EVENT tokens in source (not obfuscated string payloads)
            found = set(re.findall(r"\b([A-Z][A-Z0-9_]*(?:EVENT|EVENTS|DILEMMA|DILEMMAS)[A-Z0-9_]*)\b", src))
            # Also catch lowercase camelCase like storyEvents
            found |= set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Event|Events|Dilemma|Dilemmas)[A-Za-z0-9_]*)\b", src))
            extra_names = sorted(found - set(KNOWN_EXPORTS))

        if extra_names:
            # Re-inject with extras by evaluating in data.js scope is hard after load;
            # try eval of names on window / Function — they won't be on window.
            # Instead: append-style already ran; probe which extras resolve via Function constructor
            # in page — they won't. So store them for second pass with updated appendix.
            pass

        data = page.evaluate(DISCOVER_AND_EXTRACT)
        data["dataJsUrl"] = data_js_url
        data["extraNamesFromSource"] = extra_names
        browser.close()

        # Second pass if source revealed new identifiers
        if extra_names:
            data2 = scrape_with_names(KNOWN_EXPORTS + extra_names)
            if data2.get("ok"):
                # Merge any new collections
                for name, col in (data2.get("collections") or {}).items():
                    if name not in (data.get("collections") or {}):
                        data.setdefault("collections", {})[name] = col
                        data.setdefault("counts", {})[name] = data2["counts"].get(name)
                data["avail"] = sorted(set(data.get("avail") or []) | set(data2.get("avail") or []))
                data["extraResolved"] = [n for n in extra_names if n in (data2.get("avail") or [])]
                data["inventory"].update({k: v for k, v in (data2.get("inventory") or {}).items() if k not in data.get("inventory", {})})
                # Recompute totals
                to, tout = 0, 0
                for c in (data.get("counts") or {}).values():
                    to += c.get("options") or 0
                    tout += c.get("outcomes") or 0
                data["totalOptions"] = to
                data["totalOutcomes"] = tout
        return data


def scrape_with_names(names: list[str]) -> dict:
    names_json = json.dumps(names)
    appendix = APPEND.replace("%NAMES%", names_json)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route):
            if "data.js" in route.request.url:
                resp = route.fetch()
                route.fulfill(
                    status=resp.status,
                    headers={**resp.headers, "content-type": "application/javascript"},
                    body=resp.text() + appendix,
                )
            else:
                route.continue_()

        page.route("**/*", handle_route)
        page.goto("https://destinyeleven.com/", wait_until="domcontentloaded", timeout=180000)
        for _ in range(60):
            if page.evaluate("() => !!(window.__D11 && window.__D11.EVENTS)"):
                break
            page.wait_for_timeout(400)
        else:
            browser.close()
            return {"ok": False, "err": "boot timeout pass2"}
        data = page.evaluate(DISCOVER_AND_EXTRACT)
        browser.close()
        return data


def write_outputs(data: dict) -> dict:
    OUT_FULL.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOCS.parent.mkdir(parents=True, exist_ok=True)

    collections = data.get("collections") or {}
    counts = data.get("counts") or {}
    scraped_at = datetime.now(timezone.utc).isoformat()

    full = {
        "ok": data.get("ok"),
        "scrapedAt": scraped_at,
        "source": data.get("dataJsUrl"),
        "avail": data.get("avail"),
        "inventory": data.get("inventory"),
        "schemaSample": data.get("schemaSample"),
        "windowHits": data.get("windowHits"),
        "extraNamesFromSource": data.get("extraNamesFromSource"),
        "extraResolved": data.get("extraResolved"),
        "counts": counts,
        "totalOptions": data.get("totalOptions"),
        "totalOutcomes": data.get("totalOutcomes"),
        "scheduledStoryCount": data.get("scheduledStoryCount"),
        "scheduledStoryIds": data.get("scheduledStoryIds"),
        "duplicateEventIds": data.get("duplicateEventIds"),
        "collections": collections,
        "setup": data.get("setup"),
    }
    OUT_FULL.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")

    # Compatibility raw shape used by older trainers
    events = (collections.get("EVENTS") or {}).get("items") or []
    micro = (collections.get("MICRO_EVENTS") or {}).get("items") or []
    raw = {
        "ok": True,
        "nEvents": len(events),
        "events": events,
        "micro": micro,
        "counts": counts,
        "scrapedAt": scraped_at,
        "setup": data.get("setup"),
    }
    OUT_RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # Compact for Pages / bookmarklet — events as array (advisor.js expects list or map)
    events_list = []
    for ev in events:
        events_list.append(
            {
                "id": ev.get("id"),
                "cat": ev.get("cat"),
                "text": ev.get("text"),
                "cond": ev.get("cond"),
                "w": ev.get("w"),
                "once": ev.get("once"),
                "scheduledOnly": ev.get("scheduledOnly"),
                "options": [
                    {
                        "label": o.get("label"),
                        "hint": o.get("hint"),
                        "tag": o.get("tag"),
                        "outcomes": [
                            {
                                "weight": oc.get("weight"),
                                "text": oc.get("text"),
                                "tone": oc.get("tone"),
                                "chips": oc.get("chips"),
                                "fx": oc.get("fx"),
                            }
                            for oc in (o.get("outcomes") or [])
                        ],
                    }
                    for o in (ev.get("options") or [])
                ],
            }
        )
    compact = {
        "scrapedAt": scraped_at,
        "nEvents": len(events_list),
        "nUniqueIds": len({e.get("id") for e in events_list if e.get("id")}),
        "duplicateEventIds": data.get("duplicateEventIds") or [],
        "scheduledStoryIds": data.get("scheduledStoryIds") or [],
        "counts": counts,
        "events": events_list,
    }
    # Also include micro as a flat list (small)
    if micro:
        compact["micro"] = [
            {
                "id": m.get("id"),
                "text": m.get("text"),
                "w": m.get("w"),
                "aMin": m.get("aMin"),
                "aMax": m.get("aMax"),
                "fx": m.get("fx"),
                "cond": m.get("cond"),
            }
            for m in micro
        ]
    OUT_DOCS.write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    meta = {
        "scrapedAt": scraped_at,
        "paths": {
            "full": str(OUT_FULL.as_posix()),
            "raw": str(OUT_RAW.as_posix()),
            "docs": str(OUT_DOCS.as_posix()),
        },
        "counts": counts,
        "totalOptions": data.get("totalOptions"),
        "totalOutcomes": data.get("totalOutcomes"),
        "scheduledStoryCount": data.get("scheduledStoryCount"),
        "scheduledStoryIds": data.get("scheduledStoryIds"),
        "duplicateEventIds": data.get("duplicateEventIds"),
        "avail": data.get("avail"),
        "extraNamesFromSource": data.get("extraNamesFromSource"),
        "extraResolved": data.get("extraResolved"),
        "schemaSample": data.get("schemaSample"),
    }
    OUT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main():
    print("Scraping ALL events from destinyeleven.com …", flush=True)
    data = scrape()
    if not data.get("ok"):
        print("FAILED", json.dumps(data, ensure_ascii=True)[:2000])
        raise SystemExit(1)

    meta = write_outputs(data)
    print("\n=== Collection counts ===", flush=True)
    for name, c in sorted((meta.get("counts") or {}).items()):
        print(
            f"  {name}: {c.get('events')} events | {c.get('options')} options | "
            f"{c.get('outcomes')} outcomes  ({c.get('kind')})",
            flush=True,
        )
    n_events = (meta.get("counts") or {}).get("EVENTS", {}).get("events")
    print(f"\nTotal options (all collections): {meta.get('totalOptions')}", flush=True)
    print(f"Total outcomes (all collections): {meta.get('totalOutcomes')}", flush=True)
    print(f"Scheduled story events (scheduledOnly): {meta.get('scheduledStoryCount')}", flush=True)
    if meta.get("duplicateEventIds"):
        print(f"Duplicate event ids in EVENTS: {meta.get('duplicateEventIds')}", flush=True)
    print(f"Avail exports: {meta.get('avail')}", flush=True)
    if meta.get("extraNamesFromSource"):
        print(f"Extra EVENT* names in source: {meta.get('extraNamesFromSource')}", flush=True)
        print(f"Extra resolved on pass2: {meta.get('extraResolved')}", flush=True)
    print(f"Schema sample: {meta.get('schemaSample')}", flush=True)
    print(f"\nWrote:\n  {OUT_FULL}\n  {OUT_RAW}\n  {OUT_DOCS}\n  {OUT_META}", flush=True)

    # Sanity vs historical ~179 EVENTS
    if n_events is None:
        print("WARNING: EVENTS collection missing", flush=True)
    elif n_events < 170:
        print(f"WARNING: EVENTS count {n_events} << expected ~179 — possible incomplete scrape", flush=True)
    elif n_events < 179:
        print(f"NOTE: EVENTS count {n_events} slightly under previous ~179", flush=True)
    else:
        print(f"OK: EVENTS count {n_events} (>= previous ~179)", flush=True)


if __name__ == "__main__":
    main()
