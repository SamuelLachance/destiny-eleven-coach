"""Debug: ouvre le jeu, clique commencer, dump l'etat."""
import time
from playwright.sync_api import sync_playwright

JS = r"""() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && st.visibility !== 'hidden'
      && st.display !== 'none' && st.opacity !== '0';
  };
  const btns = [];
  document.querySelectorAll('button, .btn, [role="button"]').forEach(el => {
    if (!visible(el)) return;
    const t = norm(el.innerText);
    if (t) btns.push(t.slice(0, 80));
  });
  return {btns: btns.slice(0, 30), body: norm(document.body.innerText).slice(0, 1500)};
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 420, "height": 900}).new_page()
    page.goto("https://destinyeleven.com/", wait_until="domcontentloaded")
    time.sleep(2)
    for label in ["Accepter", "COMMENCER MA CARRIÈRE", "Commencer ma carrière", "France", "Attaquant"]:
        loc = page.locator("button, .btn").filter(has_text=label)
        if loc.count():
            try:
                loc.first.click(timeout=2000)
                print("clicked", label)
                time.sleep(0.8)
            except Exception as e:
                print("fail", label, e)
    st = page.evaluate(JS)
    print("BTNS:", st["btns"])
    print("BODY:", st["body"][:1200])
    page.screenshot(path="debug_screen.png")
    browser.close()
