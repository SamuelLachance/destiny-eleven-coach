"""
Dataset bootstrap: situations typiques Destiny Eleven + label score final.
Sert de distillation de la politique optimale (discipline / progression).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT = Path("data/games.jsonl")

# (prompt, choices, best_index, score_if_best, score_if_wrong)
SCENARIOS = [
    (
        "Rite d'initiation vestiaire: chanter devant les cadres.",
        ["Chanter à pleins poumons, faux mais fier", "Refuser, paralysé"],
        0,
        72,
        48,
    ),
    (
        "Un agent FIFA certifié demande 2000 euros de frais de dossier.",
        ["Payer : on ne rate pas une telle chance", "Vérifier sa licence auprès de la fédération"],
        1,
        78,
        35,
    ),
    (
        "Votre temps de jeu famélique alerte tout le marché.",
        ["Rester à Rennes", "D2 Bari — 70 k€/an · indemnité 1,5 M€", "D2 Vitesse — 40 k€/an"],
        1,
        74,
        50,
    ),
    (
        "Penalty à la 88e du derby, 1-1. Le virage scande votre nom.",
        [
            "AUTORITÉ: Prendre le ballon",
            "COLLECTIF: Laisser le tireur attitré",
            "LÉGENDAIRE: Panenka",
            "Le prendre et frapper en force",
        ],
        3,
        76,
        42,
    ),
    (
        "Douleur vive au genou à l'entraînement. Le staff hésite.",
        ["Forcer pour être titulaire samedi", "Repos et voir le médecin", "Cacher la douleur"],
        1,
        80,
        38,
    ),
    (
        "Les coéquipiers proposent une soirée en boîte après la victoire.",
        ["Y aller, juste un verre", "Rentrer dormir, hygiène de pro", "Profiter à fond jusqu'au matin"],
        1,
        77,
        40,
    ),
    (
        "Le coach vous critique en public après un match moyen.",
        ["L'engueuler devant le vestiaire", "Écouter, travailler plus", "Ignorer et poster sur les réseaux"],
        1,
        79,
        36,
    ),
    (
        "Un journaliste vous pousse à clasher un coéquipier.",
        ["Clash, ça fait le buzz", "Rester discret et collectif", "Insulter le journaliste"],
        1,
        75,
        34,
    ),
    (
        "Offre d'un club élite mais vous serez remplaçant.",
        ["Accepter Paris élite banc", "Rester où je suis titulaire", "Demander des garanties de temps de jeu"],
        2,
        73,
        52,
    ),
    (
        "Convocation en sélection nationale.",
        ["Refuser pour reposer", "Répondre présent", "Faire la fête avant le rassemblement"],
        1,
        82,
        45,
    ),
    (
        "Votre adolescence forge discipline et réputation.",
        ["Hygiène de pro", "Équilibré", "La belle vie"],
        0,
        70,
        45,
    ),
    (
        "Qui gère vos intérêts avant le premier contrat ?",
        ["Famille encadrante", "Agent ambitieux", "La bande du quartier"],
        1,
        71,
        48,
    ),
    (
        "Origine avant les projecteurs.",
        ["Centre de formation classique", "Quartier populaire", "Prodige du futsal", "Révélé sur le tard"],
        1,
        69,
        50,
    ),
    (
        "Les clubs vous ont repéré, potentiel 4 étoiles.",
        ["Quimper régional", "Metz D2", "Rennes D1", "Paris élite concurrence féroce"],
        2,
        73,
        55,
    ),
    (
        "Un pigiste local veut écrire votre biographie un jour.",
        ["Promettre, poignée de main", "Sourire sans promettre"],
        0,
        68,
        58,
    ),
    (
        "Fin de contrat, trois offres: confort, défi, argent.",
        [
            "Rester au club actuel pour le confort",
            "Signer dans un plus gros club pour jouer la C1",
            "Prendre le max d'argent en championnat faible",
        ],
        1,
        81,
        50,
    ),
    (
        "Vous êtes fatigué, 3 matches en 8 jours.",
        ["Exiger de jouer quand même", "Demander une rotation / repos", "Sortir en boîte pour décompresser"],
        1,
        76,
        40,
    ),
    (
        "Polémique sur les réseaux après un geste d'énervement.",
        ["Alimenter la polémique", "S'excuser et tourner la page", "Attaquer les haters"],
        1,
        74,
        37,
    ),
    (
        "Le staff propose une séance vidéo supplémentaire.",
        ["Sécher la séance", "Participer et apprendre", "Râler puis y aller"],
        1,
        75,
        46,
    ),
    (
        "Un senior vous humilie à l'entraînement.",
        ["Se battre", "Répondre sur le terrain en travaillant", "Se plaindre aux médias"],
        1,
        78,
        35,
    ),
]


def synth_game(rng: random.Random) -> dict:
    # sample 8-14 decisions from scenarios (with replacement variants)
    n = rng.randint(8, 14)
    decisions = []
    score = 55.0
    for step in range(n):
        prompt, choices, best_i, good, bad = rng.choice(SCENARIOS)
        # sometimes shuffle choices
        indexed = list(enumerate(choices))
        rng.shuffle(indexed)
        new_choices = [c for _, c in indexed]
        new_best = next(i for i, (oi, _) in enumerate(indexed) if oi == best_i)

        # follow optimal most of the time, else mistake
        if rng.random() < 0.75:
            chosen_i = new_best
            score += (good - 55) / n + rng.uniform(-1, 2)
        else:
            wrong = [i for i in range(len(new_choices)) if i != new_best]
            chosen_i = rng.choice(wrong)
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

    final = int(max(20, min(95, round(score + rng.uniform(-3, 3)))))
    return {
        "ts": "bootstrap",
        "policy": "bootstrap",
        "final_score": final,
        "n_decisions": len(decisions),
        "decisions": decisions,
        "retired": True,
    }


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # keep any existing live games
    existing = []
    if OUT.exists():
        existing = [ln for ln in OUT.read_text(encoding="utf-8").splitlines() if ln.strip()]

    rng = random.Random(42)
    games = [synth_game(rng) for _ in range(120)]
    # also add pure optimal / pure bad extremes
    for prompt, choices, best_i, good, bad in SCENARIOS:
        decisions_good = [
            {
                "step": 0,
                "prompt": prompt,
                "choices": choices,
                "chosen": choices[best_i],
                "policy": "oracle",
            }
        ]
        decisions_bad = [
            {
                "step": 0,
                "prompt": prompt,
                "choices": choices,
                "chosen": choices[(best_i + 1) % len(choices)],
                "policy": "worst",
            }
        ]
        games.append(
            {
                "ts": "oracle",
                "policy": "oracle",
                "final_score": good,
                "n_decisions": 1,
                "decisions": decisions_good,
                "retired": True,
            }
        )
        games.append(
            {
                "ts": "worst",
                "policy": "worst",
                "final_score": bad,
                "n_decisions": 1,
                "decisions": decisions_bad,
                "retired": True,
            }
        )

    with OUT.open("w", encoding="utf-8") as f:
        for ln in existing:
            # drop empty live fails
            try:
                g = json.loads(ln)
            except Exception:
                continue
            if g.get("final_score") is None and not g.get("decisions"):
                continue
            f.write(ln + "\n")
        for g in games:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    print(f"Wrote {len(games)} bootstrap games (+ kept live) -> {OUT}")


if __name__ == "__main__":
    main()
