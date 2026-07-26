/**
 * Destiny Eleven Coach — heuristique + oracle (statique, GitHub Pages)
 */
(function (global) {
  const UI_NOISE = /^(partager|ma fiche|défier un ami|defier un ami|défier|defier|continuer|retour|carte|soutenir le projet|voir la carrière|statistiques|palmarès|palmares|parcours|distinctions|face à face)$/i;
  // Landing / start-career CTAs — not real dilemma options
  const START_CAREER_CTA =
    /^(commencer(\s+(la|ma)\s+carri[eè]re)?|jouer(\s+maintenant)?|lancer(\s+la\s+partie)?|continuer(\s+vers\s+(le\s+)?setup)?)$/i;

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
      if (UI_NOISE.test(t) || START_CAREER_CTA.test(t)) continue;
      if (t.length > 220) continue;
      seen.add(t);
      out.push(t);
    }
    return out;
  }

  /** True when every remaining label is a start-career CTA (no real dilemma). */
  function isStartCareerOnly(choices) {
    const raw = (choices || []).map((x) => String(x || "").trim()).filter(Boolean);
    if (!raw.length) return false;
    return raw.every((t) => START_CAREER_CTA.test(t));
  }

  function careerPhase(player) {
    if (global.D11SaveCodec && global.D11SaveCodec.careerPhase) {
      return global.D11SaveCodec.careerPhase(player);
    }
    if (!player) return "unknown";
    const age = player.age || 20;
    const ovr = player.ovr || 50;
    const pot = player.potCap || 80;
    if ((player.injuryWeeks || 0) > 0) return "injured";
    if (age >= 34 || player.retiring) return "decline";
    if (age <= 21 || (ovr < 68 && pot - ovr >= 12)) return "develop";
    if (ovr >= 78 || (player.rep || 0) >= 55) return "peak";
    return "prime";
  }

  /** Bias from live save — injury / phase / weak attrs (Engine-aligned). */
  function playerBias(text, prompt, player) {
    if (!player) return 0;
    const cl = (text || "").toLowerCase();
    const pl = (prompt || "").toLowerCase();
    const phase = careerPhase(player);
    let s = 0;
    const inj = player.injuryWeeks || 0;
    const form = player.form != null ? player.form : 50;
    const moral = player.moral != null ? player.moral : 50;
    const phys = player.p != null ? player.p : 50;
    const age = player.age || 20;

    if (inj > 0 || phase === "injured") {
      if (/repos|soigner|arrêt|arret|médical|medical|médecin|medecin|inapte|suivre|protocole|kiné|kine/.test(cl)) s += 10;
      if (/forcer|jouer quand|risquer|cacher|anti-douleur|cage|tournoi/.test(cl)) s -= 12;
    }
    if (form < 42) {
      if (/repos|récup|recuper|hygiène|hygiene|dormir|rentrer|pause/.test(cl)) s += 4;
      if (/soirée|soiree|boîte|boite|fête|fete|alcool/.test(cl)) s -= 6;
    }
    if (moral < 38) {
      if (/collectif|équipe|equipe|écouter|ecouter|focus|travailler|discret/.test(cl)) s += 3;
      if (/clash|insulter|engueuler|provoc/.test(cl)) s -= 5;
    }
    if (phys < 42) {
      if (/repos|soigner|athlétique|athletique|physique|hygiène|hygiene/.test(cl)) s += 2;
      if (/forcer|cage|tournoi|double charge|enchaîner|enchainer/.test(cl)) s -= 4;
    }

    if (phase === "develop") {
      if (/travailler|entraî|entrain|minutes|titulaire|apprendre|ombre|prêt|pret|d2|progress/.test(cl)) s += 4;
      if (/clash|fête|fete|buzz|tiktok|panenka|legendaire/.test(cl)) s -= 3;
      // Engine: études / patience can beat all-in early
      if (/études|etudes|parallèle|parallele|prudent/.test(cl) && /école|ecole|études|etudes|amateur|agent/.test(pl)) s += 3;
      if (/tout miser|risqué|risque/.test(cl) && age <= 18) s -= 2;
    }
    if (phase === "peak") {
      if (/ambitieux|prendre le match|votre compte|transfert|d1|clutch|assumer|ballon/.test(cl)) s += 3;
      if (/ombre|patienter|rester fidèle|rester fidele/.test(cl)) s -= 2;
    }
    if (phase === "decline") {
      if (/dernière danse|derniere danse|repousser|encore|battre|reconqu/.test(cl)) s += 8;
      if (/annoncer la retraite|prendre votre retraite|tête haute|tete haute/.test(cl)) s -= 10;
      if (/forcer|double|cage/.test(cl)) s -= 3;
    }
    if ((player.coachRel || 50) < 35) {
      if (/écouter|ecouter|respect|discuter|travailler|excuses/.test(cl)) s += 4;
      if (/engueuler|insulter|clash|poing|culotté|culotte/.test(cl)) s -= 4;
    }
    if ((player.rep || 0) >= 60 && /presse|média|media|réseaux|reseaux|interview/.test(pl)) {
      if (/discret|collectif|équipe|equipe|diplomatique/.test(cl)) s += 3;
      if (/clash|attaquer|buzz|poster/.test(cl)) s -= 3;
    }
    return s;
  }

  function scoreChoice(text, prompt, player) {
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
      // Engine: apprendre dans l'ombre sometimes beats "taper du poing"
      if (/ombre|apprendre/.test(cl)) score += 2;
      if (/poing|culotté|culotte/.test(cl)) score -= 1;
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
    // Engine CF: early all-in foot often loses to études
    if (/école|ecole|études|etudes|amateur|tout miser/.test(pl)) {
      if (/études|etudes|parallèle|parallele|prudent/.test(cl)) score += 3;
      if (/tout miser|risqué:\s*tout miser/.test(cl)) score -= 1;
    }
    if (Math.abs(score) < 1.5) {
      if (/travailler|écoute|ecoute|discret|prudent|soigner|vérif|verif|focus|collectif/.test(cl)) score += 2.5;
      if (/clash|fête|fete|panenka|insulter|tiktok|buzz|forcer/.test(cl)) score -= 2.5;
    }
    if (text.length >= 10 && text.length <= 120) score += 0.4;
    score += playerBias(text, prompt, player);
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
  let eventOutcomes = null;

  function setTreeModel(model) {
    treeModel = model;
  }

  function setEventOutcomes(data) {
    if (!data) {
      eventOutcomes = null;
      return;
    }
    let list = [];
    if (Array.isArray(data.events)) {
      list = data.events;
    } else if (data.events && typeof data.events === "object") {
      list = Object.keys(data.events).map((k) => data.events[k]);
    }
    eventOutcomes = {
      scrapedAt: data.scrapedAt || null,
      events: list
        .map((ev) => {
          if (!ev) return null;
          // Format compact pré-calculé (build_event_outcomes.py)
          if (Array.isArray(ev.o) && !ev.options) {
            return {
              id: ev.id,
              text: ev.p || ev.text || "",
              options: (ev.o || []).map((o) => ({
                label: o.l || o.label || "",
                outcomes: null,
                summary: { success: o.s, pos: o.pos || [], neg: o.neg || [] },
              })),
            };
          }
          // Format scrape_all_events.py (fx + weights bruts)
          return {
            id: ev.id,
            text: ev.text || ev.p || "",
            options: (ev.options || []).map((o) => {
              const base = String(o.label || o.text || "").trim();
              const hint = o.hint ? String(o.hint).trim() : "";
              const label = hint && base && !base.toLowerCase().startsWith(hint.toLowerCase() + ":")
                ? hint + ": " + base
                : base;
              return {
                label,
                labelRaw: base,
                hint,
                outcomes: o.outcomes || [],
                summary: null,
              };
            }),
          };
        })
        .filter((ev) => ev && (ev.options || []).length >= 2),
    };
  }

  const FX_LIVE_POS = {
    t: "technique",
    p: "physique",
    m: "mental",
    c: "charisme",
    rep: "réputation",
    form: "forme",
    mor: "moral",
    pot: "potentiel",
    money: "argent",
    coach: "relation coach",
    team: "vestiaire",
    natCall: "sélection",
    trophy: "trophée",
    award: "distinction",
  };
  const FX_LIVE_NEG = {
    inj: "blessure",
    fatigue: "fatigue",
    ban: "suspension",
    retire: "retraite",
    end: "fin de carrière",
    careerEnd: "fin de carrière",
    natRetire: "retraite internationale",
  };

  function shortFxText(t, n) {
    t = String(t || "")
      .trim()
      .replace(/\n/g, " ");
    if (t.length <= n) return t;
    const cut = t.slice(0, n).replace(/\s+\S*$/, "");
    return (cut || t.slice(0, n)).replace(/[.,;:]+$/, "") + "…";
  }

  function liveNetImpact(fx) {
    try {
      if (typeof Engine !== "undefined" && Engine && typeof Engine.netImpact === "function") {
        return Number(Engine.netImpact(fx || {})) || 0;
      }
    } catch (e) {}
    if (!fx) return 0;
    let s = 0;
    s += 1.4 * (fx.t || 0) + (fx.p || 0) + 1.2 * (fx.m || 0) + (fx.c || 0);
    s += 1.8 * (fx.rep || 0) + 0.7 * (fx.form || 0) + 0.5 * (fx.mor || 0);
    s -= 2.5 * (fx.inj || 0);
    if (fx.retire) s -= 28;
    if (fx.careerEnd || fx.end) s -= 80;
    return s;
  }

  function summarizeLiveOption(opt) {
    const outs = opt.outcomes || [];
    let tw = 0;
    let posW = 0;
    const pos = [];
    const neg = [];
    const seenP = new Set();
    const seenN = new Set();
    const push = (arr, seen, items, lim) => {
      for (const b of items || []) {
        if (!b || seen.has(b)) continue;
        seen.add(b);
        arr.push(b);
        if (arr.length >= (lim || 3)) break;
      }
    };
    for (const oc of outs) {
      const w = oc.weight || 1;
      tw += w;
      const fx = oc.fx || {};
      const impact = liveNetImpact(fx);
      const text = shortFxText(oc.text || "", 70);
      if (impact > 0.15) {
        posW += w;
        const bits = [];
        for (const [k, v] of Object.entries(fx)) {
          if (typeof v === "number" && v > 0 && FX_LIVE_POS[k]) bits.push("+" + FX_LIVE_POS[k]);
          if (k === "transfer") bits.push("transfert");
          if (k === "loan") bits.push("prêt");
        }
        push(pos, seenP, bits);
        if (text && w / (tw || 1) >= 0.18) push(pos, seenP, [text]);
      } else if (impact < -0.15) {
        const bits = [];
        for (const [k, v] of Object.entries(fx)) {
          if (FX_LIVE_NEG[k] && v) bits.push(FX_LIVE_NEG[k]);
          else if (typeof v === "number" && v < 0) bits.push((FX_LIVE_POS[k] || k) + " ↓");
        }
        push(neg, seenN, bits);
        if (text && w / (tw || 1) >= 0.12) push(neg, seenN, [text]);
      }
    }
    if (!pos.length) pos.push("effet mitigé");
    if (!neg.length) neg.push("peu de risque direct");
    return {
      label: String(opt.label || opt.text || "").trim(),
      success: Math.round((100 * posW) / (tw || 1)),
      pos: pos.slice(0, 3),
      neg: neg.slice(0, 3),
      approx: false,
      source: "engine",
    };
  }

  function readLiveEventsPack() {
    try {
      if (global.__D11 && Array.isArray(global.__D11.EVENTS)) return global.__D11.EVENTS;
      if (typeof EVENTS !== "undefined" && Array.isArray(EVENTS)) return EVENTS;
    } catch (e) {}
    return null;
  }

  function stripChoiceHint(s) {
    return String(s || "").replace(/^\s*[^:]{1,28}:\s*/, "").trim();
  }

  function softChoiceOverlap(srcLabels, choices) {
    let overlap = 0;
    for (const ch of choices || []) {
      let best = 0;
      for (const lab of srcLabels) {
        best = Math.max(best, choiceSim(lab, ch), choiceSim(stripChoiceHint(lab), stripChoiceHint(ch)));
      }
      if (best >= 0.35) overlap += best >= 0.55 ? 1 : 0.6;
    }
    return overlap;
  }

  function matchLiveEvent(prompt, choices) {
    const events = readLiveEventsPack();
    if (!events || !events.length) return null;
    const pn = norm(prompt);
    let best = null;
    let bestScore = 0;
    for (const ev of events) {
      const opts = (ev.options || []).map((o) => String(o.label || o.text || "").trim()).filter(Boolean);
      if (opts.length < 2) continue;
      let score = softChoiceOverlap(opts, choices);
      const ep = norm((ev.text || "").replace(/\{[^}]+\}/g, " "));
      if (pn && ep && (pn.includes(ep.slice(0, 48)) || ep.includes(pn.slice(0, 48)))) score += 1.5;
      else score += promptSim(prompt, (ev.text || "").replace(/\{[^}]+\}/g, " ")) * 2.2;
      if (score > bestScore) {
        bestScore = score;
        best = ev;
      }
    }
    if (!best || bestScore < 1.2) return null;
    return best;
  }

  function matchStaticEvent(prompt, choices) {
    const list = (eventOutcomes && eventOutcomes.events) || [];
    if (!list.length) return null;
    const pn = norm(prompt);
    let best = null;
    let bestScore = 0;
    for (const ev of list) {
      const opts = (ev.options || [])
        .flatMap((o) => [o.label, o.labelRaw].filter(Boolean))
        .map(String);
      if ((ev.options || []).length < 2) continue;
      let score = softChoiceOverlap(opts, choices);
      const filled = (ev.text || "").replace(/\{[^}]+\}/g, " ");
      const ep = norm(filled);
      if (pn && ep && (pn.includes(ep.slice(0, 48)) || ep.includes(pn.slice(0, 48)))) score += 1.5;
      else score += promptSim(prompt, filled) * 2.2;
      if (score > bestScore) {
        bestScore = score;
        best = ev;
      }
    }
    if (!best || bestScore < 1.2) return null;
    return best;
  }

  function mapOptionDetail(srcOpts, choice) {
    let best = null;
    let bestS = -1;
    for (const o of srcOpts || []) {
      const label = o.label || o.l || "";
      const s = Math.max(choiceSim(label, choice), choiceSim(stripChoiceHint(label), stripChoiceHint(choice)));
      if (s > bestS) {
        bestS = s;
        best = o;
      }
    }
    if (bestS < 0.2) return null;
    return { opt: best, sim: bestS };
  }

  function heuristicConsequenceTags(text) {
    const cl = (text || "").toLowerCase();
    const pos = [];
    const neg = [];
    if (/travailler|entraî|entrain|progress|apprendre|protocole|soigner|hygiène|hygiene|vérif|verif|licence/.test(cl)) {
      pos.push("progression / discipline");
    }
    if (/ambitieux|titulaire|minutes|transfert|d1|requin|prendre le match|votre compte|clutch|assumer/.test(cl)) {
      pos.push("statut / ambition");
    }
    if (/collectif|équipe|equipe|discret|diplomatique|excuses|écouter|ecouter/.test(cl)) {
      pos.push("vestiaire / image");
    }
    if (/repos|rentrer|dormir|récup|recuper|médical|medical|inapte/.test(cl)) {
      pos.push("santé / fraîcheur");
    }
    if (/soirée|soiree|boîte|boite|alcool|fête|fete|clash|insulter|panenka|tiktok|buzz|forcer|cacher/.test(cl)) {
      neg.push("risque image / forme");
    }
    if (/retraite|career|fin/.test(cl) && /annoncer|prendre/.test(cl)) {
      neg.push("fin de carrière");
    }
    if (/payer|investir|yolo|crypto|casino|offshore/.test(cl)) {
      neg.push("risque financier");
    }
    if (/bless|douleur|infiltration|forcer le retour/.test(cl)) {
      neg.push("risque blessure");
    }
    if (!pos.length) pos.push("gain possible selon tirage");
    if (!neg.length) neg.push("contrepartie possible");
    return { pos: pos.slice(0, 3), neg: neg.slice(0, 3) };
  }

  function matchScenarioRow(prompt, choices, scenarios) {
    if (!scenarios || !scenarios.length) return null;
    const choiceSet = new Set((choices || []).map(norm));
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
      }
    }
    if (best && bestOverlap >= 2) return best;
    let fuzzy = null;
    let fuzzySim = 0;
    for (const row of scenarios) {
      const s = promptSim(prompt, row.prompt || "");
      if (s > fuzzySim) {
        fuzzySim = s;
        fuzzy = row;
      }
    }
    if (fuzzy && fuzzySim >= 0.2) return fuzzy;
    return null;
  }

  /** Détail pos/nég + score oracle (soft-vote ensemble / trophées / top). */
  function choiceBreakdowns(prompt, choices, scenarios) {
    const c = cleanChoices(choices);
    if (c.length < 2) return [];

    function isSoftVoteGoal(row) {
      const g = String((row && row.label_goal) || '');
      return g.indexOf('softvote') >= 0 || Array.isArray(row && row.softvote_scores);
    }

    function isTrophyGoal(row) {
      const g = String((row && row.label_goal) || '');
      return g.indexOf('trophy') >= 0 || Array.isArray(row && row.trophy_p90);
    }

    function softVoteLabel(score, approx) {
      if (score == null || !isFinite(score)) {
        return approx ? 'Soft vote ~? (estimé)' : 'Soft vote ~?';
      }
      const n = Math.max(0, Math.min(100, Math.round(Number(score) * 100)));
      return (approx ? 'Soft vote ~' : 'Soft vote ') + n + '%';
    }

    function trophyLabel(score, approx) {
      if (score == null || !isFinite(score)) {
        return approx ? 'Trophées (P90) ~? (estimé)' : 'Trophées (P90) ~?';
      }
      const n = Math.round(Number(score) * 10) / 10;
      return (approx ? 'Upside trophées ~' : 'Trophées (P90) ~') + n;
    }

    function pctLabel(pct, approx) {
      if (pct == null || !isFinite(pct)) {
        return approx ? 'Top mondial ~?% (estimé)' : 'Top mondial ~?%';
      }
      const n = Math.max(0, Math.min(100, Math.round(pct)));
      return (approx ? 'Top mondial ~' : 'Top mondial ') + n + '%';
    }

    function attachFx(prompt, choices, ch, tags) {
      let pos = tags.pos;
      let neg = tags.neg;
      const staticEv = matchStaticEvent(prompt, choices);
      if (staticEv) {
        const mapped = mapOptionDetail(staticEv.options || [], ch);
        if (mapped) {
          const sum = mapped.opt.summary
            ? mapped.opt.summary
            : summarizeLiveOption(mapped.opt);
          if (sum.pos && sum.pos.length) pos = sum.pos;
          if (sum.neg && sum.neg.length) neg = sum.neg;
        }
        return { pos, neg };
      }
      const liveEv = matchLiveEvent(prompt, choices);
      if (liveEv) {
        let bestOpt = null;
        let bestS = -1;
        for (const o of liveEv.options || []) {
          const label = String(o.label || o.text || '').trim();
          const s = choiceSim(label, ch);
          if (s > bestS) {
            bestS = s;
            bestOpt = o;
          }
        }
        if (bestOpt && bestS >= 0.2) {
          const sum = summarizeLiveOption(bestOpt);
          if (sum.pos && sum.pos.length) pos = sum.pos;
          if (sum.neg && sum.neg.length) neg = sum.neg;
        }
      }
      return { pos, neg };
    }

    const row = matchScenarioRow(prompt, c, scenarios);
    if (row) {
      const softMode = isSoftVoteGoal(row);
      const trophyMode = !softMode && isTrophyGoal(row);
      const rates = row.top_mondial_pct || null;
      const softScores = row.softvote_scores || (softMode ? (row.raw_scores || null) : null);
      const trophyScores = row.trophy_p90 || (trophyMode ? (row.raw_scores || null) : null);
      const scores = row.raw_scores || row.qualities;
      const srcChoices = row.choices || [];
      const useSoft =
        Array.isArray(softScores) && softScores.length === srcChoices.length;
      const useTrophy =
        !useSoft && Array.isArray(trophyScores) && trophyScores.length === srcChoices.length;
      const useTopPct = !useSoft && !useTrophy && Array.isArray(rates) && rates.length === srcChoices.length;
      return c.map((ch) => {
        let bj = -1;
        let bs = -1;
        srcChoices.forEach((sch, j) => {
          const s = choiceSim(ch, sch);
          if (s > bs) {
            bs = s;
            bj = j;
          }
        });
        const tags = heuristicConsequenceTags(ch);
        const fx = attachFx(prompt, c, ch, tags);
        let pct = null;
        let tScore = null;
        let soft = null;
        if (bj >= 0 && bs >= 0.2) {
          if (useSoft && softScores[bj] != null) soft = Number(softScores[bj]);
          else if (useTrophy && trophyScores[bj] != null) tScore = Number(trophyScores[bj]);
          else if (useTopPct && rates[bj] != null) pct = Number(rates[bj]);
          else if (scores && scores[bj] != null) {
            const v = Number(scores[bj]);
            if (softMode) soft = v <= 1 ? v : v / 100;
            else if (trophyMode) tScore = v;
            else {
              pct = v <= 100 ? v : Math.min(95, Math.round(100 * (v - Math.min(...scores.map(Number))) / (Math.max(...scores.map(Number)) - Math.min(...scores.map(Number)) + 1e-9)));
            }
          }
        }
        const approx = bj < 0 || bs < 0.2;
        return {
          choice: ch,
          pos: fx.pos,
          neg: fx.neg,
          success: useSoft || softMode ? soft : useTrophy ? tScore : pct,
          approx,
          source: useSoft || softMode ? 'softvote' : useTrophy ? 'trophy_max' : 'top_mondial',
          labelPct:
            useSoft || softMode
              ? softVoteLabel(soft, approx)
              : useTrophy || trophyMode
                ? trophyLabel(tScore, approx)
                : pctLabel(pct, approx),
        };
      });
    }

    const liveEv = matchLiveEvent(prompt, c);
    if (liveEv) {
      return c.map((ch) => {
        const tags = heuristicConsequenceTags(ch);
        const fx = attachFx(prompt, c, ch, tags);
        return {
          choice: ch,
          pos: fx.pos,
          neg: fx.neg,
          success: null,
          approx: true,
          source: 'engine_fx_only',
          labelPct: 'Trophées (P90) ~? (pas de trajectoire)',
        };
      });
    }

    const staticEv = matchStaticEvent(prompt, c);
    if (staticEv) {
      return c.map((ch) => {
        const tags = heuristicConsequenceTags(ch);
        const fx = attachFx(prompt, c, ch, tags);
        return {
          choice: ch,
          pos: fx.pos,
          neg: fx.neg,
          success: null,
          approx: true,
          source: 'outcomes_fx_only',
          labelPct: 'Trophées (P90) ~? (pas de trajectoire)',
        };
      });
    }

    return c.map((ch) => {
      const tags = heuristicConsequenceTags(ch);
      return {
        choice: ch,
        pos: tags.pos,
        neg: tags.neg,
        success: null,
        approx: true,
        source: 'estimé',
        labelPct: 'Trophées (P90) ~? (estimé)',
      };
    });
  }

  function _n(s) {
    return (s || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function treeHeuristic(prompt, choice, player) {
    const c = _n(choice);
    const p = _n(prompt);
    let s = 0;
    if (/ambitieux|titulaire|minutes|garant|transfert|offre|d1|selection|requin|rivale|prendre le match|votre compte|danse|repousser|encore|clutch/.test(c)) s += 5;
    if (/travailler|soigner|verif|licence|focus|collectif|ecout|hygiene|prudent|apprendre/.test(c)) s += 4;
    if (/annoncer la retraite|prendre votre retraite|dopage|casino|alcool|soiree|boite|fete|tiktok|buzz/.test(c)) s -= 10;
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
      // Engine: ombre/apprendre often > poing early career
      if (/ombre|apprendre|patienter/.test(c)) s += 3;
      if (/poing|culotte|ambitieux|discut|titulaire|minutes/.test(c)) s += 2;
      if (/ecout|travaill|respect/.test(c)) s += 2;
    }
    if (/finale|derby|decisif|grand match/.test(p)) {
      if (/prendre le match|votre compte|assumer|clutch|force/.test(c)) s += 6;
      if (/jouer simple|passer|effacer/.test(c)) s -= 2;
    }
    if (/club formateur|poach|structure|etudes|etude|football|ecole/.test(p)) {
      // Engine CF: études parallel often beats all-in
      if (/etudes|etude|parallele|prudent/.test(c)) s += 3;
      if (/ambitieux|rivale/.test(c)) s += 4;
      if (/tout miser/.test(c)) s += 1;
      if (/fidele/.test(c)) s -= 1;
    }
    s += playerBias(choice, prompt, player);
    return s;
  }

  function baseOnlyFeatures(prompt, choice, keywords, player) {
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
    const h = treeHeuristic(prompt, choice, player);
    feats.push(h / 20);
    feats.push(h > 0 ? 1 : 0);
    feats.push(h < 0 ? 1 : 0);
    return feats;
  }

  function dilemmaFeatureMatrix(prompt, choices, keywords, player) {
    const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
    const hMax = Math.max(...hs);
    const hMin = Math.min(...hs);
    const hMean = hs.reduce((a, b) => a + b, 0) / (hs.length || 1);
    const sorted = [...hs].sort((a, b) => a - b);
    const second = sorted.length > 1 ? sorted[sorted.length - 2] : sorted[0];
    return choices.map((ch, i) => {
      const b = baseOnlyFeatures(prompt, ch, keywords, player);
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

  function richNeuralRows(prompt, choices, keywords, hashDim, retrSim, retrMap, player) {
    const baseM = dilemmaFeatureMatrix(prompt, choices, keywords, player);
    const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
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

  function pickRanMlp(prompt, choices, scenarios, player) {
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
      const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
      let bestI = 0;
      for (let i = 1; i < hs.length; i++) if (hs[i] > hs[bestI]) bestI = i;
      return { pick: choices[bestI], score: hs[bestI] };
    }

    const rows = richNeuralRows(prompt, choices, kws, hashDim, sim, mapped, player);
    const ml = rows.map((f) => mlpForward(f, layers));
    const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
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

  function pickLogisticBlend(prompt, choices, player) {
    const kws = treeModel.keywords || [];
    const M = dilemmaFeatureMatrix(prompt, choices, kws, player);
    const weights = treeModel.weights || [];
    const bias = treeModel.bias || 0;
    const wH = treeModel.blend_w_heuristic != null ? treeModel.blend_w_heuristic : 0.55;
    const ml = M.map((f) => logisticScore(f, weights, bias));
    const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
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

  function pickWithTree(prompt, choices, scenarios, player) {
    if (!treeModel) return null;
    const kws = treeModel.keywords || [];
    const type = treeModel.type || "";

    if ((type === "ran_mlp_retrieval" || type === "ran_mlp_gated" || type === "mlp_neural_ranker" || type === "mlp_with_retrieval_primary") && treeModel.layers) {
      return pickRanMlp(prompt, choices, scenarios, player);
    }

    if (type === "logistic_pointwise_blend" && treeModel.weights) {
      return pickLogisticBlend(prompt, choices, player);
    }

    if (
      type === "retrieval_tfidf_blend" ||
      type === "tuned_heuristic_rules" ||
      type === "heuristic_primary_rf_backup" ||
      treeModel.prefer_heuristic_if_better
    ) {
      const hs = choices.map((ch) => treeHeuristic(prompt, ch, player));
      let bestI = 0;
      for (let i = 1; i < hs.length; i++) if (hs[i] > hs[bestI]) bestI = i;
      // For retrieval models, prefer oracle path; this branch is heuristic fallback blend
      if (type === "retrieval_tfidf_blend" && treeModel.blend_w_heuristic === 0) {
        // still allow player-biased heuristic when oracle missed
        return { pick: choices[bestI], score: hs[bestI] };
      }
      return { pick: choices[bestI], score: hs[bestI] };
    }

    if (type === "random_forest_pairwise" || (treeModel.trees && treeModel.trees.length)) {
      const feats = choices.map((ch) => baseOnlyFeatures(prompt, ch, kws, player));
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
    const M = dilemmaFeatureMatrix(prompt, choices, kws, player);
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

  /** Hard overrides when live save contradicts generic Engine CF (avg starter). */
  function playerHardOverride(prompt, choices, player) {
    if (!player || !choices || choices.length < 2) return null;
    const phase = careerPhase(player);
    const pl = (prompt || "").toLowerCase();

    if ((player.injuryWeeks || 0) > 0 || phase === "injured" || /bless|douleur|entorse|kiné|kine|médical|medical/.test(pl)) {
      const med = choices.filter((ch) =>
        /repos|soigner|arrêt|arret|médical|medical|médecin|medecin|inapte|protocole|kiné|kine|suivre/.test(ch)
      );
      const bad = choices.filter((ch) => /forcer|cacher|anti-douleur|jouer quand/.test(ch));
      if (med.length && (!bad.length || med[0] !== bad[0])) {
        med.sort((a, b) => playerBias(b, prompt, player) - playerBias(a, prompt, player));
        return { pick: med[0], reason: `blessé (${player.injuryWeeks || "?"} sem.) → protocole` };
      }
    }
    if (phase === "decline" || (player.age || 0) >= 34) {
      const cont = choices.filter(
        (ch) =>
          /dernière danse|derniere danse|repousser|encore|battre|reconqu|simple joueur/.test(ch) &&
          !/annoncer la retraite|prendre votre retraite/.test(ch)
      );
      if (cont.length) return { pick: cont[0], reason: `phase déclin (âge ${player.age}) → prolonger` };
    }
    return null;
  }

  function withBreakdowns(result, prompt, choices, scenarios) {
    const c = result.choices || cleanChoices(choices);
    const breakdowns = choiceBreakdowns(prompt, c, scenarios);
    return { ...result, choices: c, breakdowns };
  }

  function advise(prompt, choices, scenarios, player) {
    if (isStartCareerOnly(choices)) {
      return { pick: "", reason: "Démarre la carrière", choices: [], breakdowns: [] };
    }
    const c = cleanChoices(choices);
    if (!c.length) return { pick: "", reason: "Aucun choix détecté", choices: [], breakdowns: [] };
    if (c.length < 2) {
      return { pick: "", reason: "En attente d’un dilemme…", choices: c, breakdowns: [] };
    }

    const hard = playerHardOverride(prompt, c, player);
    if (hard) {
      return withBreakdowns(
        { ...hard, choices: c, prompt, player, phase: careerPhase(player) },
        prompt,
        c,
        scenarios
      );
    }

    const oracle = lookupOracle(prompt, c, scenarios);
    if (oracle) {
      // Soft re-rank oracle candidates with player bias when margins are close
      if (player && scenarios) {
        const phase = careerPhase(player);
        const scored = c.map((ch) => ({
          ch,
          s: scoreChoice(ch, prompt, player),
        }));
        scored.sort((a, b) => b.s - a.s);
        const top = scored[0];
        const oraclePick = oracle.pick;
        const oracleScore = scored.find((x) => x.ch === oraclePick);
        if (
          top &&
          oracleScore &&
          top.ch !== oraclePick &&
          top.s >= oracleScore.s + 6 &&
          (phase === "injured" || phase === "develop" || phase === "decline")
        ) {
          return withBreakdowns(
            {
              pick: top.ch,
              reason: `oracle+stats (${phase}) · override joueur`,
              choices: c,
              prompt,
              player,
              phase,
            },
            prompt,
            c,
            scenarios
          );
        }
      }
      return withBreakdowns(
        {
          ...oracle,
          choices: c,
          prompt,
          player,
          phase: careerPhase(player),
          reason: player
            ? `${oracle.reason} · ${careerPhase(player)} OVR${player.ovr || "?"}`
            : oracle.reason,
        },
        prompt,
        c,
        scenarios
      );
    }

    const retire = antiRetire(prompt, c);
    if (retire) {
      return withBreakdowns(
        { ...retire, choices: c, prompt, player, phase: careerPhase(player) },
        prompt,
        c,
        scenarios
      );
    }

    const setup = pickSetup(prompt, c);
    if (setup) return withBreakdowns({ ...setup, choices: c, prompt }, prompt, c, scenarios);

    const treePick = pickWithTree(prompt, c, scenarios, player);
    if (treePick) {
      const pct = treeModel.cv_top1_holdout != null ? ` · CV ${(100 * treeModel.cv_top1_holdout).toFixed(0)}%` : "";
      const kind = (treeModel && treeModel.type) || "model";
      const phase = careerPhase(player);
      return withBreakdowns(
        {
          pick: treePick.pick,
          reason: `${kind} score≈${treePick.score.toFixed(2)}${pct}${player ? ` · ${phase}` : ""}`,
          choices: c,
          prompt,
          player,
          phase,
        },
        prompt,
        c,
        scenarios
      );
    }

    let best = c[0];
    let bestScore = -1e9;
    for (const ch of c) {
      const s = scoreChoice(ch, prompt, player);
      if (s > bestScore) {
        bestScore = s;
        best = ch;
      }
    }
    let why = "heuristique (fallback)";
    if (player) why += ` · ${careerPhase(player)}`;
    if (bestScore >= 5) why += " · signal Engine";
    else if (bestScore <= 0) why += " · moins risqué";
    return withBreakdowns(
      {
        pick: best,
        reason: `${why} (h=${bestScore.toFixed(1)})`,
        choices: c,
        prompt,
        player,
        phase: careerPhase(player),
      },
      prompt,
      c,
      scenarios
    );
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

  global.DestinyCoach = {
    advise,
    parseBlob,
    cleanChoices,
    scoreChoice,
    setTreeModel,
    setEventOutcomes,
    choiceBreakdowns,
    playerBias,
    careerPhase,
  };
})(window);
