"""Evalue l'accuracy de decision du modele / heuristique / blend."""

from __future__ import annotations

import numpy as np

from advisor import _score_choice, advise
from bootstrap_data import SCENARIOS
from expand_and_train import EXTRA
from ml_model import load_model, ml_rank_choices


def main() -> None:
    b = load_model(force=True)
    print("=== MODELE SAUVE ===")
    print(f"samples entraines: {b.get('n')}")
    print(f"MAE holdout (qualite): {b.get('mae'):.2f}")
    print(f"top-1 holdout (split): {100 * b.get('rank_acc_holdout', 0):.1f}%")
    print(f"top-1 all (meme data): {100 * b.get('rank_acc_all', 0):.1f}%")
    print(f"marge moyenne best-min: {b.get('margin'):.1f} pts")
    print(f"objectif: {b.get('objective')}")

    scenarios = list(SCENARIOS) + list(EXTRA)
    ml_ok = h_ok = blend_ok = 0
    ml_margins = []
    errors = []

    for prompt, choices, best_i, good, bad in scenarios:
        best = choices[best_i]
        ranked = ml_rank_choices(prompt, choices)
        ml_pick = ranked[0][1]
        pred_map = {c: s for s, c in ranked}
        ml_margins.append(pred_map[best] - min(pred_map.values()))
        h_pick = max(choices, key=lambda ch: _score_choice(ch, prompt))
        blend_pick, _ = advise(prompt, choices)
        ml_ok += ml_pick == best
        h_ok += h_pick == best
        blend_ok += blend_pick == best
        if ml_pick != best:
            errors.append((prompt, best, ml_pick))

    n = len(scenarios)
    print()
    print("=== ACCURACY DECISIONS (scenarios oracle) ===")
    print(f"dilemmes testes: {n}")
    print(f"ML seul top-1:     {ml_ok}/{n} = {100 * ml_ok / n:.1f}%")
    print(f"Heuristique seule: {h_ok}/{n} = {100 * h_ok / n:.1f}%")
    print(f"Coach blend ML+H:  {blend_ok}/{n} = {100 * blend_ok / n:.1f}%")
    print(f"marge ML moyenne (best - pire): {float(np.mean(ml_margins)):.1f}")
    print()
    print("Chance aleatoire approx (2-4 options): ~25-50%")
    print()
    print("=== ERREURS ML ===")
    for prompt, best, ml_pick in errors[:10]:
        print(f"- {prompt[:72]}")
        print(f"  oracle: {best}")
        print(f"  ML:     {ml_pick}")
    print(f"(total erreurs ML: {len(errors)})")


if __name__ == "__main__":
    main()
