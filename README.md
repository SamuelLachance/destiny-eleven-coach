# Destiny Eleven Coach

Coach pour [Destiny Eleven](https://destinyeleven.com/) : recommande le choix qui maximise ta carrière.

## Site live (GitHub Pages)

**https://samuellachance.github.io/destiny-eleven-coach/**

Colle un dilemme + les options → recommandation (oracle des événements du jeu + heuristique anti-retraite précoce).

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

## Licence

Usage perso / éducatif. Destiny Eleven appartient à ses auteurs.
