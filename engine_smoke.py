"""Smoke test: real Engine career loop + one forced event."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

APPEND = r"""
;try{
  window.__D11 = {
    EVENTS, MICRO_EVENTS, ORIGINS, LIFESTYLES, POSITIONS, ENTOURAGES, NATIONALITIES,
    CLUBS: (typeof CLUBS !== 'undefined' ? CLUBS : null)
  };
}catch(e){ window.__D11Err = String(e); }
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

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
        for _ in range(50):
            st = page.evaluate(
                "() => !!(window.__D11 && window.__D11.CLUBS && window.__D11.CLUBS.length && typeof Engine!=='undefined')"
            )
            if st:
                break
            page.wait_for_timeout(400)
        else:
            raise RuntimeError("boot fail")

        info = page.evaluate(
            """() => {
          const pack = window.__D11, E = Engine;
          const setup = {
            name:'Smoke',
            nationality: pack.NATIONALITIES.find(x=>x.id==='fr')||pack.NATIONALITIES[0],
            origin: pack.ORIGINS.find(x=>x.id==='quartier')||pack.ORIGINS[0],
            position: pack.POSITIONS.find(x=>x.id==='att')||pack.POSITIONS[0],
            lifestyle: pack.LIFESTYLES.find(x=>x.id==='pro')||pack.LIFESTYLES[0],
            entourage: pack.ENTOURAGES.find(x=>/ambit/i.test((x.id||'')+(x.name||'')))||pack.ENTOURAGES[0],
            club: pack.CLUBS.find(c=>c.id==='fr_rennes')||pack.CLUBS.find(c=>c.level==='d1')||pack.CLUBS[0],
          };
          E.setSeed(1);
          const g = E.newCareer(setup);
          const ages=[];
          for (let i=0;i<6;i++){
            const a0=g.age, y0=g.year, m0=g.totals.matches;
            let season=null, serr=null, aerr=null;
            try { season = E.playSeason(g); } catch(e){ serr=String(e); }
            try { E.advanceYear(g); } catch(e){ aerr=String(e); }
            ages.push({i, a0, a1:g.age, y0, y1:g.year, m0, m1:g.totals.matches, score:E.computeCareerScore(g), ovr:E.ovr(g), serr, aerr, seasonAge: season&&season.age});
            if (g.careerEnded) break;
          }
          // force academy event if present
          E.setSeed(2);
          const g2 = E.newCareer(setup);
          const ev = pack.EVENTS.find(e=>e.id==='ev_all_in') || pack.EVENTS[0];
          const before = E.computeCareerScore(g2);
          const res = E.resolveOption(g2, ev.options[0]);
          const after = E.computeCareerScore(g2);
          return {ages, force:{id:ev.id, before, after, delta:after-before, resKeys:Object.keys(res||{}), ended:g2.careerEnded}};
        }"""
        )
        Path("data/engine_smoke.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=True, indent=2))
        browser.close()


if __name__ == "__main__":
    main()
