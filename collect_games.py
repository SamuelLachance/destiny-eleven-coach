"""
Collecte Destiny Eleven + labels score final.
Ecrit data/games.jsonl (UTF-8).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from advisor import advise, clean_choices

OUT = Path("data/games.jsonl")
LOG = Path("data/collect.log")

_EXTRACT = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && st.visibility !== 'hidden'
      && st.display !== 'none' && st.opacity !== '0';
  };
  const hasLetter = (s) => /[A-Za-zÀ-ÖØ-öø-ÿ]/.test(s || '');
  const promptCandidates = [];
  document.querySelectorAll('p, .text, [class*="desc"], [class*="event"], h1, h2, h3').forEach(el => {
    if (!visible(el)) return;
    const t = norm(el.innerText);
    if (t.length > 25 && t.length < 700) promptCandidates.push(t);
  });
  promptCandidates.sort((a,b) => b.length - a.length);
  const prompt = promptCandidates[0] || '';
  const skip = /continuer|retour|commencer|jouer maintenant|en voir plus|lancer|soutenir|cookies|accepter|mettre à jour|annuler|confirmer|boutique|badges|panthéon|pantheon|partager|ma fiche|défier|defier|rejouer|voir la carrière|statistiques|palmarès|parcours|distinctions|face à face/i;
  const choices = [];
  const seen = new Set();
  document.querySelectorAll('button, .btn, [role="button"]').forEach(el => {
    if (!visible(el)) return;
    const t = norm(el.innerText);
    if (!t || t.length > 180 || !hasLetter(t) || skip.test(t)) return;
    if (seen.has(t)) return;
    seen.add(t);
    choices.push(t);
  });
  const body = norm(document.body.innerText);
  let finalScore = null;
  const patterns = [
    /(\d{1,3})\s*\/\s*100/,
    /note[^0-9]{0,12}(\d{1,3})/i,
    /score[^0-9]{0,12}(\d{1,3})/i,
    /carrière[^0-9]{0,20}(\d{1,3})/i,
  ];
  for (const re of patterns) {
    const m = body.match(re);
    if (m) { finalScore = parseInt(m[1], 10); break; }
  }
  const retired = /carrière terminée|carriere terminee|rejouer une carrière|rejouer une carriere|carrière terminée|voir la carrière saison par saison/i.test(body);
  return {prompt, choices, finalScore, retired, body};
}"""


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat()} {msg}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    try:
        print(msg, flush=True)
    except Exception:
        pass


def click_visible(page, text: str) -> bool:
    loc = page.locator("button:visible, .btn:visible, [role='button']:visible").filter(has_text=text)
    try:
        n = loc.count()
        if not n:
            return False
        loc.first.click(timeout=2500, force=True)
        return True
    except Exception:
        return False


def click_any(page, labels: list[str]) -> str | None:
    for label in labels:
        if click_visible(page, label):
            return label
    return None


def start_career(page) -> None:
    page.goto("https://destinyeleven.com/", wait_until="domcontentloaded")
    time.sleep(1.5)
    click_any(page, ["Accepter", "Refuser"])
    time.sleep(0.5)
    # primary CTA
    try:
        page.locator("#btn-start").click(timeout=3000, force=True)
    except Exception:
        click_any(page, ["COMMENCER MA CARRIÈRE", "Commencer ma carrière", "Commencer"])
    time.sleep(0.8)

    setup = [
        "France",
        "Attaquant",
        "Quartier populaire",
        "Hygiène de pro",
        "Agent ambitieux",
        "Rennes",
        "Metz",
        "Lille",
        "Lyon",
    ]
    for _ in range(20):
        st = page.evaluate(_EXTRACT)
        if st.get("retired"):
            return
        choices = clean_choices(st.get("choices") or [])
        # still in setup if nationality/poste etc.
        body = (st.get("body") or "").lower()
        if any(k in body for k in ["votre nationalité", "votre poste", "votre origine", "adolescence", "entourage", "clubs vous"]):
            clicked = False
            for pref in setup:
                if click_visible(page, pref):
                    clicked = True
                    time.sleep(0.45)
                    break
            if not clicked and choices:
                click_visible(page, choices[0])
                time.sleep(0.45)
            continue
        if len(choices) >= 2:
            return
        if click_any(page, ["Continuer", "CONTINUER"]):
            time.sleep(0.4)
            continue
        time.sleep(0.3)


def play_one(page, policy: str) -> dict:
    decisions = []
    start_career(page)
    last_fp = ""
    same = 0

    for step in range(220):
        st = page.evaluate(_EXTRACT)
        body = st.get("body") or ""
        if st.get("retired") or (st.get("finalScore") is not None and "rejouer" in body.lower()):
            break

        choices = clean_choices(st.get("choices") or [])
        prompt = st.get("prompt") or ""
        fp = prompt[:80] + "|" + "|".join(choices[:6])

        if len(choices) >= 2:
            if fp == last_fp:
                same += 1
            else:
                same = 0
                last_fp = fp
            if same > 8:
                # stuck — click continuer or random
                if not click_any(page, ["Continuer", "CONTINUER"]):
                    click_visible(page, random.choice(choices))
                time.sleep(0.4)
                continue

            if policy == "random":
                pick = random.choice(choices)
                reason = "random"
            else:
                pick, reason = advise(prompt, choices)
                if not pick or pick not in choices:
                    pick = random.choice(choices)
                    reason = "fallback"

            decisions.append(
                {
                    "step": step,
                    "prompt": prompt[:500],
                    "choices": choices,
                    "chosen": pick,
                    "policy": policy,
                    "reason": reason,
                }
            )
            ok = click_visible(page, pick)
            if not ok:
                for ch in choices:
                    if pick[:16] in ch or ch[:16] in pick:
                        ok = click_visible(page, ch)
                        if ok:
                            break
            if not ok:
                click_visible(page, choices[0])
            time.sleep(0.5)
            continue

        if click_any(page, ["Continuer", "CONTINUER", "OK", "Suivant"]):
            time.sleep(0.4)
            continue

        # maybe end screen without detected retired
        if re.search(r"\b\d{1,3}\s*/\s*100\b", body) or "rejouer" in body.lower():
            break
        time.sleep(0.35)

    st = page.evaluate(_EXTRACT)
    score = st.get("finalScore")
    # last chance parse
    if score is None:
        m = re.search(r"(\d{1,3})\s*/\s*100", st.get("body") or "")
        if m:
            score = int(m.group(1))

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "policy": policy,
        "final_score": score,
        "n_decisions": len(decisions),
        "decisions": decisions,
        "retired": bool(st.get("retired")),
        "body_tail": (st.get("body") or "")[-400:],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--policy", choices=["heuristic", "random"], default="heuristic")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    log(f"Collecte {args.games} parties -> {OUT}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 420, "height": 900},
            locale="fr-FR",
        )
        page = context.new_page()
        for i in range(args.games):
            log(f"[{i+1}/{args.games}] playing...")
            try:
                game = play_one(page, args.policy)
            except Exception as e:
                log(f"  fail: {e}")
                continue
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(game, ensure_ascii=False) + "\n")
            log(
                f"  score={game.get('final_score')} decisions={game.get('n_decisions')} retired={game.get('retired')}"
            )
        browser.close()
    log("Done.")


if __name__ == "__main__":
    main()
