"""Dimension 1: models moved into products/."""

from __future__ import annotations

from pathlib import Path

from ..ast_helpers import get_model_names
from . import scores


def score_models(name: str, backend_dir: Path, assigned_model_counts: dict[str, int]) -> scores.DimensionScore:
    """Are models in products/ or still in posthog/models/?

    100 = all models in products/backend/
    0   = all models still in posthog/models/ or ee/models/
    """
    models_in_product = get_model_names(backend_dir)
    still_to_move = assigned_model_counts.get(name, 0)

    total = len(models_in_product) + still_to_move
    if total == 0:
        return scores.DimensionScore("models", 0, "no models", applicable=False)

    pct = round(100 * len(models_in_product) / total)
    if still_to_move > 0:
        detail = f"{len(models_in_product)}/{total} in product ({still_to_move} to move)"
    else:
        detail = f"{len(models_in_product)}/{total} in product"

    next_steps: list[str] = []
    skills: list[str] = []
    if still_to_move > 0:
        next_steps.append(
            f"STOP — do not attempt this move yourself. {still_to_move} model(s) still live in "
            f"posthog/models/ (or ee/models/) and need to be relocated into "
            f"products/{name}/backend/models/. Model moves require a SeparateDatabaseAndState "
            f"migration coordinated with team devex; doing it ad-hoc breaks production. Open a "
            f"request with team devex (#team-devex on Slack) referencing this product and ask "
            f"them to schedule the migration."
        )
        next_steps.append(
            "Once devex has scheduled and merged the move, the rest of the maturity dimensions "
            "(facade, presentation, boundaries) become actionable and you can tackle them yourself."
        )

    return scores.DimensionScore("models", pct, detail, next_steps=next_steps, skills=skills)
