from __future__ import annotations

import uuid
import logging
from functools import partial

from django.db import transaction

from posthog.exceptions_capture import capture_exception

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.slack_delivery import (
    MAX_SLACK_NOTE_SNAPSHOT_LEN,
    ScoutSlackOutputType,
    get_scout_slack_destination,
)
from products.signals.backend.tasks import enqueue_scout_slack_delivery

logger = logging.getLogger(__name__)


def queue_configured_scout_slack_delivery(
    *,
    run_id: uuid.UUID | str,
    output_type: ScoutSlackOutputType,
    output_id: str,
    delivery_id: str | None = None,
    edit_note: str | None = None,
) -> None:
    """Snapshot a run's configured destination and enqueue delivery after the current commit.

    `edit_note` marks a note-only report edit: the delivery posts the note as an update instead of
    re-posting the report message the channel already has. Snapshotted here (rather than re-read at
    send time) because the report's work log can gain further notes before the worker runs."""
    try:
        run = SignalScoutRun.all_teams.select_related("scout_config").filter(pk=run_id).first()
        if run is None:
            logger.warning("signals_scout.slack_delivery_run_missing", extra={"run_id": str(run_id)})
            return

        destination = get_scout_slack_destination(
            run.scout_config.output_destinations if run.scout_config is not None else None
        )
        if destination is None:
            return

        transaction.on_commit(
            partial(
                enqueue_scout_slack_delivery,
                team_id=run.team_id,
                output_type=output_type,
                output_id=output_id,
                run_id=str(run.id),
                delivery_id=delivery_id or str(uuid.uuid4()),
                integration_id=destination.integration_id,
                channel=destination.channel,
                edit_note=edit_note[:MAX_SLACK_NOTE_SNAPSHOT_LEN] if edit_note is not None else None,
                thread_reports=destination.thread_reports,
            ),
            robust=True,
        )
    except Exception as exc:
        capture_exception(
            exc,
            {
                "run_id": str(run_id),
                "output_type": output_type,
                "output_id": output_id,
            },
        )
        logger.exception(
            "signals_scout.slack_delivery_queue_failed",
            extra={"run_id": str(run_id), "output_type": output_type, "output_id": output_id},
        )
