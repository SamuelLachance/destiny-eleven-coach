/**
 * Destiny Eleven Coach — heuristique + oracle (statique, GitHub Pages)
 */
(function (global) {
  const UI_NOISE = /^(partager|ma fiche|défier un ami|defier un ami|défier|defier|continuer|retour|carte|soutenir le projet|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face)$/i;

  const GOOD = [
    [/\bambitieux\b|tout miser|requin|rivale|transfert|offre|\bd1\b|partir|signer/i, 6],
    [/titulaire|minutes|temps de jeu|garanties|sélection|selection/i, 5],
    [/prendre le match|votre compte|taper du poing|œil pour œil|oeil pour oeil|clutch|assumer/i, 5],
    [/\bcollectif\b/i, 3],
    [/équipe|equipe|coéquipier|coequipier|vestiaire|groupe|club/i, 1],
    [/hygiène|hygiene|diète|diete|sommeil|dormir|rentrer|récupér|recuper|repos|pause/i, 4],
    [/soigner|kiné|kine|médecin|medecin|médical|medical|hôpital|hopital|physio|inapte|arrêt|arret|protocole/i, 5],
    [/travailler|s'entraîner|s'entrainer|entraînement|entrainement|muscu|vidéo|video|analyser|étudier|etudier|apprendre|progresser|reconquérir|reconquerir/i, 4],
    [/vérifier|verifier|licence|fédération|federation|avocat|contrat clair|lire le contrat|cadre|garanties/i, 4],
    [/promettre|poignée|poignee|remercier|discret|humble|concentré|concentre|calme|respect|diplomatique/i, 2],
    [/frapper en force|en force|prendre le ballon|assumé|assumer/i, 4],
    [/\bautorité\b|\bautorite\b|\bpro\b/i, 2],
    [/accepter.*(offre|contrat|prêt|pret|essayer)|demander.*(temps de jeu|titulaire|garanties)/i, 5],
    [/ignorer.*(provocation|presse|polémique|polemique|haters)|ne rien dire|passer mon chemin|ne pas répondre|ne pas repondre|bloquer/i, 2],
    [/excuser|s'excuser|présenter des excuses|presenter des excuses/i, 2],
    [/écouter|ecouter|suivre le plan|consigne|staff|suivre l'avis/i, 2],
    [/focus|carrière|carriere|rester focus/i, 2],
    [/refuser.*(poliment|boîte|boite|soirée|soiree|investir|mentir)/i, 4],
    [/dernière danse|derniere danse|repousser|encore/i, 8],
  ];

  const BAD = [
    [/\blégendaire\b|legendaire|panenka|rabona|tiktok|showboat|flex/i, -5],
    [/belle vie|soirée|soiree|boîte|boite|alcool|fêter|feter|fête|fete|juste un verre|champagne/i, -7],
    [/insulter|engueuler|clash|se battre|bagarre|provoc|humilier|menacer/i, -4],
    [/payer.*(frais|agent)|envoyer de l'argent|prêter sans|preter sans/i, -5],
    [/refuser.*(sélection|selection|convoq|entraî|entrain)/i, -5],
    [/cacher la douleur|anti-douleurs/i, -5],
    [/bande du quartier|sécher|secher|arriver en retard/i, -5],
    [/drogue|parier|betting|casino|usurier|mentir sur/i, -8],
    [/poster sur les reseaux|poster sur les réseaux|buzz|alimenter le drama/i, -4],
    [/annoncer la retraite|prendre votre retraite/i, -14],
    [/ombre du titulaire|patienter|rester en famille|études en parallèle|etudes en parallele|jouer simple/i, -2],
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

  function jaccardSets(a, b) {
    if (!a.size || !b.size) return 0;
    let inter = 0;
    for (const x of a) if (b.has(x)) inter++;
    return inter / (a.size + b.size - inter);
  }

  function charGrams(s, n) {
    const t = _n(s).replace(/\s+/g, " ");
    const g = new Set();
    if (t.length < n) {
      if (t) g.add(t);
      return g;
    }
    for (let i = 0; i <= t.length - n; i++) g.add(t.slice(i, i + n));
    return g;
  }

  function promptSim(a, b) {
    return 0.5 * jaccardSets(charGrams(a, 3), charGrams(b, 3)) + 0.5 * jaccardSets(charGrams(a, 4), charGrams(b, 4));
  }

  function choiceSim(a, b) {
    const na = new Set(_n(a).split(/\s+/).filter(Boolean));
    const nb = new Set(_n(b).split(/\s+/).filter(Boolean));
    return jaccardSets(na, nb);
  }

  function mapBestChoice(srcRow, choices) {
    const want = (srcRow.choices || [])[srcRow.best_i] || "";
    let bestCh = null;
    let bestS = -1;
    for (const ch of choices) {
      const s = choiceSim(want, ch);
      if (s > bestS) {
        bestS = s;
        bestCh = ch;
      }
    }
    if (bestS >= 0.2) return bestCh;
    const scores = srcRow.raw_scores || srcRow.qualities;
    if (scores && scores.length === (srcRow.choices || []).length) {
      const mapped = choices.map((ch) => {
        let bj = -1;
        let bs = -1;
        (srcRow.choices || []).forEach((sch, j) => {
          const s = choiceSim(ch, sch);
          if (s > bs) {
            bs = s;
            bj = j;
          }
        });
        return bs >= 0.2 ? Number(scores[bj]) : -1e9;
      });
      if (Math.max(...mapped) > -1e8) return choices[mapped.indexOf(Math.max(...mapped))];
    }
    return null;
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
    if (best) {
      const mapped = mapBestChoice(best, choices);
      if (mapped) return { pick: mapped, reason: `oracle jeu (${best.id || "event"})` };
    }

    // Retrieval flou (trigrammes) — meilleure generalisation holdout ~63.6% CV
    const minSim = (treeModel && treeModel.min_sim != null) ? treeModel.min_sim : 0.15;
    let fuzzy = null;
    let fuzzySim = 0;
    for (const row of scenarios) {
      if (!(row.prompt || "").trim()) continue;
      const s = promptSim(prompt, row.prompt);
      if (s > fuzzySim) {
        fuzzySim = s;
        fuzzy = row;
      }
    }
    if (fuzzy && fuzzySim >= minSim) {
      const mapped = mapBestChoice(fuzzy, choices);
      if (mapped) {
        return {
          pick: mapped,
          reason: `retrieval sim=${fuzzySim.toFixed(2)} (${fuzzy.id || "near"})`,
        };
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
    if (/ambitieux|titulaire|minutes|garant|transfert|offre|d1|selection|requin|rivale|tout miser|prendre le match|votre compte|poing|danse|repousser|encore|clutch/.test(c)) s += 6;
    if (/travailler|soigner|verif|licence|focus|collectif|ecout|hygiene/.test(c)) s += 4;
    if (/annoncer la retraite|prendre votre retraite|dopage|casino|alcool|soiree|boite|fete|tiktok|buzz|banc/.test(c)) s -= 10;
    if (/panenka|legendaire|insult|engueul/.test(c)) s -= 3;
    if (/bless|douleur|medical|kine|radios/.test(p)) {
      if (/repos|soigner|medical|inapte|suivre|protocole|repousser/.test(c)) s += 5;
      if (/forcer|cacher|anti-douleur|annoncer la retraite/.test(c)) s -= 4;
    }
    if (/agent|frais|sponsor|entourage/.test(p)) {
      if (/ambitieux|requin|international|verif|licence/.test(c)) s += 6;
      if (/^payer|donner/.test(c)) s -= 4;
      if (/rester en famille|famille/.test(c)) s -= 2;
    }
    if (/penalty/.test(p)) {
      if (/force/.test(c)) s += 4;
      if (/panenka/.test(c)) s -= 5;
    }
    if (/retrait|radios|reverence/.test(p)) {
      if (/danse|repousser|encore|battre|reconqu/.test(c)) s += 12;
      if (/annoncer la retraite|prendre votre retraite|tete haute/.test(c)) s -= 14;
    }
    if (/soir|boite|fete|nuit/.test(p)) {
      if (/rentrer|refuser|dormir/.test(c)) s += 5;
      if (/accepter|profiter|verre/.test(c)) s -= 6;
    }
    if (/coach|staff|entrain|banc|titulaire|ombre/.test(p)) {
      if (/poing|titulaire|minutes|ambitieux|discut/.test(c)) s += 5;
      if (/ecout|travaill|respect/.test(c)) s += 2;
      if (/ombre|patienter|silence/.test(c)) s -= 3;
    }
    if (/finale|derby|decisif|grand match/.test(p)) {
      if (/prendre le match|votre compte|assumer|clutch|force/.test(c)) s += 6;
      if (/jouer simple|passer|effacer/.test(c)) s -= 2;
    }
    if (/club formateur|poach|structure|etudes|etude|football/.test(p)) {
      if (/ambitieux|rivale|tout miser|football/.test(c)) s += 5;
      if (/fidele|etudes|etude|parallele/.test(c)) s -= 2;
    }
    return s;
  }

  function baseOnlyFeatures(prompt, choice, keywords) {
    const p = _n(prompt);
    const c = _n(choice);
    const feats = [];
    for (const kw of keywords) {
      feats.push(c.includes(kw) ? 1 : 0);
      feats.push(p.includes(kw) ? 1 : 0);
    }
    feats.push(Math.min(c.length, 200) / 100);
    feats.push(/collectif/.test(c) ? 1 : 0);
    feats.push(c.includes("legendaire") ? 1 : 0);
    feats.push(/prudent|sagesse|ambitieux/.test(c) ? 1 : 0);
    feats.push(/soigner|repos|verif|travailler|ecout|discret|prudent|hygiene|rentrer|medical|garant|collectif|excus|focus|licence|danse|repousser|titulaire/.test(c) ? 1 : 0);
    feats.push(/panenka|clash|insult|soiree|boite|alcool|fete|tiktok|buzz|forcer|legendaire|retraite|banc/.test(c) ? 1 : 0);
    const h = treeHeuristic(prompt, choice);
    feats.push(h / 20);
    feats.push(h > 0 ? 1 : 0);
    feats.push(h < 0 ? 1 : 0);
    return feats;
  }

  function dilemmaFeatureMatrix(prompt, choices, keywords) {
    const hs = choices.map((ch) => treeHeuristic(prompt, ch));
    const hMax = Math.max(...hs);
    const hMin = Math.min(...hs);
    const hMean = hs.reduce((a, b) => a + b, 0) / (hs.length || 1);
    const sorted = [...hs].sort((a, b) => a - b);
    const second = sorted.length > 1 ? sorted[sorted.length - 2] : sorted[0];
    return choices.map((ch, i) => {
      const b = baseOnlyFeatures(prompt, ch, keywords);
      return b.concat([
        hs[i] / 20,
        (hs[i] - hMean) / 20,
        hs[i] >= hMax - 1e-9 ? 1 : 0,
        hs[i] <= hMin + 1e-9 ? 1 : 0,
        choices.length / 5,
        Math.abs(hs[i] - second) < 1e-9 && hs[i] < hMax - 1e-9 ? 1 : 0,
      ]);
    });
  }

  function fnv1a(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }

  function hashFeats(prompt, choice, dim) {
    const text = "C:" + String(choice || "").toLowerCase() + "|P:" + String(prompt || "").toLowerCase().slice(0, 240);
    const v = new Array(dim).fill(0);
    for (const n of [3, 4, 5]) {
      for (let i = 0; i <= text.length - n; i++) {
        const h = fnv1a(text.slice(i, i + n));
        const idx = Math.floor(h / 2) % dim;
        v[idx] += h % 2 === 0 ? 1 : -1;
      }
    }
    let nrm = 0;
    for (const x of v) nrm += x * x;
    nrm = Math.sqrt(nrm);
    if (nrm > 1e-9) for (let i = 0; i < v.length; i++) v[i] /= nrm;
    return v;
  }

  function mlpForward(feats, layers) {
    let x = feats.slice();
    for (const layer of layers || []) {
      const W = layer.W;
      const b = layer.b;
      const out = new Array(W.length);
      for (let i = 0; i < W.length; i++) {
        let s = b[i] || 0;
        const row = W[i];
        for (let j = 0; j < row.length && j < x.length; j++) s += row[j] * x[j];
        out[i] = layer.act === "relu" ? Math.max(0, s) : s;
      }
      x = out;
    }
    return x[0] || 0;
  }

  function richNeuralRows(prompt, choices, keywords, hashDim, retrSim, retrMap) {
    const baseM = dilemmaFeatureMatrix(prompt, choices, keywords);
    const hs = choices.map((ch) => treeHeuristic(prompt, ch));
    const hMean = hs.reduce((a, b) => a + b, 0) / (hs.length || 1);
    const hMax = Math.max(...hs);
    let bestRet = 0;
    for (let i = 1; i < retrMap.length; i++) if (retrMap[i] > retrMap[bestRet]) bestRet = i;
    return choices.map((ch, i) => {
      const extra = hashFeats(prompt, ch, hashDim).concat([
        retrSim,
        retrMap[i] || 0,
        i === bestRet && (retrMap[i] || 0) > 0 ? 1 : 0,
        hs[i] / 20,
        (hs[i] - hMean) / 20,
        hs[i] >= hMax - 1e-9 ? 1 : 0,
      ]);
      return baseM[i].concat(extra);
    });
  }

  function retrievalMap(prompt, choices, scenarios, minSim) {
    if (!scenarios || !scenarios.length) return { sim: 0, mapped: choices.map(() => 0) };
    let best = null;
    let bestSim = -1;
    for (const row of scenarios) {
      const s = promptSim(prompt, row.prompt || "");
      if (s > bestSim) {
        bestSim = s;
        best = row;
      }
    }
    if (!best || bestSim < (minSim != null ? minSim : 0.15)) {
      return { sim: bestSim, mapped: choices.map(() => 0) };
    }
    const want = (best.choices || [])[best.best_i] || "";
    const mapped = choices.map((ch) => choiceSim(want, ch));
    const scores = best.raw_scores || best.qualities;
    if (scores && scores.length === (best.choices || []).length) {
      const soft = choices.map((ch) => {
        let bj = 0;
        let bs = -1;
        (best.choices || []).forEach((sch, j) => {
          const s = choiceSim(ch, sch);
          if (s > bs) {
            bs = s;
            bj = j;
          }
        });
        return bs >= 0.15 ? Number(scores[bj]) : 0;
      });
      const lo = Math.min(...soft);
      const hi = Math.max(...soft);
      const normSoft = soft.map((v) => (v - lo) / (hi - lo + 1e-9));
      return {
        sim: bestSim,
        mapped: mapped.map((v, i) => 0.5 * v + 0.5 * normSoft[i]),
      };
    }
    return { sim: bestSim, mapped };
  }

  function pickRanMlp(prompt, choices, scenarios) {
    const kws = treeModel.keywords || [];
    const hashDim = treeModel.hash_dim || 48;
    const layers = treeModel.layers || [];
    const wNn = treeModel.w_nn != null ? treeModel.w_nn : 0.35;
    const wRet = treeModel.w_retrieval != null ? treeModel.w_retrieval : 0.5;
    const wH = treeModel.w_heuristic != null ? treeModel.w_heuristic : 0.15;
    const gate = treeModel.gate_sim != null ? treeModel.gate_sim : null;
    const lowMode = treeModel.low_mode || "blend";
    const { sim, mapped } = retrievalMap(prompt, choices, scenarios, treeModel.min_sim);

    // Gate: haute similarité → retrieval (souvent meilleur)
    if (gate != null && gate <= 1.0 && sim >= gate && Math.max(...mapped) > 0) {
      let bestI = 0;
      for (let i = 1; i < mapped.length; i++) if (mapped[i] > mapped[bestI]) bestI = i;
      return { pick: choices[bestI], score: mapped[bestI] };
    }
    if (lowMode === "retr") {
      let bestI = 0;
      for (let i = 1; i < mapped.length; i++) if (mapped[i] > mapped[bestI]) bestI = i;
      if (Math.max(...mapped) > 0) return { pick: choices[bestI], score: mapped[bestI] };
    }
    if (lowMode === "heur") {
      const hs = choices.map((ch) => treeHeuristic(prompt, ch));
      let bestI = 0;
      for (let i = 1; i < hs.length; i++) if (hs[i] > hs[bestI]) bestI = i;
      return { pick: choices[bestI], score: hs[bestI] };
    }

    const rows = richNeuralRows(prompt, choices, kws, hashDim, sim, mapped);
    const ml = rows.map((f) => mlpForward(f, layers));
    const hs = choices.map((ch) => treeHeuristic(prompt, ch));
    const norm = (arr) => {
      const lo = Math.min(...arr);
      const hi = Math.max(...arr);
      return arr.map((v) => (v - lo) / (hi - lo + 1e-9));
    };
    const nn = norm(ml);
    const rr = norm(mapped);
    const hh = norm(hs);
    const scores = choices.map((_, i) => {
      if (lowMode === "mlp") return nn[i];
      return wNn * nn[i] + wRet * rr[i] + wH * hh[i];
    });
    let bestI = 0;
    for (let i = 1; i < scores.length; i++) if (scores[i] > scores[bestI]) bestI = i;
    return { pick: choices[bestI], score: scores[bestI] };
  }

  function pickLogisticBlend(prompt, choices) {
    const kws = treeModel.keywords || [];
    const M = dilemmaFeatureMatrix(prompt, choices, kws);
    const weights = treeModel.weights || [];
    const bias = treeModel.bias || 0;
    const wH = treeModel.blend_w_heuristic != null ? treeModel.blend_w_heuristic : 0.55;
    const ml = M.map((f) => logisticScore(f, weights, bias));
    const hs = choices.map((ch) => treeHeuristic(prompt, ch));
    const hMin = Math.min(...hs);
    const hMax = Math.max(...hs);
    const mMin = Math.min(...ml);
    const mMax = Math.max(...ml);
    const scores = choices.map((_, i) => {
      const hn = (hs[i] - hMin) / (hMax - hMin + 1e-9);
      const mn = (ml[i] - mMin) / (mMax - mMin + 1e-9);
      return wH * hn + (1 - wH) * mn;
    });
    let bestI = 0;
    for (let i = 1; i < scores.length; i++) if (scores[i] > scores[bestI]) bestI = i;
    return { pick: choices[bestI], score: scores[bestI] };
  }

  function evalTree(node, feats) {
    if (!node) return 0;
    if (typeof node.v === "number") return node.v;
    return feats[node.f] <= node.t ? evalTree(node.l, feats) : evalTree(node.r, feats);
  }

  function forestPredict(diffFeats) {
    const trees = treeModel.trees || (treeModel.tree ? [treeModel.tree] : []);
    if (!trees.length) return 0;
    let s = 0;
    for (const t of trees) s += evalTree(t, diffFeats);
    return s / trees.length;
  }

  function pickWithTree(prompt, choices, scenarios) {
    if (!treeModel) return null;
    const kws = treeModel.keywords || [];
    const type = treeModel.type || "";

    if ((type === "ran_mlp_retrieval" || type === "ran_mlp_gated" || type === "mlp_neural_ranker" || type === "mlp_with_retrieval_primary") && treeModel.layers) {
      return pickRanMlp(prompt, choices, scenarios);
    }

    if (type === "logistic_pointwise_blend" && treeModel.weights) {
      return pickLogisticBlend(prompt, choices);
    }

    if (
      type === "retrieval_tfidf_blend" ||
      type === "tuned_heuristic_rules" ||
      type === "heuristic_primary_rf_backup" ||
      treeModel.prefer_heuristic_if_better
    ) {
      const hs = choices.map((ch) => treeHeuristic(prompt, ch));
      let bestI = 0;
      for (let i = 1; i < hs.length; i++) if (hs[i] > hs[bestI]) bestI = i;
      return { pick: choices[bestI], score: hs[bestI] };
    }

    if (type === "random_forest_pairwise" || (treeModel.trees && treeModel.trees.length)) {
      const feats = choices.map((ch) => baseOnlyFeatures(prompt, ch, kws));
      const scores = choices.map(() => 0);
      for (let i = 0; i < choices.length; i++) {
        for (let j = 0; j < choices.length; j++) {
          if (i === j) continue;
          const diff = feats[i].map((v, k) => v - feats[j][k]);
          scores[i] += forestPredict(diff);
        }
      }
      let bestI = 0;
      for (let i = 1; i < scores.length; i++) if (scores[i] > scores[bestI]) bestI = i;
      return { pick: choices[bestI], score: scores[bestI] };
    }

    // ancien modele single-tree is_best
    if (!treeModel.tree) return null;
    const M = dilemmaFeatureMatrix(prompt, choices, kws);
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

    const treePick = pickWithTree(prompt, c, scenarios);
    if (treePick) {
      const pct = treeModel.cv_top1_holdout != null ? ` · CV ${(100 * treeModel.cv_top1_holdout).toFixed(0)}%` : "";
      const kind = (treeModel && treeModel.type) || "model";
      return {
        pick: treePick.pick,
        reason: `${kind} score≈${treePick.score.toFixed(2)}${pct}`,
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
