"""Credits reserved by in-flight prompt-suggestion evaluations. Split out of `prompt_evaluation` so
the quota gate can import it without pulling in anything that reaches back into the temporal package.
"""

import datetime as dt
from typing import Any
from uuid import UUID

from django.utils import timezone

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion

# Sized for a full run at the session cap (100 sessions, 4 concurrent, a few minutes each).
# Lives here rather than temporal/constants so quota-path imports don't drag in the temporal package.
EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT = dt.timedelta(hours=3)

# Slack past the workflow execution timeout before a still-"running" evaluation is considered dead.
_EVALUATION_RUNNING_GRACE = dt.timedelta(minutes=5)


def evaluation_in_flight(evaluation: Any) -> bool:
    """True while a running evaluation's workflow can still be alive. Past the timeout nothing is left to finalize it."""
    if not isinstance(evaluation, dict) or evaluation.get("status") != "running":
        return False
    try:
        started_at = dt.datetime.fromisoformat(str(evaluation.get("started_at") or ""))
    except ValueError:
        return False
    if started_at.tzinfo is None:
        return False
    return timezone.now() - started_at < EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT + _EVALUATION_RUNNING_GRACE


def in_flight_evaluation_credits(organization_id: UUID) -> int:
    """Credits that running evaluations still plan to charge. Settled sessions hold a receipt or never charge."""
    rows = ReplayScannerPromptSuggestion.objects.filter(
        team__organization_id=organization_id, evaluation__status="running"
    ).values_list("evaluation", "scanner__model")
    total = 0
    for evaluation, scanner_model in rows:
        if not isinstance(evaluation, dict) or not evaluation_in_flight(evaluation):
            continue
        unsettled = max(0, int(evaluation.get("total") or 0) - len(evaluation.get("results") or []))
        # Receipts bill the model frozen at workflow start, so the reservation prices from the same frozen
        # value. Stubs written before the field existed fall back to the scanner's current model.
        model = evaluation.get("model") or scanner_model
        total += unsettled * observation_credits_for_model(model or "")
    return total
