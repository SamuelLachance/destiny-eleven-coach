"""Quick probe of career start flow."""
import time
from playwright.sync_api import sync_playwright
from advisor import clean_choices

_EXTRACT = open("collect_games.py", encoding="utf-8").read().split("_EXTRACT = r\"\"\"")[1].split("\"\"\"")[0]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 420, "height": 900}, locale="fr-FR").new_page()
    page.goto("https://destinyeleven.com/", wait_until="domcontentloaded")
    time.sleep(1.5)
    try:
        page.locator("button:visible").filter(has_text="Accepter").first.click(timeout=2000)
    except Exception:
        pass
    time.sleep(0.4)
    page.locator("#btn-start").click(force=True)
    time.sleep(1)
    lines = []
    for i in range(15):
        st = page.evaluate(_EXTRACT)
        choices = clean_choices(st.get("choices") or [])
        body = (st.get("body") or "")[:300].replace("\n", " ")
        lines.append(f"STEP {i} choices={choices[:5]} body={body}")
        # click first useful
        prefs = ["France", "Attaquant", "Quartier populaire", "Hygiène de pro", "Agent ambitieux", "Rennes", "Metz"]
        clicked = False
        for pref in prefs:
            loc = page.locator("button:visible, .btn:visible").filter(has_text=pref)
            if loc.count():
                loc.first.click(force=True)
                lines.append(f"  clicked {pref}")
                clicked = True
                time.sleep(0.6)
                break
        if not clicked and choices:
            page.locator("button:visible").filter(has_text=choices[0]).first.click(force=True)
            lines.append(f"  clicked choice0 {choices[0][:40]}")
            time.sleep(0.6)
        elif not clicked:
            loc = page.locator("button:visible").filter(has_text="Continuer")
            if loc.count():
                loc.first.click(force=True)
                lines.append("  clicked Continuer")
                time.sleep(0.5)
    open("data/probe.txt", "w", encoding="utf-8").write("\n".join(lines))
    page.screenshot(path="data/probe.png")
    browser.close()
print("wrote data/probe.txt")
