"""The outcomes of the ranking model that the API, the inbox sorts and the MCP tools show by name.

The served model scores more heads than these. The other heads stay readable in `ranking_score` artefacts and
through their `ranking_<head>` ordering fields, but the `ranking` field, the ranking filters and the outcomes list
show only the outcomes here, in this order. Add an outcome here to show it everywhere at once.

A public name can differ from the model head it reads. `fix` reads the `fixed` head, because `fixed` next to a
report's status reads as "this was fixed". Training, model metadata and artefacts keep the head name.

Horizon and cohort come from the served model's metadata, not from this file, so they follow the model.
"""

from typing import Literal, get_args

from django.db.models import TextChoices

from posthog.dataclasses import frozen

PublicOutcomeName = Literal["open", "action", "fix"]


@frozen
class PublicOutcome:
    outcome: PublicOutcomeName
    model_head: str
    label: str
    description: str


PUBLIC_OUTCOMES: tuple[PublicOutcome, ...] = (
    PublicOutcome(
        outcome="open",
        model_head="open",
        label="Open",
        description="Chance that a person opens the report within the horizon. A prediction, not the report's state.",
    ),
    PublicOutcome(
        outcome="action",
        model_head="action",
        label="Action",
        description=(
            "Chance that a person or their agent acts on the report within the horizon. "
            "A prediction, not the report's state."
        ),
    ),
    PublicOutcome(
        outcome="fix",
        model_head="fixed",
        label="Fix",
        description=(
            "Chance that someone fixes the problem the report describes within the horizon. "
            "A prediction, not the report's status."
        ),
    ),
)

PUBLIC_OUTCOME_NAMES: tuple[PublicOutcomeName, ...] = tuple(entry.outcome for entry in PUBLIC_OUTCOMES)
MODEL_HEAD_BY_OUTCOME: dict[str, str] = {entry.outcome: entry.model_head for entry in PUBLIC_OUTCOMES}

assert PUBLIC_OUTCOME_NAMES == get_args(PublicOutcomeName), (
    "PUBLIC_OUTCOMES and PublicOutcomeName must list the same outcomes"
)


# The API's choice set for an outcome name. A Choices class gives the OpenAPI enum a stable name of its own.
class RankingOutcome(TextChoices):
    OPEN = "open"
    ACTION = "action"
    FIX = "fix"


assert tuple(RankingOutcome.values) == PUBLIC_OUTCOME_NAMES, (
    "RankingOutcome and PUBLIC_OUTCOMES must list the same outcomes"
)
