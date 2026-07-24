"""
Extrait TOUS les EVENTS Destiny Eleven + label chaque option
via l'esperance des fx (outcomes ponderees).

Puis genere data/choice_samples.jsonl pour train_model.py.
"""

from __future__ import annotations

import json
import math
import random
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

RAW = Path("data/game_events_raw.json")
SAMPLES = Path("data/choice_samples.jsonl")
SCENARIOS = Path("data/game_scenarios.jsonl")

# Poids approx. vers score carriere (alignés esprit Engine / notes finales)
FX_WEIGHTS = {
    "t": 1.2,  # technique
    "m": 1.0,  # mental
    "p": 0.9,  # physique
    "form": 0.8,
    "mor": 0.7,  # moral
    "rep": 1.1,
    "vis": 0.5,  # visibilite
    "chem": 0.4,
    "rel": 0.4,
    "sal": 0.15,
    "val": 0.1,
    "pot": 1.5,
    "ovr": 1.3,
    "inj": -1.4,  # jours blessure
    "fatigue": -0.6,
    "ego": -0.5,
    "stress": -0.5,
}

TRAIT_BONUS = {
    "loyal": 2,
    "pro": 3,
    "leader": 3,
    "clutch": 2,
    "worker": 2,
    "disciplined": 3,
    "media": 1,
}
TRAIT_MALUS = {
    "party": -3,
    "toxic": -4,
    "fragile": -2,
    "diva": -3,
}

CLUB_NAMES = [
    "Rennes", "Metz", "Lyon", "Lille", "Monaco", "Paris", "Marseille",
    "Padoue", "Bari", "Ajax", "Porto", "Naples", "ton club", "votre club",
]


def _fill_templates(text: str, club: str = "ton club") -> str:
    return (
        (text or "")
        .replace("{club}", club)
        .replace("{name}", "toi")
        .replace("{Club}", club)
    )


def expected_fx_score(option: dict) -> float:
    """Prefer game Engine.netImpact expectation; fallback to local weights.

    Important: le flag fx.retire donne un gros bonus court-terme dans le jeu,
    mais pour MAXIMISER la carriere on prefere souvent jouer encore une saison.
    On penalise donc les options qui declenchent retire s'il existe une alternative.
    """
    base = 0.0
    if option.get("expectedImpact") is not None:
        base = float(option["expectedImpact"])
    else:
        outcomes = option.get("outcomes") or []
        if not outcomes:
            return 0.0
        if outcomes and outcomes[0].get("impact") is not None:
            tw = sum(float(o.get("weight") or 1) for o in outcomes) or 1.0
            base = sum(
                float(o.get("weight") or 1) / tw * float(o.get("impact") or 0) for o in outcomes
            )
        else:
            total_w = sum(float(o.get("weight") or 1) for o in outcomes) or 1.0
            score = 0.0
            for o in outcomes:
                w = float(o.get("weight") or 1) / total_w
                fx = o.get("fx") or {}
                s = 0.0
                for k, v in fx.items():
                    if k == "trait":
                        t = str(v).lower()
                        s += TRAIT_BONUS.get(t, 0) + TRAIT_MALUS.get(t, 0)
                        continue
                    if isinstance(v, (int, float)):
                        s += FX_WEIGHTS.get(k, 0.3) * float(v)
                score += w * s
            base = score

    # penalite retraite (voir docstring)
    outcomes = option.get("outcomes") or []
    retire_w = 0.0
    tw = sum(float(o.get("weight") or 1) for o in outcomes) or 1.0
    for o in outcomes:
        fx = o.get("fx") or {}
        if fx.get("retire") is True or fx.get("retire") == 1:
            retire_w += float(o.get("weight") or 1) / tw
    label = (option.get("label") or "").lower()
    if retire_w > 0.2 or re.search(r"annoncer la retraite|prendre votre retraite|s'arrêter en héros|t'arrêter", label):
        base -= 18.0 * max(retire_w, 0.5)
    # bonus continuer / derniere danse
    if re.search(r"dernière danse|derniere danse|repousser|encore un an|encore une saison|battre pour|reconquérir|reconquerir", label):
        base += 8.0
    return base


