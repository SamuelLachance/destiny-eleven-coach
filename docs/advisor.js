/**
 * Destiny Eleven Coach — heuristique + oracle (statique, GitHub Pages)
 */
(function (global) {
  const UI_NOISE = /^(partager|ma fiche|défier un ami|defier un ami|défier|defier|continuer|retour|carte|soutenir le projet|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face)$/i;

  const GOOD = [
    [/\bcollectif\b/i, 5],
    [/équipe|equipe|coéquipier|coequipier|vestiaire|groupe|club/i, 2],
    [/hygiène|hygiene|diète|diete|sommeil|dormir|rentrer|récupér|recuper|repos|pause/i, 5],
    [/soigner|kiné|kine|médecin|medecin|médical|medical|hôpital|hopital|physio|inapte|arrêt|arret/i, 6],
    [/travailler|s'entraîner|s'entrainer|entraînement|entrainement|muscu|vidéo|video|analyser|étudier|etudier|apprendre|progresser|reconquérir|reconquerir/i, 5],
    [/vérifier|verifier|licence|fédération|federation|avocat|contrat clair|lire le contrat|prudent|cadre|garanties/i, 6],
    [/promettre|poignée|poignee|remercier|discret|humble|concentré|concentre|calme|respect|diplomatique/i, 3],
    [/frapper en force|en force|prendre le ballon|assumé|assumer/i, 3],
    [/\bautorité\b|\bautorite\b|\bprudent\b|\bsagesse\b|\bpro\b/i, 2],
    [/accepter.*(offre|contrat|prêt|pret|essayer)|signer|demander.*(temps de jeu|titulaire|garanties)/i, 4],
    [/titulaire|minutes|temps de jeu|jouer beaucoup/i, 3],
    [/sélection|selection|convoqué|convoque|répondre présent|repondre present|honorer|présent|present/i, 4],
    [/ignorer.*(provocation|presse|polémique|polemique|haters)|ne rien dire|passer mon chemin|ne pas répondre|ne pas repondre|bloquer/i, 4],
    [/excuser|s'excuser|présenter des excuses|presenter des excuses/i, 4],
    [/écouter|ecouter|suivre le plan|consigne|staff|suivre l'avis/i, 4],
    [/focus|carrière|carriere|rester focus/i, 2],
    [/refuser.*(poliment|boîte|boite|soirée|soiree|investir|mentir)/i, 4],
  ];

  const BAD = [
    [/\blégendaire\b|legendaire|panenka|rabona|tiktok|showboat|flex/i, -6],
    [/belle vie|soirée|soiree|boîte|boite|alcool|fêter|feter|fête|fete|juste un verre|champagne/i, -6],
    [/insulter|engueuler|clash|se battre|bagarre|provoc|humilier|menacer/i, -7],
    [/payer.*(frais|agent)|envoyer de l'argent|prêter sans|preter sans/i, -6],
    [/refuser.*(sélection|selection|convoq|entraî|entrain)/i, -4],
    [/forcer.*(bless|douleur|derby)|jouer blessé|jouer blesse|cacher la douleur|anti-douleurs/i, -6],
    [/bande du quartier|sécher|secher|arriver en retard/i, -5],
    [/drogue|parier|betting|casino|usurier|mentir sur/i, -8],
    [/poster sur les reseaux|poster sur les réseaux|buzz|alimenter le drama/i, -3],
    [/annoncer la retraite|prendre votre retraite/i, -12],
  ];

  function norm(s) {
    return (s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function cleanChoices(choices) {
    const out = [];
    const seen = new Set();
    for (const x of choices || []) {
      const t = String(x || "").trim();
      if (!t || seen.has(t)) continue;
      if (!/[A-Za-zÀ-ÖØ-öø-ÿ]/.test(t)) continue;
      if (UI_NOISE.test(t)) continue;
      if (t.length > 220) continue;
      seen.add(t);
      out.push(t);
    }
    return out;
  }

  function scoreChoice(text, prompt) {
    const cl = (text || "").toLowerCase();
    const pl = (prompt || "").toLowerCase();
    let score = 0;
    for (const [re, w] of GOOD) if (re.test(cl)) score += w;
    for (const [re, w] of BAD) if (re.test(cl)) score += w;

    if (/^\s*collectif\b/i.test(cl)) score += 4;
    if (/^\s*autorité\b|^\s*autorite\b/i.test(cl)) score += 1.5;
    if (/^\s*légendaire\b|^\s*legendaire\b/i.test(cl)) score -= 4;
    if (/^\s*prudent\b|^\s*sagesse\b|^\s*pro\b/i.test(cl)) score += 3;

    const m = cl.match(/(\d+(?:[.,]\d+)?)\s*k€/);
    if (m) score += Math.min(parseFloat(m[1].replace(",", ".")) / 18, 6);

    if (/bless|douleur|entorse|fatigue|genou|cheville|muscle|kiné|kine/.test(pl)) {
      if (/repos|soigner|arrêt|arret|médical|medical|médecin|medecin|inapte|suivre/.test(cl)) score += 6;
      if (/forcer|jouer quand même|jouer quand meme|risquer|cacher|anti-douleur/.test(cl)) score -= 6;
    }
    if (/temps de jeu|banc|famélique|famelique|remplaçant|remplacant/.test(pl)) {
      if (/^\s*rester\b/.test(cl)) score -= 4;
      if (/d1|d2|indemnité|indemnite|k€|partir|accepter|offre|titulaire|prêt|pret/.test(cl)) score += 5;
    }
    if (/agent|frais de dossier|sponsor douteux/.test(pl)) {
      if (/vérifier|verifier|licence|fédération|federation|refuser|lire/.test(cl)) score += 8;
      if (/^payer\b|donner/.test(cl)) score -= 8;
    }
    if (/penalty|pénalty|tir au but/.test(pl)) {
      if (/force/.test(cl)) score += 4;
      if (/panenka/.test(cl)) score -= 5;
    }
    if (/presse|journaliste|interview|média|media|réseaux|reseaux/.test(pl)) {
      if (/discret|équipe|equipe|collectif|diplomatique|excuses/.test(cl)) score += 4;
      if (/clash|attaquer|provoc|polémique|polemique|insulter/.test(cl)) score -= 5;
    }
    if (/coach|entraîneur|entraineur|staff/.test(pl)) {
      if (/écouter|ecouter|respect|travailler|discuter|calmement/.test(cl)) score += 5;
      if (/engueuler|insulter|ignorer|clash/.test(cl)) score -= 6;
    }
    if (/nuit|sortie|boîte|boite|soirée|soiree|fête|fete/.test(pl)) {
      if (/rentrer|refuser|dormir|hygiène|hygiene|tôt|tot/.test(cl)) score += 5;
      if (/accepter|y aller|profiter|verre|boire/.test(cl)) score -= 5;
    }
    if (/retraite|révérence|reverence|radios|dernière danse|derniere danse/.test(pl)) {
      if (/dernière danse|derniere danse|repousser|encore|battre|reconqu|simple joueur/.test(cl)) score += 10;
      if (/annoncer la retraite|prendre votre retraite|tête haute|tete haute/.test(cl)) score -= 12;
    }
    if (Math.abs(score) < 1.5) {
      if (/travailler|écoute|ecoute|discret|prudent|soigner|vérif|verif|focus|collectif/.test(cl)) score += 2.5;
      if (/clash|fête|fete|panenka|insulter|tiktok|buzz|forcer/.test(cl)) score -= 2.5;
    }
    if (text.length >= 10 && text.length <= 120) score += 0.4;
    return score;
  }

  function lookupOracle(prompt, choices, scenarios) {
    if (!scenarios || !scenarios.length || choices.length < 2) return null;
    const choiceSet = new Set(choices.map(norm));
    const pn = norm(prompt);
    let best = null;
    let bestOverlap = 0;

    for (const row of scenarios) {
      const rc = (row.choices || []).map(norm);
      if (rc.length < 2) continue;
      let overlap = 0;
      for (const x of rc) if (choiceSet.has(x)) overlap++;
      if (overlap >= 2 && overlap >= bestOverlap) {
        bestOverlap = overlap;
        best = row;
        const rp = norm(row.prompt || "");
        if (pn && rp && (rp.slice(0, 60).includes(pn.slice(0, 40)) || pn.slice(0, 60).includes(rp.slice(0, 40)))) {
          bestOverlap = overlap + 0.5;
        }
      }
    }
    if (!best || bestOverlap < 2) {
      for (const row of scenarios) {
        const rp = norm(row.prompt || "");
        if (rp.length > 40 && (pn.includes(rp.slice(0, 80)) || rp.includes(pn.slice(0, 80)))) {
          best = row;
          break;
        }
      }
    }
    if (!best) return null;
    const want = norm((best.choices || [])[best.best_i] || "");
    for (const ch of choices) {
      const cn = norm(ch);
      if (cn === want || cn.includes(want) || want.includes(cn)) {
        return { pick: ch, reason: `oracle jeu (${best.id || "event"})` };
      }
    }
    return null;
  }

  function antiRetire(prompt, choices) {
    const pl = (prompt || "").toLowerCase();
    const hit =
      /retraite|révérence|reverence|dernière saison|derniere saison|s'arrêter|s'arreter|radios/.test(pl) ||
      choices.some((ch) => /retraite|dernière danse|derniere danse|repousser/i.test(ch));
    if (!hit) return null;
    const cont = choices.filter((ch) => {
      const cl = ch.toLowerCase();
      return (
        /dernière danse|derniere danse|repousser|encore|continuer|battre|reconquérir|reconquerir|simple joueur|refuser|jouer/.test(cl) &&
        !/annoncer la retraite|prendre votre retraite|tête haute|tete haute/.test(cl)
      );
    });
    if (!cont.length) return null;
    cont.sort((a, b) => {
      const rank = (ch) => {
        const cl = ch.toLowerCase();
        let s = 0;
        if (/dernière danse|derniere danse/.test(cl)) s += 5;
        if (/repousser|encore/.test(cl)) s += 4;
        if (/battre|reconqu/.test(cl)) s += 3;
        return s;
      };
      return rank(b) - rank(a);
    });
    return { pick: cont[0], reason: "anti-retraite precoce (encore jouer)" };
  }

  function pickSetup(prompt, choices) {
    const pl = (prompt || "").toLowerCase();
    const find = (keys, avoid = []) => {
      for (const ch of choices) {
        const cl = ch.toLowerCase();
        if (avoid.some((a) => cl.includes(a))) continue;
        if (keys.some((k) => cl.includes(k))) return ch;
      }
      return null;
    };
    if (/origine|d'où venez-vous|d’où venez-vous/.test(pl)) {
      const p = find(["quartier populaire", "futsal", "fils de sportif"]);
      if (p) return { pick: p, reason: "stats utiles buteur" };
    }
    if (/adolescence|mode de vie/.test(pl)) {
      const p = find(["hygiène de pro", "hygiene"]);
      if (p) return { pick: p, reason: "forme + recruteurs" };
    }
    if (/entourage/.test(pl) && /intérêt|interet|contrat|gère|gere/.test(pl)) {
      const p = find(["agent ambitieux"]);
      if (p) return { pick: p, reason: "monte plus vite" };
    }
    if (/clubs vous ont repéré|recruteurs ont observé/.test(pl)) {
      const p = find(["rennes", "metz", "sociedad", "lyon", "lille", "monaco"], ["paris", "quimper", "aubervilliers"]);
      if (p) return { pick: p, reason: "bon club formateur" };
    }
    if (/poste|position|où jouez|ou jouez/.test(pl) && choices.some((c) => /attaquant|gardien|défenseur|defenseur|milieu/i.test(c))) {
      const p = find(["attaquant", "ailier", "meneur", "milieu offensif"]);
      if (p) return { pick: p, reason: "plus de stats buteur" };
    }
    return null;
  }

  let treeModel = null;

  function setTreeModel(model) {
    treeModel = model;
  }

  function _n(s) {
    return (s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function treeHeuristic(prompt, choice) {
    const c = _n(choice);
    const p = _n(prompt);
    let s = 0;
    if (/collectif|travailler|soigner|repos|verif|licence|prudent|discret|ecout|rentrer|hygiene|garant|diplomat|excus|focus|danse|repousser|encore/.test(c)) s += 5;
    if (/panenka|clash|insult|engueul|soiree|boite|alcool|fete|tiktok|buzz|forcer|dopage|casino|legendaire|annoncer la retraite|prendre votre retraite/.test(c)) s -= 6;
    if (/bless|douleur|medical|kine/.test(p)) {
      if (/repos|soigner|medical|inapte|suivre/.test(c)) s += 6;
      if (/forcer|cacher|anti-douleur/.test(c)) s -= 6;
    }
    if (/agent|frais/.test(p)) {
      if (/verif|licence|federation|refuser|lire/.test(c)) s += 8;
      if (/^payer|donner/.test(c)) s -= 8;
    }
    if (/penalty/.test(p)) {
      if (/force/.test(c)) s += 4;
      if (/panenka/.test(c)) s -= 5;
    }
    if (/retrait|radios|reverence/.test(p)) {
      if (/danse|repousser|encore|battre|reconqu/.test(c)) s += 10;
      if (/annoncer la retraite|prendre votre retraite|tete haute/.test(c)) s -= 12;
    }
    if (/soir|boite|fete|nuit/.test(p)) {
      if (/rentrer|refuser|dormir/.test(c)) s += 5;
      if (/accepter|profiter|verre/.test(c)) s -= 5;
    }
    return s;
  }

  function baseTreeFeatures(prompt, choice, keywords) {
    const p = _n(prompt);
    const c = _n(choice);
    const feats = [];
    for (const kw of keywords) {
      feats.push(c.includes(kw) ? 1 : 0);
      feats.push(p.includes(kw) ? 1 : 0);
    }
    feats.push(Math.min(c.length, 200) / 100);
    feats.push(/^\s*collectif\b/.test(c) ? 1 : 0);
    feats.push(c.includes("legendaire") ? 1 : 0);
    feats.push(/prudent|sagesse/.test(c) ? 1 : 0);
    feats.push(/soigner|repos|verif|travailler|ecout|discret|prudent|hygiene|rentrer|medical|present|garant|collectif|excus|focus|licence|danse|repousser/.test(c) ? 1 : 0);
    feats.push(/panenka|clash|insult|soiree|boite|alcool|fete|tiktok|buzz|forcer|legendaire|retraite/.test(c) ? 1 : 0);
    feats.push(treeHeuristic(prompt, choice) / 20);
    return feats;
  }

  function dilemmaFeatureMatrix(prompt, choices, keywords) {
    const hs = choices.map((ch) => treeHeuristic(prompt, ch));
    const hMax = Math.max(...hs);
    const hMin = Math.min(...hs);
    const hMean = hs.reduce((a, b) => a + b, 0) / (hs.length || 1);
    return choices.map((ch, i) => {
      const b = baseTreeFeatures(prompt, ch, keywords);
      return b.concat([
        hs[i] / 20,
        (hs[i] - hMean) / 20,
        hs[i] >= hMax - 1e-9 ? 1 : 0,
        hs[i] === hMin ? 1 : 0,
        choices.length / 5,
      ]);
    });
  }

  function evalTree(node, feats) {
    if (!node) return 0;
    if (typeof node.v === "number") return node.v;
    return feats[node.f] <= node.t ? evalTree(node.l, feats) : evalTree(node.r, feats);
  }

  function pickWithTree(prompt, choices) {
    if (!treeModel || !treeModel.tree) return null;
    const M = dilemmaFeatureMatrix(prompt, choices, treeModel.keywords || []);
    let best = choices[0];
    let bestScore = -1e9;
    for (let i = 0; i < choices.length; i++) {
      const s = evalTree(treeModel.tree, M[i]);
      if (s > bestScore) {
        bestScore = s;
        best = choices[i];
      }
    }
    return { pick: best, score: bestScore };
  }

  function advise(prompt, choices, scenarios) {
    const c = cleanChoices(choices);
    if (!c.length) return { pick: "", reason: "Aucun choix détecté", choices: [] };

    const oracle = lookupOracle(prompt, c, scenarios);
    if (oracle) return { ...oracle, choices: c, prompt };

    const retire = antiRetire(prompt, c);
    if (retire) return { ...retire, choices: c, prompt };

    const setup = pickSetup(prompt, c);
    if (setup) return { ...setup, choices: c, prompt };

    const treePick = pickWithTree(prompt, c);
    if (treePick) {
      const pct = treeModel.cv_top1_holdout != null ? ` · CV ${(100 * treeModel.cv_top1_holdout).toFixed(0)}%` : "";
      return {
        pick: treePick.pick,
        reason: `arbre ranking P(best)≈${treePick.score.toFixed(2)}${pct}`,
        choices: c,
        prompt,
      };
    }

    let best = c[0];
    let bestScore = -1e9;
    for (const ch of c) {
      const s = scoreChoice(ch, prompt);
      if (s > bestScore) {
        bestScore = s;
        best = ch;
      }
    }
    let why = "heuristique (fallback)";
    if (bestScore >= 5) why += " · signal pro/safe";
    else if (bestScore <= 0) why += " · moins risqué";
    return { pick: best, reason: `${why} (h=${bestScore.toFixed(1)})`, choices: c, prompt };
  }

  function parseBlob(blob) {
    const lines = String(blob || "")
      .split(/\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    let prompt = blob;
    let choices = [];
    if (lines.length >= 2) {
      const shortTail = [];
      for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].length <= 120) shortTail.unshift(lines[i]);
        else break;
      }
      if (shortTail.length >= 2) {
        choices = shortTail;
        prompt = lines.slice(0, lines.length - shortTail.length).join(" ") || lines[0];
      }
    }
    return { prompt, choices };
  }

  global.DestinyCoach = { advise, parseBlob, cleanChoices, scoreChoice, setTreeModel };
})(window);
