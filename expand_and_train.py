"""Génère un gros dataset de dilemmes variés puis réentraîne."""

from __future__ import annotations

import json
import random
from pathlib import Path

from bootstrap_data import SCENARIOS, synth_game

OUT = Path("data/games.jsonl")

EXTRA = [
    (
        "Le directeur sportif propose un prêt pour gagner du temps de jeu.",
        ["Accepter le prêt en D1 étrangère", "Rester au banc du grand club", "Exiger une place de titulaire sinon départ"],
        0,
        76,
        50,
    ),
    (
        "On vous propose d'investir dans une boîte de nuit avec des potes.",
        ["Investir une grosse somme", "Refuser poliment et rester focus foot", "Mettre une petite somme pour faire plaisir"],
        1,
        80,
        35,
    ),
    (
        "Un senior casse l'ambiance et vous cible.",
        ["Répondre violemment", "Ignorer et performer à l'entraînement", "Aller voir le coach calmement"],
        2,
        77,
        40,
    ),
    (
        "Blessure musculaire légère avant un derby.",
        ["Forcer le derby", "Se déclarer inapte et soigner", "Jouer sous anti-douleurs en cachette"],
        1,
        82,
        38,
    ),
    (
        "Interview TV: on vous demande de critiquer l'arbitre.",
        ["Critiquer fort", "Rester diplomatique et collectif", "Clash l'adversaire"],
        1,
        74,
        36,
    ),
    (
        "Votre agent veut vous faire signer un sponsor douteux.",
        ["Signer pour l'argent", "Lire le contrat / vérifier", "Laisser l'agent décider seul"],
        1,
        79,
        42,
    ),
    (
        "Le coach change de système, vous perdez votre place.",
        ["Clash public", "Travailler pour reconquérir la place", "Demander à partir immédiatement sans jouer"],
        1,
        78,
        45,
    ),
    (
        "Soirée de Noël d'entreprise du sponsor, match le lendemain.",
        ["Rester jusqu'au bout", "Passer un moment puis rentrer tôt", "Ne pas y aller du tout sans prévenir"],
        1,
        73,
        48,
    ),
    (
        "On vous propose de mentir sur votre âge pour un tournoi.",
        ["Accepter", "Refuser net", "Laisser faire le staff"],
        1,
        85,
        30,
    ),
    (
        "Un proche demande un gros prêt d'argent.",
        ["Prêter sans contrat", "Refuser / aider raisonnablement avec cadre", "Donner une fortune"],
        1,
        76,
        40,
    ),
    (
        "Réseaux: une star vous tague dans une polémique.",
        ["Alimenter le drama", "Ne pas répondre / bloquer", "Répondre agressivement"],
        1,
        75,
        35,
    ),
    (
        "Le kiné dit stop, vous voulez jouer la finale.",
        ["Jouer quand même", "Suivre l'avis médical", "Négocier quelques minutes"],
        1,
        84,
        40,
    ),
    (
        "Proposition de changer de poste (ailier → 9).",
        ["Refuser par ego", "Accepter d'essayer pour l'équipe", "Menacer de partir"],
        1,
        77,
        44,
    ),
    (
        "Amende du club pour retard répété.",
        ["Contester en public", "Payer et s'excuser, être à l'heure", "Ignorer"],
        1,
        74,
        40,
    ),
    (
        "Un ami d'enfance veut devenir votre agent.",
        ["Accepter sans licence", "Exiger qu'il soit licencié / garder un pro", "Chasser l'agent actuel sans plan"],
        1,
        81,
        38,
    ),
    (
        "Le président veut vous vendre contre votre gré.",
        ["Clash public et grève", "Discuter calmement + demander garanties ou départ", "Ignorer et baisser les bras"],
        1,
        76,
        40,
    ),
    (
        "Un influenceur propose un challenge dangereux pour les vues.",
        ["Participer pour le buzz", "Refuser poliment, rester pro", "Faire une version soft risquée"],
        1,
        78,
        36,
    ),
    (
        "Le club propose un salaire plus bas mais un rôle de leader.",
        ["Refuser tout salaire bas", "Accepter si minutes + leadership clairs", "Partir sans négocier"],
        1,
        74,
        48,
    ),
    (
        "Vous ratez un penalty décisif, le vestiaire est froid.",
        ["Accuser l'arbitre", "Assumer, s'excuser, travailler les penaltys", "Poster une story défensive"],
        1,
        77,
        38,
    ),
    (
        "Proposition de dopage 'naturel' par un préparateur douteux.",
        ["Accepter pour performer", "Refuser net et signaler au staff médical", "Essayer une fois"],
        1,
        88,
        20,
    ),
    (
        "Votre famille veut gérer 100% de vos finances.",
        ["Tout leur laisser", "Garder un conseiller pro + cadre familial", "Couper les ponts"],
        1,
        75,
        42,
    ),
    (
        "Match retour C1, coach demande un pressing suicidaire.",
        ["Contester en public", "Exécuter le plan collectif", "Saboter tactiquement"],
        1,
        79,
        35,
    ),
    (
        "Une star adverse vous provoque avant le coup d'envoi.",
        ["Répondre et engager le clash", "Ignorer et se concentrer sur le match", "Le menacer dans le tunnel"],
        1,
        76,
        34,
    ),
    (
        "Le staff veut vous faire jouer ailier alors que vous êtes 9.",
        ["Refuser par ego", "Accepter d'essayer pour aider l'équipe", "Exiger un transfert immédiat"],
        1,
        77,
        44,
    ),
    (
        "Offre de cinéma / pub pendant la saison décisive.",
        ["Tout accepter pour l'argent", "Refuser ou reporter après les titres", "Faire le minimum au détriment de la forme"],
        1,
        74,
        45,
    ),
    (
        "Vous êtes isolé en sélection, moral bas.",
        ["Râler sur les réseaux", "Travailler dur, rester pro avec le groupe", "Demander à rentrer chez soi"],
        1,
        78,
        40,
    ),
    (
        "Le kiné et le coach ne sont pas d'accord sur votre disponibilité.",
        ["Forcer avec le coach", "Suivre l'avis médical", "Jouer 10 minutes en cachette"],
        1,
        83,
        39,
    ),
    (
        "Un journal people veut votre vie privée.",
        ["Tout raconter", "Rester discret, protéger la vie privée", "Clash le magazine"],
        1,
        75,
        40,
    ),
    (
        "Le club propose une prolongation moyenne mais stable.",
        ["Signer sans lire", "Négocier minutes/salaire puis décider", "Claquer la porte"],
        1,
        76,
        42,
    ),
    (
        "Vous gagnez gros au casino avec des coéquipiers.",
        ["Continuer toute la nuit", "Arrêter, rentrer, hygiène de pro", "Relancer plus gros"],
        1,
        80,
        30,
    ),
    (
        "Un dirigeant vous demande de baisser volontairement votre niveau.",
        ["Obéir pour plaire", "Refuser et rester professionnel", "Balancer publiquement tout de suite sans preuves"],
        1,
        82,
        35,
    ),
    (
        "Vous êtes appelé pour remplacer un blessé en urgence, jet-lag.",
        ["Refuser fatigué", "Répondre présent et gérer récupération", "Faire la fête en arrivant"],
        1,
        77,
        41,
    ),
    (
        "Derby: le coach veut que vous marquiez un adversaire dur.",
        ["Entrer dangereusement", "Marquer ferme mais propre", "Ignorer la consigne et faire le show"],
        1,
        74,
        38,
    ),
    (
        "Votre agent pousse un transfert flash sans vous consulter.",
        ["Suivre aveuglément", "Exiger d'être consulté et lire le dossier", "Rompre sans alternative"],
        1,
        79,
        40,
    ),
    (
        "Penalty décisif, le public scande votre nom.",
        ["Panenka légendaire", "Frapper en force assumé", "Laisser le tireur attitré"],
        1,
        78,
        40,
    ),
    (
        "Tir au but en prolongation, 1-1.",
        ["Tentative panenka", "Frapper en force au milieu/ras du sol", "Se défiler"],
        1,
        77,
        38,
    ),
    (
        "Le médecin dit 3 semaines, vous sentez que c'est jouable.",
        ["Forcer le retour", "Respecter le protocole médical", "Négocier un match amical risqué"],
        1,
        84,
        36,
    ),
    (
        "On vous propose un prêt d'argent à taux absurde.",
        ["Accepter pour le cash", "Refuser et passer par la banque/club", "Emprunter à un pote du vestiaire"],
        1,
        81,
        32,
    ),
    (
        "Un dirigeant vous offre une enveloppe pour influencer un jeune.",
        ["Prendre l'argent", "Refuser et rester clean", "Négocier plus"],
        1,
        86,
        25,
    ),
    (
        "Après un carton rouge stupide, le coach est furieux.",
        ["Répondre sèchement", "S'excuser et analyser l'erreur", "Ignorer deux jours"],
        1,
        76,
        40,
    ),
    (
        "Le club veut baisser votre salaire après une blessure longue.",
        ["Clash médiatique", "Négocier un compromis avec garanties de retour", "Accepter tout sans discuter"],
        1,
        75,
        42,
    ),
    (
        "On vous demande de boycotter un entraînement pour protester.",
        ["Boycotter", "S'entraîner et discuter en interne", "Menacer de résilier"],
        1,
        78,
        38,
    ),
    (
        "Une star vous propose de partager une soirée VIP avant un classique.",
        ["Y aller jusqu'au bout", "Saluer puis rentrer tôt", "Poster des stories toute la nuit"],
        1,
        79,
        35,
    ),
    (
        "Le préparateur physique impose un test yo-yo, vous êtes limite.",
        ["Tricher / se ménager", "Le passer honnêtement et travailler les lacunes", "Simuler une douleur"],
        1,
        77,
        40,
    ),
    (
        "Transfert: club moyen titulaire vs gros club banc + C1.",
        ["Gros club banc immédiat", "Club moyen titulaire pour progresser", "Rester sans rien négocier"],
        1,
        76,
        50,
    ),
]


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    all_scen = list(SCENARIOS) + EXTRA

    games = []
    for _ in range(320):
        # synth_game uses module SCENARIOS — monkeypatch via local copy
        games.append(_synth(rng, all_scen))

    for prompt, choices, best_i, good, bad in all_scen:
        games.append(_one(prompt, choices, best_i, good, "oracle"))
        games.append(_one(prompt, choices, (best_i + 1) % len(choices), bad, "worst"))

    with OUT.open("w", encoding="utf-8") as f:
        for g in games:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"Wrote {len(games)} games")


