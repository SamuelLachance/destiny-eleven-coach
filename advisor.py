"""Heuristique universelle + ML blend — couvre tous les dilemmes texte."""

from __future__ import annotations

import re

_HAS_LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_UI_NOISE = re.compile(
    r"^(partager|ma fiche|défier un ami|defier un ami|défier|defier|"
    r"continuer|retour|carte|soutenir le projet|voir la carrière|"
    r"statistiques|palmarès|palmares|parcours|distinctions|face à face)$",
    re.I,
)

# Lexique large: pro / safe / progression vs ego / fête / clash
_GOOD = [
    (r"\bcollectif\b", 5),
    (r"équipe|equipe|coéquipier|coequipier|vestiaire|groupe|club", 2),
    (r"hygiène|hygiene|diète|diete|sommeil|dormir|rentrer|récupér|recuper|repos|pause|récupération", 5),
    (r"soigner|kiné|kine|médecin|medecin|médical|medical|hôpital|hopital|physio|inapte|arrêt|arret", 6),
    (r"travailler|s'entraîner|s'entrainer|entraînement|entrainement|muscu|vidéo|video|analyser|étudier|etudier|apprendre|progresser|reconquérir|reconquerir", 5),
    (r"vérifier|verifier|licence|fédération|federation|avocat|contrat clair|lire le contrat|prudent|cadre|garanties", 6),
    (r"promettre|poignée|poignee|remercier|discret|humble|concentré|concentre|calme|respect|diplomatique", 3),
    (r"frapper en force|en force|prendre le ballon|assumé|assumer", 3),
    (r"\bautorité\b|\bautorite\b|\bprudent\b|\bsagesse\b|\bpro\b", 2),
    (r"accepter.*(offre|contrat|prêt|pret|essayer)|signer|demander.*(temps de jeu|titulaire|garanties)", 4),
    (r"titulaire|minutes|temps de jeu|jouer beaucoup", 3),
    (r"sélection|selection|convoqué|convoque|répondre présent|repondre present|honorer|présent|present", 4),
    (r"ignorer.*(provocation|presse|polémique|polemique|haters)|ne rien dire|passer mon chemin|ignorer les réseaux|ignorer les reseaux|ne pas répondre|ne pas repondre|bloquer", 4),
    (r"excuser|s'excuser|présenter des excuses|presenter des excuses", 4),
    (r"écouter|ecouter|suivre le plan|consigne|staff|suivre l'avis|suivre lavis", 4),
    (r"d1\b|élite|elite|c1\b|ligue des champions|champions league|meilleur salaire|\d+\s*k€", 2),
    (r"prolonger|renouveler|rester.*titulaire|rester.*jouer", 2),
    (r"s'expliquer|sexpliquer|discuter|dialoguer|clarifier|calmement", 2),
    (r"focus|focus football|priorité sport|priorite sport|carrière|carriere|rester focus", 2),
    (r"aider|mentor|conseiller un jeune|montrer l'exemple|montrer lexemple", 2),
    (r"épargne|epargne|conseiller financier|agent officiel|fifa", 2),
    (r"refuser.*(poliment|boîte|boite|soirée|soiree|investir|prêt douteux|pret douteux|sponsor douteux|argent|mentir)", 4),
    (r"passer un moment puis rentrer|rentrer tôt|rentrer tot", 3),
]

_BAD = [
    (r"\blégendaire\b|legendaire|panenka|rabona|trick|showboat|youtube|tiktok|story|flex|spectacle inutile|faire le show", -6),
    (r"belle vie|soirée|soiree|boîte|boite|alcool|fêter|feter|fête|fete|sortir en ville|night|juste un verre|just un verre|tequila|champagne|profiter à fond|profiter a fond", -6),
    (r"insulter|engueuler|lengueuler|l'engueuler|clash|frapper un|se battre|bagarre|provoc|humilier|menacer|répondre violemment|repondre violemment", -7),
    (r"payer.*(frais|agent|inconnu)|donner \d|envoyer de l'argent|envoyer de l’argent|espèces|especes|prêter sans|preter sans", -6),
    (r"refuser.*(sélection|selection|convoq|entraî|entrain|stage|rassemblement)", -4),
    (r"forcer.*(bless|douleur|derby)|jouer blessé|jouer blesse|cacher la douleur|ignorer la douleur|anti-douleurs|antidouleurs", -6),
    (r"bande du quartier|ignorer le staff|sécher|secher|arriver en retard|no-show|absent", -5),
    (r"paralys|refuser.*chanter|ne rien faire|fuite|fuir", -2),
    (r"drogue|parier|betting|casino|prêt douteux|pret douteux|usurier|mentir sur", -8),
    (r"poste sur les réseaux|poster sur les reseaux|twitter|polémique|polemique|buzz|alimenter le drama", -3),
    (r"rompre|insulter le coach|balancer|traître|traitre|contester en public", -5),
    (r"investir.*(grosse|tout)|tout miser|petite somme pour faire plaisir", -3),
    (r"rester au banc|élite banc|elite banc", -2),
]


