# Destiny Eleven Coach

Coach pour [Destiny Eleven](https://destinyeleven.com/) : recommande le choix qui maximise ta carrière.

## Site live (GitHub Pages)

**https://samuellachance.github.io/destiny-eleven-coach/**

- Colle un dilemme, ou
- **Mode navigateur** : ouvre le jeu + active le **favori Coach** (panneau flottant sur destinyeleven.com)

> GitHub Pages ne peut pas lancer Playwright. Le favori injecte le même coach dans la page du jeu.

## Local (Flask + navigateur auto)

```powershell
cd destiny-eleven-coach
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\python server.py
```

Ouvre http://127.0.0.1:5055 — mode navigateur Playwright avec profil persistant (`browser_profile/`).

### Réentraîner le modèle ML

```powershell
.\.venv\Scripts\python extract_and_label_all.py
.\.venv\Scripts\python train_model.py
```

## Comment ça décide

1. **Oracle** — si le dilemme est un événement exact du jeu → meilleur choix labellisé via `Engine.netImpact`
2. **Arbre de décision** — sklearn `DecisionTreeRegressor`, export JSON, tourne en JS
3. **Heuristique** — filet si l’arbre n’est pas chargé

### Anti-leak (arbre)

- CV **GroupKFold par `event_id`** (aucun événement en train et test)
- augs bruitées exclues
- dédup `(event, choix)`
- métrique officielle = **top-1 holdout CV ~64%** (chance ~45%), sans leak `event_id`

```powershell
.\.venv\Scripts\python export_decision_tree.py
```

Voir `docs/tree_train_report.json` pour le dernier rapport.