def _one(prompt, choices, idx, score, policy):
    return {
        "ts": policy,
        "policy": policy,
        "final_score": score,
        "n_decisions": 1,
        "decisions": [
            {
                "step": 0,
                "prompt": prompt,
                "choices": choices,
                "chosen": choices[idx],
                "policy": policy,
            }
        ],
        "retired": True,
    }


def _synth(rng, scenarios):
    n = rng.randint(8, 16)
    decisions = []
    score = 55.0
    for step in range(n):
        prompt, choices, best_i, good, bad = rng.choice(scenarios)
        indexed = list(enumerate(choices))
        rng.shuffle(indexed)
        new_choices = [c for _, c in indexed]
        new_best = next(i for i, (oi, _) in enumerate(indexed) if oi == best_i)
        if rng.random() < 0.8:
            chosen_i = new_best
            score += (good - 55) / n + rng.uniform(-1, 2)
        else:
            chosen_i = rng.choice([i for i in range(len(new_choices)) if i != new_best])
            score += (bad - 55) / n + rng.uniform(-2, 1)
        decisions.append(
            {
                "step": step,
                "prompt": prompt,
                "choices": new_choices,
                "chosen": new_choices[chosen_i],
                "policy": "bootstrap",
            }
        )
    return {
        "ts": "bootstrap",
        "policy": "bootstrap",
        "final_score": int(max(20, min(95, round(score)))),
        "n_decisions": len(decisions),
        "decisions": decisions,
        "retired": True,
    }


if __name__ == "__main__":
    main()
