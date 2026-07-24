"""JS partagé: lire prompt + choix visibles dans Destiny Eleven."""

# Exact UI chrome only — NEVER bare "accepter"/"confirmer" (real dilemma options).
EXTRACT_JS = """() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && st.visibility !== 'hidden'
      && st.display !== 'none' && Number(st.opacity) !== 0;
  };
  const hasLetter = (s) => /[A-Za-zÀ-ÖØ-öø-ÿ]/.test(s || '');

  // Exact chrome only. Do NOT match substrings like "Accepter l'offre".
  const skipExact = /^(continuer|retour|commencer|jouer maintenant|en voir plus|lancer|soutenir|soutenir le projet|cookies|annuler|mettre à jour|boutique|badges|panthéon|pantheon|partager|ma fiche|défier|defier|défier un ami|defier un ami|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face|carte)$/i;
  const skipPhrase = /cookies|soutenir le projet|mettre à jour|google analytics|refuser les cookies|accepter les cookies|jouer maintenant|en voir plus/i;

  const promptCandidates = [];
  document.querySelectorAll(
    '.event-text, .card-tag, #game-card p, p, .text, [class*="desc"], [class*="event"], [class*="prompt"], h2, h3'
  ).forEach(el => {
    if (!visible(el)) return;
    const t = norm(el.innerText);
    if (t.length > 25 && t.length < 700) promptCandidates.push(t);
  });
  promptCandidates.sort((a,b) => b.length - a.length);
  const prompt = promptCandidates[0] || '';

  const push = (raw, seen, choices) => {
    let t = norm(raw);
    if (!t || !hasLetter(t) || t.length > 220) return;
    if (skipExact.test(t) || skipPhrase.test(t)) return;
    if (prompt && t.length > 80 && prompt.includes(t.slice(0, 40))) return;
    // Prefer short name for multi-line cards
    const firstLine = t.split(/\\n/)[0].trim();
    if (firstLine.length >= 2 && firstLine.length < t.length && firstLine.length <= 80) {
      t = firstLine;
    }
    if (seen.has(t)) return;
    seen.add(t);
    choices.push(t);
  };

  const seen = new Set();
  const choices = [];

  // 1) Dilemmes: boutons .opt-btn dans la carte
  document.querySelectorAll('#game-card .opt-btn, .event-options .opt-btn, .opt-btn').forEach(el => {
    if (!visible(el)) return;
    push(el.innerText, seen, choices);
  });

  // 2) Setup: nationalité / origine / liste
  document.querySelectorAll('.nat-card, .origin-card').forEach(el => {
    if (!visible(el)) return;
    const name = el.querySelector('.nat-name, .origin-name');
    push((name && name.innerText) || el.innerText, seen, choices);
  });

  // 3) Fallback boutons génériques
  if (choices.length < 2) {
    document.querySelectorAll('button, .btn, [role="button"], [class*="choice"]').forEach(el => {
      if (!visible(el)) return;
      if (el.closest('.opt-btn, .nat-card, .origin-card')) return;
      push(el.innerText || el.getAttribute('aria-label') || '', seen, choices);
    });
  }

  return [prompt, choices];
}"""
