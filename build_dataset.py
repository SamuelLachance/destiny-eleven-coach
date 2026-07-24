"""
Construit un dataset de QUALITÉ PAR CHOIX (pas score final de carrière).

C'est le fix principal: avant, tous les choix d'une partie avaient le même
label (= score final) → le modèle ne savait pas les départager.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from bootstrap_data import SCENARIOS
from expand_and_train import EXTRA

OUT = Path("data/choice_samples.jsonl")
GAMES = Path("data/games.jsonl")


def _label_for_index(i: int, best_i: int, good: float, bad: float, n: int) -> float:
    if i == best_i:
        return float(good)
    if n == 2:
        return float(bad)
    # options intermédiaires: un cran au-dessus du pire
    return float(bad + (good - bad) * 0.22)


def _noise_text(rng: random.Random, s: str) -> str:
    """Légères variantes pour généraliser."""
    if rng.random() < 0.5:
        s = s.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a")
    if rng.random() < 0.25:
        s = re.sub(r"\s+", " ", s)
    return s


def samples_from_scenarios(scenarios, rng: random.Random, n_aug: int = 2) -> list[dict]:
    rows = []
    for prompt, choices, best_i, good, bad in scenarios:
        n = len(choices)
        for i, ch in enumerate(choices):
            lab = _label_for_index(i, best_i, good, bad, n)
            rows.append(
                {
                    "prompt": prompt,
                    "choice": ch,
                    "label": lab,
                    "is_best": i == best_i,
                    "choices": choices,
                    "source": "scenario",
                }
            )
            for _ in range(n_aug):
                rows.append(
                    {
                        "prompt": _noise_text(rng, prompt),
                        "choice": _noise_text(rng, ch),
                        "label": lab + rng.uniform(-1.5, 1.5),
                        "is_best": i == best_i,
                        "choices": choices,
                        "source": "aug",
                    }
                )
    return rows


def samples_from_games(path: Path) -> list[dict]:
    """Si une partie a choice_quality / is_best, on les utilise."""
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                g = json.loads(line)
            except Exception:
                continue
            for d in g.get("decisions") or []:
                cq = d.get("choice_quality")
                chosen = d.get("chosen")
                prompt = d.get("prompt") or ""
                if cq is None or not chosen:
                    continue
                rows.append(
                    {
                        "prompt": prompt,
                        "choice": chosen,
                        "label": float(cq),
                        "is_best": bool(d.get("is_best", False)),
                        "choices": d.get("choices") or [chosen],
                        "source": "game",
                    }
                )
    return rows


def main() -> None:
    rng = random.Random(11)
    all_scen = list(SCENARIOS) + list(EXTRA)
    rows = samples_from_scenarios(all_scen, rng, n_aug=4)
    rows += samples_from_games(GAMES)

    # contrast: dupliquer oracles purs
    for prompt, choices, best_i, good, bad in all_scen:
        for i, ch in enumerate(choices):
            rows.append(
                {
                    "prompt": prompt,
                    "choice": ch,
                    "label": float(good if i == best_i else bad),
                    "is_best": i == best_i,
                    "choices": choices,
                    "source": "oracle_contrast",
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_best = sum(1 for r in rows if r["is_best"])
    print(f"Wrote {len(rows)} choice samples ({n_best} best) -> {OUT}")
    print(f"Scenarios covered: {len(all_scen)}")


if __name__ == "__main__":
    main()
