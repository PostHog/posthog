import logging
from uuid import UUID

from products.wizard.backend.logic.runs import store
from products.wizard.backend.observability.tracing import annotate_run_span, wizard_span
from products.wizard.backend.temporal import client as temporal_client
from products.wizard.backend.temporal.errors import WizardTemporalError

logger = logging.getLogger(__name__)


@wizard_span("wizard.run.cancel")
def dispatch_cancellation(team_id: int, run_id: UUID) -> bool:
    annotate_run_span(team_id, run_id)
    if store.get_workflow_id(team_id, run_id) is None:
        return False

    try:
        with wizard_span("wizard.run.cancel_workflow"):
            temporal_client.cancel_wizard_run_workflow(run_id)
    except WizardTemporalError:
        logger.exception("wizard_run_cancellation_failed", extra={"team_id": team_id, "run_id": str(run_id)})
        return False

    store.mark_cancellation_dispatched(team_id, run_id)

    return True
