"""What each public outcome of the served ranking model means for one team: horizon, cohort, base rate, readability.

The values come from the model metadata that the team's latest `ranking_score` artefact copies, so the answer
needs no model store and follows the model that scored the team's reports.
"""

from typing import Any

import structlog

from products.signals.backend.artefact_schemas import RankingScore
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.ranking.public_outcomes import PUBLIC_OUTCOMES

logger = structlog.get_logger(__name__)


def served_outcomes(team_id: int) -> tuple[str | None, list[dict[str, Any]]]:
    """The served model key and one entry per public outcome, or `(None, [])` when the team has no readable score."""
    from products.signals.backend.ranking.model_contract import (  # noqa: PLC0415 — keeps numpy and pandas off the API import path
        classification_thresholds,
        readable_head_names,
    )

    art = (
        SignalReportArtefact.objects.filter(team_id=team_id, type=SignalReportArtefact.ArtefactType.RANKING_SCORE)
        .order_by("-created_at")
        .only("id", "content")
        .first()
    )
    if art is None:
        return None, []
    try:
        score = RankingScore.model_validate_json(art.content)
        metadata = score.results[score.served_key].metadata
        thresholds = classification_thresholds(metadata)
        readable = readable_head_names(metadata)
    except (ValueError, KeyError, TypeError, AttributeError):
        logger.warning("signals.ranking_outcomes.invalid_content", team_id=team_id, artefact_id=str(art.id))
        return None, []
    recipe = metadata.get("recipe")
    recipe_heads = recipe.get("heads") if isinstance(recipe, dict) else None
    outcomes = []
    for entry in PUBLIC_OUTCOMES:
        # A model trained before the recipe was saved has no horizon or cohort, and no value may stand in for it.
        head_recipe = recipe_heads.get(entry.model_head) if isinstance(recipe_heads, dict) else None
        if not isinstance(head_recipe, dict):
            head_recipe = {}
        horizon_days = head_recipe.get("horizon_days")
        cohort = head_recipe.get("cohort")
        outcomes.append(
            {
                "outcome": entry.outcome,
                "label": entry.label,
                "description": entry.description,
                "horizon_days": horizon_days if isinstance(horizon_days, int) else None,
                "cohort": cohort if isinstance(cohort, str) else None,
                "base_rate": thresholds.get(entry.model_head),
                "readable": entry.model_head in readable,
            }
        )
    return score.served_key, outcomes
