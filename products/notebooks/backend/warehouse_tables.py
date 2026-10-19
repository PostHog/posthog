"""Saving a Python cell's result dataframe as a data warehouse table.

The sandbox uploads the frame to a staging object and reports the upload in the run's callback.
The callback records the save as pending and hands the rest to a Celery task, because reading the
staged object's columns is a ClickHouse round trip that can take longer than the callback may.
"""

from typing import Any, TypedDict

from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.api import sync_notebook_table_to_dag
from products.data_warehouse.backend.facade.api import NotebookTableError, save_notebook_table
from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sql_v2_state import upstream_hogql_queries

logger = structlog.get_logger(__name__)


class WarehouseTableOutcome(TypedDict, total=False):
    name: str
    error: str | None
    pending: bool


def upload_outcome(table_name: str, upload: Any) -> WarehouseTableOutcome:
    """The outcome to store with the run once the sandbox reports its upload.

    The sandbox runs user code, so it only reports whether the upload worked. The table name
    always comes from the run row.
    """
    if not isinstance(upload, dict) or upload.get("ok") is not True:
        error = upload.get("error") if isinstance(upload, dict) else None
        return {"name": table_name, "error": str(error or "The sandbox didn't upload the dataframe.")}
    return {"name": table_name, "error": None, "pending": True}


def finish_warehouse_table_save(team_id: int, run_id: str) -> None:
    """Publish the run's staged upload as its warehouse table, and store how that went on the run."""
    run = NotebookNodeRun.objects.for_team(team_id).select_related("notebook").filter(id=run_id).first()
    if run is None or not run.warehouse_table_name:
        return
    name = run.warehouse_table_name
    table_id: str | None = None
    outcome: WarehouseTableOutcome
    try:
        table_id = save_notebook_table(team_id, name, run.user_id, str(run.id))
        outcome = {"name": name, "error": None}
    except NotebookTableError as e:
        outcome = {"name": name, "error": str(e)}
    except Exception as e:
        capture_exception(e)
        outcome = {"name": name, "error": "The warehouse table couldn't be saved."}

    with transaction.atomic():
        locked = NotebookNodeRun.objects.for_team(team_id).select_for_update().get(id=run.id)
        envelope = dict(locked.envelope) if isinstance(locked.envelope, dict) else {}
        envelope["warehouse_table"] = outcome
        locked.envelope = envelope
        locked.save(update_fields=["envelope", "updated_at"])

    if table_id is None:
        return
    try:
        sync_notebook_table_to_dag(
            team_id,
            name,
            table_id,
            upstream_hogql_queries(team_id, run.notebook, run.node_id),
            run.notebook.short_id,
            run.node_id,
        )
    except Exception as e:
        # The table is saved. Lineage is extra, so a failure here must not report the save as failed.
        capture_exception(e)
