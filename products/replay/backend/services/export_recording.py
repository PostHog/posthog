import uuid
import asyncio
import dataclasses
from datetime import timedelta

from django.conf import settings

import structlog
from temporalio import common

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect
from posthog.temporal.session_replay.export_recording.types import ExportRecordingInput

from products.replay.backend.models.exported_recording import ExportedRecording

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class ReplayActivityContext(ActivityContextBase):
    reason: str


def trigger_recording_export(
    *,
    team: Team,
    session_id: str,
    reason: str,
    user: User,
    was_impersonated: bool,
) -> ExportedRecording:
    export_record = ExportedRecording.objects.create(
        team=team,
        session_id=session_id,
        reason=reason,
        created_by=user,
    )

    try:
        temporal = sync_connect()
        workflow_input = ExportRecordingInput(exported_recording_id=export_record.id)
        workflow_id = f"export-recording-{export_record.id}-{uuid.uuid4()}"

        asyncio.run(
            temporal.start_workflow(
                "export-recording",
                workflow_input,
                id=workflow_id,
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                retry_policy=common.RetryPolicy(
                    maximum_attempts=2,
                    initial_interval=timedelta(minutes=1),
                ),
            )
        )
    except Exception:
        export_record.status = ExportedRecording.Status.FAILED
        export_record.error_message = "Failed to start the export workflow"
        export_record.save(update_fields=["status", "error_message"])
        raise

    # The workflow has started; an audit-log write failure must not fail the export
    # (which would 502 and prompt a retry that starts a duplicate workflow).
    try:
        log_activity(
            organization_id=team.organization_id,
            team_id=team.id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=session_id,
            scope="Replay",
            activity="exported",
            detail=Detail(
                name=f"Session replay {session_id}",
                short_id=session_id,
                type="admin_export",
                context=ReplayActivityContext(reason=reason),
            ),
        )
    except Exception:
        logger.exception("export_recording_activity_log_failed", team_id=team.id, session_id=session_id)

    return export_record
