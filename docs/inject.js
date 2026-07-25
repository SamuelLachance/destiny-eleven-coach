/**
 * Destiny Eleven Coach — overlay injecté sur destinyeleven.com
 * Chargé via bookmarklet depuis GitHub Pages.
 */
(function () {
  if (window.__D11CoachInjected) {
    const el = document.getElementById("d11-coach-root");
    if (el) el.style.display = "block";
    return;
  }
  window.__D11CoachInjected = true;

  const BASE = (document.currentScript && document.currentScript.src
    ? document.currentScript.src.replace(/\/[^/]*$/, "/")
    : "https://samuellachance.github.io/destiny-eleven-coach/");

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.documentElement.appendChild(s);
    });
  }

  function extract() {
    const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const st = getComputedStyle(el);
      return (
        r.width > 8 &&
        r.height > 8 &&
        st.visibility !== "hidden" &&
        st.display !== "none" &&
        Number(st.opacity) !== 0
      );
    };
    const hasLetter = (s) => /[A-Za-zÀ-ÖØ-öø-ÿ]/.test(s || "");
    const skipExact =
      /^(continuer|retour|commencer|jouer maintenant|en voir plus|lancer|soutenir|soutenir le projet|cookies|annuler|mettre à jour|boutique|badges|panthéon|pantheon|partager|ma fiche|défier|defier|défier un ami|defier un ami|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face|carte)$/i;
    const skipPhrase =
      /cookies|soutenir le projet|mettre à jour|google analytics|refuser les cookies|accepter les cookies|jouer maintenant|en voir plus/i;

    const promptCandidates = [];
    document
      .querySelectorAll(
        '.event-text, .card-tag, #game-card p, p, .text, [class*="desc"], [class*="event"], [class*="prompt"], h2, h3'
      )
      .forEach((el) => {
        if (!visible(el)) return;
        const t = norm(el.innerText);
        if (t.length > 25 && t.length < 700) promptCandidates.push(t);
      });
    promptCandidates.sort((a, b) => b.length - a.length);
    const prompt = promptCandidates[0] || "";

    const seen = new Set();
    const choices = [];
    const push = (raw) => {
      let t = norm(raw);
      if (!t || !hasLetter(t) || t.length > 220) return;
      if (skipExact.test(t) || skipPhrase.test(t)) return;
      if (prompt && t.length > 80 && prompt.includes(t.slice(0, 40))) return;
      const firstLine = t.split(/\n/)[0].trim();
      if (firstLine.length >= 2 && firstLine.length < t.length && firstLine.length <= 80) t = firstLine;
      if (seen.has(t)) return;
      seen.add(t);
      choices.push(t);
    };

    document.querySelectorAll("#game-card .opt-btn, .event-options .opt-btn, .opt-btn").forEach((el) => {
      if (visible(el)) push(el.innerText);
    });
    document.querySelectorAll(".nat-card, .origin-card").forEach((el) => {
      if (!visible(el)) return;
      const name = el.querySelector(".nat-name, .origin-name");
      push((name && name.innerText) || el.innerText);
    });
    if (choices.length < 2) {
      document.querySelectorAll('button, .btn, [role="button"]').forEach((el) => {
        if (visible(el)) push(el.innerText || el.getAttribute("aria-label") || "");
      });
    }
    return [prompt, choices];
  }

  function ensureUI() {
    if (document.getElementById("d11-coach-root")) return;
    const root = document.createElement("div");
    root.id = "d11-coach-root";
    root.innerHTML = `
      <style>
        #d11-coach-root {
          all: initial;
          position: fixed; z-index: 2147483646;
          right: 12px; bottom: 12px; width: min(340px, calc(100vw - 24px));
          font-family: system-ui, Segoe UI, sans-serif;
        }
        #d11-coach-panel {
          background: #0f3d2e; color: #f4fff7;
          border: 2px solid #c8f560; border-radius: 16px;
          box-shadow: 0 16px 40px rgba(0,0,0,.35);
          padding: 12px 14px; line-height: 1.35;
        }
        #d11-coach-panel h3 { margin: 0 0 6px; font-size: 14px; color: #c8f560; }
        #d11-coach-pick { font-size: 18px; font-weight: 800; margin: 6px 0; color: #fff; }
        #d11-coach-reason, #d11-coach-status { font-size: 12px; opacity: .85; }
        #d11-coach-prompt { font-size: 12px; margin-top: 8px; max-height: 72px; overflow: auto; opacity: .9; }
        #d11-coach-close {
          position: absolute; top: 8px; right: 10px; border: 0; background: transparent;
          color: #c8f560; font-size: 18px; cursor: pointer;
        }
      </style>
      <div id="d11-coach-panel" style="position:relative">
        <button id="d11-coach-close" type="button" aria-label="Fermer">×</button>
        <h3>Destiny Eleven Coach</h3>
        <div id="d11-coach-status">Chargement…</div>
        <div id="d11-coach-pick"></div>
        <div id="d11-coach-reason"></div>
        <div id="d11-coach-prompt"></div>
      </div>
    `;
    document.documentElement.appendChild(root);
    document.getElementById("d11-coach-close").onclick = () => {
      root.style.display = "none";
    };
  }

  async function boot() {
    ensureUI();
    const status = document.getElementById("d11-coach-status");
    try {
      if (!window.D11SaveCodec) {
        await loadScript(BASE + "save_codec.js");
      }
      if (!window.DestinyCoach) {
        await loadScript(BASE + "advisor.js");
      }
      const [scenarios, tree] = await Promise.all([
        fetch(BASE + "scenarios.json").then((r) => r.json()),
        fetch(BASE + "tree_model.json").then((r) => r.json()).catch(() => null),
      ]);
      if (tree && window.DestinyCoach.setTreeModel) DestinyCoach.setTreeModel(tree);
      status.textContent = "Actif — joue, le conseil se met à jour";

      let last = "";
      setInterval(() => {
        try {
          const [prompt, choices] = extract();
          if (!choices || choices.length < 2) {
            status.textContent = "En attente d’un dilemme…";
            return;
          }
          const player =
            (window.D11SaveCodec && D11SaveCodec.readPlayerFromStorage && D11SaveCodec.readPlayerFromStorage()) ||
            null;
          const fp =
            prompt +
            "||" +
            choices.join("||") +
            "||" +
            (player
              ? [player.age, player.ovr, player.injuryWeeks, player.form, player.moral, player.club].join(",")
              : "");
          if (fp === last) return;
          last = fp;
          const advice = DestinyCoach.advise(prompt, choices, scenarios, player);
          document.getElementById("d11-coach-pick").textContent = "→ " + (advice.pick || "—");
          let reason = advice.reason || "";
          if (player) {
            const bits = [
              player.pos || "",
              "OVR" + (player.ovr != null ? player.ovr : "?"),
              "âge" + (player.age != null ? player.age : "?"),
              player.club || "",
            ].filter(Boolean);
            if ((player.injuryWeeks || 0) > 0) bits.push("blessé×" + player.injuryWeeks);
            reason = (reason ? reason + " · " : "") + bits.join(" · ");
          }
          document.getElementById("d11-coach-reason").textContent = reason;
          document.getElementById("d11-coach-prompt").textContent = prompt || "";
          status.textContent = player
            ? "Conseil à jour (save lu)"
            : "Conseil à jour (pas de save)";
        } catch (e) {
          status.textContent = "Erreur lecture écran";
        }
      }, 450);
    } catch (e) {
      status.textContent = "Échec chargement coach: " + (e && e.message ? e.message : e);
    }
  }

  boot();
})();