def clean_choices(choices: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in choices:
        t = (x or "").strip()
        if not t or t in seen:
            continue
        if not _HAS_LETTER.search(t):
            continue
        if _UI_NOISE.match(t):
            continue
        if len(t) > 220:
            continue
        seen.add(t)
        out.append(t)
    return out


def _score_choice(text: str, prompt: str = "") -> float:
    cl = text.lower()
    pl = (prompt or "").lower()
    score = 0.0

    for pat, w in _GOOD:
        if re.search(pat, cl, re.I):
            score += w
    for pat, w in _BAD:
        if re.search(pat, cl, re.I):
            score += w

    # Tags en tête de bouton
    if re.match(r"^\s*collectif\b", cl):
        score += 4
    if re.match(r"^\s*autorité\b|^\s*autorite\b", cl):
        score += 1.5
    if re.match(r"^\s*légendaire\b|^\s*legendaire\b", cl):
        score -= 4
    if re.match(r"^\s*prudent\b|^\s*sagesse\b|^\s*pro\b", cl):
        score += 3

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*k€", cl)
    if m:
        score += min(float(m.group(1).replace(",", ".")) / 18.0, 6)

    # --- contexte prompt (universel) ---
    if re.search(r"bless|douleur|entorse|fatigue|crampe|genou|cheville|cuisse|muscle|kiné|kine", pl):
        if re.search(r"repos|soigner|arrêt|arret|prudence|médical|medical|médecin|medecin|inapte|suivre", cl):
            score += 6
        if re.search(r"forcer|jouer quand même|jouer quand meme|risquer|cacher|anti-douleur", cl):
            score -= 6

    if re.search(r"temps de jeu|banc|famélique|famelique|remplaçant|remplacant", pl):
        if re.match(r"^\s*rester\b", cl):
            score -= 4
        if re.search(r"d1|d2|indemnité|indemnite|k€|partir|accepter|offre|titulaire|prêt|pret", cl):
            score += 5

    if re.search(r"agent|frais de dossier|2000|€|euros|mirabolant|sponsor douteux", pl):
        if re.search(r"vérifier|verifier|licence|fédération|federation|refuser|lire", cl):
            score += 8
        if re.search(r"^payer\b|donner|signer pour l'argent|laisser l'agent", cl):
            score -= 8

    if re.search(r"penalty|pénalty|pénalti|tir au but", pl):
        if re.search(r"force", cl):
            score += 4
        if re.search(r"panenka", cl):
            score -= 5
        if re.search(r"laisser le tireur|collectif", cl):
            score += 1

    if re.search(r"presse|journaliste|interview|média|media|réseaux|reseaux|tv\b", pl):
        if re.search(r"discret|équipe|equipe|collectif|merci|humble|ne rien|excuses|diplomatique", cl):
            score += 4
        if re.search(r"clash|attaquer|provoc|polémique|polemique|insulter|critiquer fort|drama", cl):
            score -= 5

    if re.search(r"coach|entraîneur|entraineur|staff|directeur", pl):
        if re.search(r"écouter|ecouter|respect|travailler|comprendre|discuter|calmement|aller voir", cl):
            score += 5
        if re.search(r"engueuler|insulter|ignorer|clash|balancer|public", cl):
            score -= 6

    if re.search(r"nuit|sortie|boîte|boite|soirée|soiree|fête|fete|copains|noël|noel", pl):
        if re.search(r"rentrer|refuser|dormir|non\b|hygiène|hygiene|demain match|tôt|tot", cl):
            score += 5
        if re.search(r"accepter|y aller|profiter|verre|boire|jusqu'au bout", cl):
            score -= 5

    if re.search(r"contrat|offre|transfert|mercato|indemnité|indemnite|prêt|pret", pl):
        if re.search(r"titulaire|temps de jeu|minutes|garanties|c1|champions|accepter le prêt|accepter le pret", cl):
            score += 4
        if re.search(r"rester.*banc|refuser.*tout|argent seulement", cl):
            score -= 2

    if re.search(r"sélection|selection|bleu|national", pl):
        if re.search(r"présent|present|accepter|honorer|rejoindre", cl):
            score += 5
        if re.search(r"refuser|sécher|secher|fêter|feter", cl):
            score -= 5

    if re.search(r"argent|investissement|business|boîte de nuit|boite de nuit|restau|prêt d'argent|pret d'argent", pl):
        if re.search(r"refuser|prudent|attendre|agent|conseiller|cadre|raisonnable", cl):
            score += 4
        if re.search(r"investir tout|tout miser|prêter|preter sans|grosse somme|fortune", cl):
            score -= 4

    if re.search(r"fille|relation|people|influenceur|influenceuse", pl):
        if re.search(r"discret|focus|football|attendre|concentré|concentre", cl):
            score += 3
        if re.search(r"people|médiatiser|mediatiser|story", cl):
            score -= 3

    if re.search(r"âge|age|mentir|tricher|dopage|amende|retard", pl):
        if re.search(r"refuser|s'excuser|excuser|à l'heure|a l'heure|honnête|honnete", cl):
            score += 5
        if re.search(r"accepter|ignorer|contester en public", cl):
            score -= 4

    if re.search(r"poste|système|systeme|ailier|milieu", pl):
        if re.search(r"accepter|essayer|équipe|equipe", cl):
            score += 3
        if re.search(r"ego|menacer|refuser par", cl):
            score -= 4

    if re.search(r"retraite|révérence|reverence|radios|dernière danse|derniere danse", pl):
        if re.search(r"dernière danse|derniere danse|repousser|encore|battre|reconqu|simple joueur", cl):
            score += 10
        if re.search(r"annoncer la retraite|prendre votre retraite|tête haute|tete haute|s'arrêter|s'arreter", cl):
            score -= 12

    # Fallback linguistique: si rien ne matche fort, favoriser le ton "pro"
    if abs(score) < 1.5:
        if re.search(r"travailler|écoute|ecoute|discret|prudent|soigner|vérif|verif|focus|équipe|equipe|collectif", cl):
            score += 2.5
        if re.search(r"clash|fête|fete|panenka|insulter|tiktok|buzz|forcer", cl):
            score -= 2.5

    if 10 <= len(text) <= 120:
        score += 0.4

    return score


def advise(prompt: str, choices: list[str]) -> tuple[str, str]:
    p = prompt or ""
    c = clean_choices([x.strip() for x in choices if x and str(x).strip()])
    if not c:
        return ("", "Aucun choix détecté")

    # 0) Oracle: evenement exact du jeu deja labellise
    try:
        from scenario_lookup import lookup_best

        hit = lookup_best(p, c)
        if hit:
            return hit
    except Exception:
        pass

    # 0b) Hard rule retraite: ne JAMAIS couper la carriere a la 1re proposition
    pl = p.lower()
    if re.search(r"retraite|révérence|reverence|dernière saison|derniere saison|s'arrêter|s'arreter|radios sur la table", pl) or any(
        re.search(r"retraite|dernière danse|derniere danse|repousser", ch.lower()) for ch in c
    ):
        cont = [
            ch
            for ch in c
            if re.search(
                r"dernière danse|derniere danse|repousser|encore|continuer|battre|reconquérir|reconquerir|"
                r"simple joueur|refuser|pas.*retraite|jouer",
                ch.lower(),
            )
            and not re.search(r"annoncer la retraite|prendre votre retraite|tête haute|tete haute", ch.lower())
        ]
        if cont:
            def _cont_rank(ch: str) -> int:
                cl = ch.lower()
                s = 0
                if re.search(r"dernière danse|derniere danse", cl):
                    s += 5
                if re.search(r"repousser|encore", cl):
                    s += 4
                if re.search(r"battre|reconqu", cl):
                    s += 3
                if re.search(r"simple joueur|continuer|jouer", cl):
                    s += 2
                return s

            ranked = sorted(cont, key=_cont_rank, reverse=True)
            return ranked[0], "anti-retraite precoce (encore jouer)"

    h_scores = {ch: _score_choice(ch, p) for ch in c}

    ml_scores: dict[str, float] = {}
    n_ml = 0
    try:
        from ml_model import load_model, ml_rank_choices

        bundle = load_model()
        if bundle and bundle.get("n", 0) >= 20:
            n_ml = int(bundle.get("n") or 0)
            for pred, ch in ml_rank_choices(p, c):
                ml_scores[ch] = float(pred)
    except Exception:
        pass

    combined: list[tuple[float, str, str]] = []
    h_vals = list(h_scores.values())
    h_min, h_max = min(h_vals), max(h_vals)
    h_span = (h_max - h_min) or 1.0

    use_ml = False
    if ml_scores:
        ml_vals = list(ml_scores.values())
        ml_min, ml_max = min(ml_vals), max(ml_vals)
        ml_span = (ml_max - ml_min) or 0.0
        # ML différencie assez → on l'utilise (objectif = qualité du choix)
        use_ml = ml_span >= 2.0

    if use_ml:
        ml_vals = list(ml_scores.values())
        ml_min, ml_max = min(ml_vals), max(ml_vals)
        ml_span = (ml_max - ml_min) or 1.0
        for ch in c:
            hn = (h_scores[ch] - h_min) / h_span
            mn = (ml_scores.get(ch, ml_min) - ml_min) / ml_span
            # ML plus fiable maintenant (labels par choix) — heuristique en filet
            if h_span >= 6 and abs(h_scores[ch]) >= 6:
                w_h = 0.55
            elif abs(h_scores[ch]) >= 4:
                w_h = 0.4
            else:
                w_h = 0.3
            score = w_h * hn + (1 - w_h) * mn
            combined.append((score, ch, f"ML+H ({n_ml} samples)"))
    else:
        mode = "heuristique" if not ml_scores else f"H (ML plat, {n_ml})"
        for ch in c:
            combined.append((h_scores[ch], ch, mode))

    combined.sort(key=lambda x: x[0], reverse=True)
    best_score, best, mode = combined[0]

    pl = p.lower()
    if "origine" in pl or "d'où venez-vous" in pl or "d’où venez-vous" in pl:
        return _pick(c, ["quartier populaire", "futsal", "fils de sportif"], "stats utiles buteur")
    if "adolescence" in pl or "mode de vie" in pl:
        return _pick(c, ["hygiène de pro", "hygiene"], "forme + recruteurs")
    if "entourage" in pl and re.search(r"intérêt|interet|contrat|gère|gere", pl):
        return _pick(c, ["agent ambitieux"], "monte plus vite")
    if "clubs vous ont repéré" in pl or "recruteurs ont observé" in pl:
        return _pick(
            c,
            ["rennes", "metz", "sociedad", "lyon", "lille", "monaco"],
            "bon club formateur",
            avoid=["paris", "quimper", "aubervilliers"],
        )
    if re.search(r"poste|position|où jouez|ou jouez", pl) and any(
        x in " ".join(c).lower() for x in ("attaquant", "gardien", "défenseur", "defenseur", "milieu")
    ):
        return _pick(c, ["attaquant", "ailier", "meneur", "milieu offensif"], "plus de stats buteur")

    why = mode
    if h_scores[best] >= 5:
        why += " · signal pro/safe"
    elif h_scores[best] <= 0:
        why += " · moins risqué"
    else:
        why += " · meilleur rang disponible"
    return best, f"{why} (h={h_scores[best]:.1f})"


def _pick(
    choices: list[str],
    keywords: list[str],
    reason: str,
    avoid: list[str] | None = None,
) -> tuple[str, str]:
    avoid = avoid or []
    for choice in choices:
        cl = choice.lower()
        if any(a in cl for a in avoid):
            continue
        if any(k in cl for k in keywords):
            return (choice, reason)
    for choice in choices:
        cl = choice.lower()
        if not any(a in cl for a in avoid):
            return (choice, reason + " (approx)")
    return (choices[0], reason + " (defaut)")
