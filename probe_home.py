import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": 420, "height": 900}, locale="fr-FR").new_page()
    page.goto("https://destinyeleven.com/", wait_until="networkidle")
    time.sleep(2)
    page.screenshot(path="data/home.png", full_page=True)
    info = page.evaluate(
        """() => {
      const btns = [...document.querySelectorAll('button, .btn, a, [role=button]')].map(el => ({
        id: el.id, cls: el.className, text: (el.innerText||'').trim().slice(0,60),
        vis: !!(el.offsetWidth || el.offsetHeight)
      }));
      return {title: document.title, n: btns.length, btns: btns.slice(0,40), html: document.body.innerHTML.slice(0,500)};
    }"""
    )
    open("data/home.json", "w", encoding="utf-8").write(str(info))
    # try click accepter then dump again
    for t in ["Accepter", "Refuser", "Commencer"]:
        loc = page.get_by_role("button", name=t)
        if loc.count():
            loc.first.click(timeout=3000)
            time.sleep(1)
    page.screenshot(path="data/home2.png", full_page=True)
    info2 = page.evaluate(
        """() => [...document.querySelectorAll('button')].map(el => (el.id||'')+':'+((el.innerText||'').trim().slice(0,40)))"""
    )
    open("data/home2.txt", "w", encoding="utf-8").write("\n".join(info2))
    browser.close()
print("ok")
