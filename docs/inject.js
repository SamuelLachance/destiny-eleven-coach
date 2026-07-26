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

  // Landing / start-career CTAs — not real dilemma options
  const START_CAREER_CTA =
    /^(commencer(\s+(la|ma)\s+carri[eè]re)?|jouer(\s+maintenant)?|lancer(\s+la\s+partie)?|continuer(\s+vers\s+(le\s+)?setup)?)$/i;

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
      /^(continuer|retour|commencer|commencer la carri[eè]re|commencer ma carri[eè]re|jouer|jouer maintenant|en voir plus|lancer|lancer la partie|soutenir|soutenir le projet|cookies|annuler|mettre à jour|boutique|badges|panthéon|pantheon|partager|ma fiche|défier|defier|défier un ami|defier un ami|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face|carte|continuer vers setup|continuer vers le setup)$/i;
    const skipPhrase =
      /cookies|soutenir le projet|mettre à jour|google analytics|refuser les cookies|accepter les cookies|jouer maintenant|en voir plus|commencer (la|ma) carri/i;

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
    let sawStartCareer = false;
    const push = (raw) => {
      let t = norm(raw);
      if (!t || !hasLetter(t) || t.length > 220) return;
      if (START_CAREER_CTA.test(t)) {
        sawStartCareer = true;
        return;
      }
      if (skipExact.test(t) || skipPhrase.test(t)) return;
      if (prompt && t.length > 80 && prompt.includes(t.slice(0, 40))) return;
      const firstLine = t.split(/\n/)[0].trim();
      if (firstLine.length >= 2 && firstLine.length < t.length && firstLine.length <= 80) t = firstLine;
      if (START_CAREER_CTA.test(t)) {
        sawStartCareer = true;
        return;
      }
      if (skipExact.test(t) || skipPhrase.test(t)) return;
      if (seen.has(t)) return;
      seen.add(t);
      choices.push(t);
    };

    document.querySelectorAll("#game-card .opt-btn, .event-options .opt-btn, .opt-btn, #btn-start").forEach((el) => {
      if (visible(el)) push(el.innerText || el.getAttribute("aria-label") || "");
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
    // Single-button start screen, or only start CTAs left after filtering
    const startOnly = sawStartCareer && choices.length < 2;
    return [prompt, choices, startOnly];
  }

  function clearAdviceUI(statusMsg) {
    const status = document.getElementById("d11-coach-status");
    if (status) status.textContent = statusMsg || "En attente d’un dilemme…";
    const pick = document.getElementById("d11-coach-pick");
    if (pick) pick.textContent = "";
    const reason = document.getElementById("d11-coach-reason");
    if (reason) reason.textContent = "";
    const promptEl = document.getElementById("d11-coach-prompt");
    if (promptEl) promptEl.textContent = "";
    const host = document.getElementById("d11-coach-choices");
    if (host) host.innerHTML = "";
  }

  function esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderBreakdowns(advice) {
    const host = document.getElementById("d11-coach-choices");
    if (!host) return;
    const list = advice.breakdowns || [];
    const pick = advice.pick || "";
    if (!list.length) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = list
      .map((b) => {
        const isPick = b.choice === pick;
        const pos = (b.pos || []).map((x) => `<li>${esc(x)}</li>`).join("");
        const neg = (b.neg || []).map((x) => `<li>${esc(x)}</li>`).join("");
        return (
          `<div class="d11-choice${isPick ? " d11-choice-pick" : ""}">` +
          `<div class="d11-choice-title">${isPick ? "★ " : ""}${esc(b.choice)}</div>` +
          `<div class="d11-choice-pct">${esc(b.labelPct || "Soft vote ~?")}</div>` +
          `<div class="d11-choice-cols">` +
          `<div><div class="d11-col-h d11-pos">Points positifs</div><ul>${pos || "<li>—</li>"}</ul></div>` +
          `<div><div class="d11-col-h d11-neg">Risques</div><ul>${neg || "<li>—</li>"}</ul></div>` +
          `</div></div>`
        );
      })
      .join("");
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
          right: 12px; bottom: 12px; width: min(360px, calc(100vw - 24px));
          font-family: system-ui, Segoe UI, sans-serif;
        }
        #d11-coach-panel {
          background: #0f3d2e; color: #f4fff7;
          border: 2px solid #c8f560; border-radius: 16px;
          box-shadow: 0 16px 40px rgba(0,0,0,.35);
          padding: 12px 14px; line-height: 1.35;
          max-height: min(78vh, 640px); overflow: auto;
        }
        #d11-coach-panel h3 { margin: 0 0 6px; font-size: 14px; color: #c8f560; }
        #d11-coach-pick { font-size: 17px; font-weight: 800; margin: 6px 0; color: #fff; }
        #d11-coach-reason, #d11-coach-status { font-size: 12px; opacity: .85; }
        #d11-coach-prompt { font-size: 12px; margin-top: 8px; max-height: 56px; overflow: auto; opacity: .9; }
        #d11-coach-choices { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
        #d11-coach-root .d11-choice {
          border: 1px solid rgba(200,245,96,.35);
          border-radius: 10px; padding: 8px 9px; background: rgba(0,0,0,.18);
        }
        #d11-coach-root .d11-choice-pick {
          border-color: #c8f560; background: rgba(200,245,96,.12);
        }
        #d11-coach-root .d11-choice-title {
          font-size: 13px; font-weight: 700; color: #fff; margin-bottom: 2px;
        }
        #d11-coach-root .d11-choice-pct {
          font-size: 12px; font-weight: 700; color: #c8f560; margin-bottom: 6px;
        }
        #d11-coach-root .d11-choice-cols {
          display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
        }
        #d11-coach-root .d11-col-h {
          font-size: 10px; text-transform: uppercase; letter-spacing: .03em;
          opacity: .9; margin-bottom: 2px; font-weight: 700;
        }
        #d11-coach-root .d11-pos { color: #9be7a8; }
        #d11-coach-root .d11-neg { color: #ffb4a8; }
        #d11-coach-root ul {
          margin: 0; padding-left: 14px; font-size: 11px; opacity: .95;
        }
        #d11-coach-root li { margin: 0 0 2px; }
        #d11-coach-close {
          position: absolute; top: 8px; right: 10px; border: 0; background: transparent;
          color: #c8f560; font-size: 18px; cursor: pointer;
        }
        @media (max-width: 420px) {
          #d11-coach-root { right: 8px; bottom: 8px; width: calc(100vw - 16px); }
          #d11-coach-root .d11-choice-cols { grid-template-columns: 1fr; }
        }
      </style>
      <div id="d11-coach-panel" style="position:relative">
        <button id="d11-coach-close" type="button" aria-label="Fermer">×</button>
        <h3>Destiny Eleven Coach</h3>
        <div id="d11-coach-status">Chargement…</div>
        <div id="d11-coach-pick"></div>
        <div id="d11-coach-reason"></div>
        <div id="d11-coach-choices"></div>
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
      const [scenarios, tree, outcomes] = await Promise.all([
        fetch(BASE + "scenarios.json").then((r) => r.json()),
        fetch(BASE + "tree_model.json").then((r) => r.json()).catch(() => null),
        fetch(BASE + "event_outcomes.json").then((r) => r.json()).catch(() => null),
      ]);
      if (tree && window.DestinyCoach.setTreeModel) DestinyCoach.setTreeModel(tree);
      if (outcomes && window.DestinyCoach.setEventOutcomes) DestinyCoach.setEventOutcomes(outcomes);
      status.textContent = "Actif — joue, le conseil se met à jour";

      let last = "";
      setInterval(() => {
        try {
          const [prompt, choices, startOnly] = extract();
          if (startOnly || !choices || choices.length < 2) {
            const msg = startOnly ? "Démarre la carrière" : "En attente d’un dilemme…";
            if (last !== "__idle__" + msg) {
              last = "__idle__" + msg;
              clearAdviceUI(msg);
            } else {
              status.textContent = msg;
            }
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
          if (!advice.pick) {
            clearAdviceUI(advice.reason || "En attente d’un dilemme…");
            last = "__idle__" + (advice.reason || "");
            return;
          }
          document.getElementById("d11-coach-pick").textContent = "→ " + advice.pick;
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
          const src = (advice.breakdowns && advice.breakdowns[0] && advice.breakdowns[0].source) || "";
          if (src && src !== "estimé") reason = (reason ? reason + " · " : "") + "fx:" + src;
          document.getElementById("d11-coach-reason").textContent = reason;
          document.getElementById("d11-coach-prompt").textContent = prompt || "";
          renderBreakdowns(advice);
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