def label_from_ev(ev_score: float, scores: list[float]) -> float:
    """Mappe le score relatif d'une option vers une qualité 20-95."""
    if not scores:
        return 55.0
    lo, hi = min(scores), max(scores)
    if abs(hi - lo) < 1e-6:
        return 70.0
    # 0..1
    t = (ev_score - lo) / (hi - lo)
    return 30.0 + 55.0 * t  # 30..85, best ~85


def extract() -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def handle_route(route):
            if "data.js" in route.request.url:
                resp = route.fetch()
                body = resp.text()
                appendix = (
                    "\n;try{window.__D11={EVENTS,MICRO_EVENTS,ORIGINS,LIFESTYLES,"
                    "POSITIONS,ENTOURAGES,NATIONALITIES};}"
                    "catch(e){window.__D11Err=String(e);}\n"
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
        page.wait_for_timeout(800)
        data = page.evaluate(
            """() => {
          if (!window.__D11 || !window.__D11.EVENTS) {
            return {ok:false, err: window.__D11Err || 'missing'};
          }
          const pack = window.__D11;
          const impact = (fx) => {
            try { return Engine.netImpact(fx || {}); } catch (e) { return 0; }
          };
          const events = pack.EVENTS.map(ev => ({
            id: ev.id,
            cat: ev.cat || null,
            icon: ev.icon || null,
            w: ev.w,
            text: String(ev.text || ''),
            once: !!ev.once,
            cond: ev.cond || null,
            options: (ev.options || []).map(o => {
              const outcomes = (o.outcomes || []).map(oc => ({
                weight: oc.weight,
                text: String(oc.text || ''),
                fx: oc.fx || {},
                impact: impact(oc.fx || {}),
              }));
              const tw = outcomes.reduce((s, oc) => s + (oc.weight || 1), 0) || 1;
              const expected = outcomes.reduce((s, oc) => s + ((oc.weight || 1) / tw) * (oc.impact || 0), 0);
              return {
                label: String(o.label || o.text || ''),
                hint: o.hint || null,
                tag: o.tag || null,
                expectedImpact: expected,
                outcomes,
              };
            }),
          }));
          const setup = {
            origins: (pack.ORIGINS||[]).map(o => ({name:o.name, desc:o.desc||''})),
            lifestyles: (pack.LIFESTYLES||[]).map(o => ({name:o.name, desc:o.desc||''})),
            positions: (pack.POSITIONS||[]).map(o => ({name:o.name})),
            entourages: (pack.ENTOURAGES||[]).map(o => ({name:o.name, desc:o.desc||''})),
            nationalities: (pack.NATIONALITIES||[]).map(o => ({name:o.name})),
          };
          return {ok:true, nEvents: events.length, events, setup,
                  micro:(pack.MICRO_EVENTS||[]).map(m=>({id:m.id,text:String(m.text||''),fx:m.fx||{}, impact: impact(m.fx||{})}))};
        }"""
        )
        browser.close()
        return data


def build_samples(data: dict, rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    scenarios_out = []

    for ev in data["events"]:
        opts = [o for o in (ev.get("options") or []) if (o.get("label") or "").strip()]
        if len(opts) < 2:
            continue
        prompt_tmpl = ev.get("text") or ""
        opts = [o for o in (ev.get("options") or []) if (o.get("label") or "").strip()]
        if len(opts) < 2:
            continue

        labels = []
        for o in opts:
            lab = o["label"]
            if o.get("hint"):
                lab = f"{o['hint']}: {lab}"
            if o.get("tag"):
                lab = f"{o['tag']}: {lab}"
            labels.append(lab)

        # scores impacts (independants du club)
        raw_scores = [expected_fx_score(o) for o in opts]
        prompt0 = _fill_templates(prompt_tmpl, "ton club")
        if max(raw_scores) - min(raw_scores) < 0.75:
            try:
                from advisor import _score_choice

                raw_scores = [
                    rs + 0.15 * _score_choice(lab, prompt0)
                    for rs, lab in zip(raw_scores, labels)
                ]
            except Exception:
                pass
        best_i = int(max(range(len(raw_scores)), key=lambda i: raw_scores[i]))
        qualities = [label_from_ev(s, raw_scores) for s in raw_scores]
        qualities[best_i] = max(qualities[best_i], 88.0)
        for i in range(len(qualities)):
            if i != best_i:
                qualities[i] = min(qualities[i], 55.0)

        # plusieurs realizations de {club} pour matcher le jeu live
        club_pool = [c for c in CLUB_NAMES if c not in ("ton club", "votre club")]
        club_variants = ["ton club"] + rng.sample(club_pool, k=min(4, len(club_pool)))
        for club in club_variants:
            prompt = _fill_templates(prompt_tmpl, club)
            if club == "ton club":
                scenarios_out.append(
                    {
                        "id": ev.get("id"),
                        "cat": ev.get("cat"),
                        "prompt": prompt,
                        "choices": labels,
                        "best_i": best_i,
                        "raw_scores": raw_scores,
                        "qualities": qualities,
                    }
                )
            for i, lab in enumerate(labels):
                rows.append(
                    {
                        "prompt": prompt,
                        "choice": lab,
                        "label": qualities[i],
                        "is_best": i == best_i,
                        "choices": labels,
                        "source": "game_event",
                        "event_id": ev.get("id"),
                        "cat": ev.get("cat"),
                    }
                )
                if club == "ton club":
                    for _ in range(2):
                        p2 = prompt.replace("é", "e") if rng.random() < 0.5 else prompt
                        c2 = lab.replace("é", "e") if rng.random() < 0.5 else lab
                        rows.append(
                            {
                                "prompt": p2,
                                "choice": c2,
                                "label": qualities[i] + rng.uniform(-1.0, 1.0),
                                "is_best": i == best_i,
                                "choices": labels,
                                "source": "game_aug",
                                "event_id": ev.get("id"),
                            }
                        )

    # Setup screens (prefs coach)
    setup = data.get("setup") or {}
    setup_pref = [
        (
            "D'où venez-vous ? Origine.",
            [o["name"] for o in setup.get("origins") or []],
            "Quartier populaire",
        ),
        (
            "Votre adolescence / mode de vie.",
            [o["name"] for o in setup.get("lifestyles") or []],
            "Hygiène de pro",
        ),
        (
            "Qui gère vos intérêts / entourage.",
            [o["name"] for o in setup.get("entourages") or []],
            "Agent ambitieux",
        ),
        (
            "Quel poste jouez-vous ?",
            [o["name"] for o in setup.get("positions") or []],
            "Attaquant",
        ),
    ]
    for prompt, choices, prefer in setup_pref:
        choices = [c for c in choices if c]
        if len(choices) < 2:
            continue
        best_i = next((i for i, c in enumerate(choices) if prefer.lower() in c.lower()), 0)
        for i, ch in enumerate(choices):
            lab = 85.0 if i == best_i else 45.0
            rows.append(
                {
                    "prompt": prompt,
                    "choice": ch,
                    "label": lab,
                    "is_best": i == best_i,
                    "choices": choices,
                    "source": "setup",
                }
            )

    # garder aussi nos scenarios manuels (bonus)
    try:
        from bootstrap_data import SCENARIOS as BOOT
        from expand_and_train import EXTRA

        for prompt, choices, best_i, good, bad in list(BOOT) + list(EXTRA):
            for i, ch in enumerate(choices):
                lab = float(good if i == best_i else bad)
                rows.append(
                    {
                        "prompt": prompt,
                        "choice": ch,
                        "label": lab,
                        "is_best": i == best_i,
                        "choices": choices,
                        "source": "manual",
                    }
                )
    except Exception:
        pass

    return rows, scenarios_out


def main():
    print("1) Extraction EVENTS du jeu…")
    data = extract()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not data.get("ok"):
        raise SystemExit(f"extract failed: {data}")
    print(f"   events={data['nEvents']}")

    print("2) Labelling via esperance fx…")
    rng = random.Random(42)
    rows, scenarios = build_samples(data, rng)
    with SCENARIOS.open("w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with SAMPLES.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_best = sum(1 for r in rows if r["is_best"])
    print(f"   scenarios jeu: {len(scenarios)}")
    print(f"   samples: {len(rows)} (best={n_best})")
    print(f"   -> {SAMPLES}")


if __name__ == "__main__":
    main()
