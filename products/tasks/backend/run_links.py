"""Where a run can be opened, and what produced it.

Both destinations hang off the task creator's PostHog Code access and fail closed: the
app is rolled out via cohort + invite redemption, so surfacing deep links to people who
can't open them sends them into an install flow we don't want to scale, and an error from
the flag service means "no link" rather than "link anyway".

The web URL is the one that works everywhere, mobile included. The desktop scheme is
offered alongside it, never instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from posthog.temporal.common.logger import get_logger
from posthog.utils import absolute_uri

from products.slack_app.backend.services.message_footer import RunProvenance
from products.tasks.backend.access import has_tasks_access

if TYPE_CHECKING:
    from posthog.models.user import User

logger = get_logger(__name__)

# The scheme a production desktop install registers. Dev builds register
# `posthog-code-dev://` instead, which the server can't tell apart from here, so links
# minted server-side always target the production build.
DESKTOP_URL_SCHEME = "posthog-code"


def run_provenance(task_run) -> RunProvenance:
    """Describe an already-loaded run for a footer. Pure apart from the access gate.

    Which model ran is not access-sensitive, so it survives the gate; only the links,
    which lead somewhere the reader may not be able to open, do not.
    """
    from products.tasks.backend.facade.run_config import (
        parse_run_state,  # noqa: PLC0415 — keeps the tasks ORM off this import path
    )

    state = parse_run_state(task_run.state)
    if not _viewer_has_posthog_code_access(task_run.task.created_by):
        return RunProvenance(model=state.model, reasoning_effort=state.reasoning_effort)

    return RunProvenance(
        task_url=_task_url(task_run.task.team_id, task_run.task_id, task_run.id),
        # Task-scoped, matching the desktop app's own task route — the run id has no
        # equivalent there.
        desktop_url=f"{DESKTOP_URL_SCHEME}://task/{task_run.task_id}",
        model=state.model,
        reasoning_effort=state.reasoning_effort,
    )


def load_run_provenance(run_id: str | UUID | None) -> RunProvenance:
    """Same, for a caller that doesn't already hold the run.

    Never raises: a footer is the last thing appended to an answer that is already
    written, so failing to describe the run must not cost the reader the answer.
    """
    from products.tasks.backend.models import TaskRun  # noqa: PLC0415 — keeps the tasks ORM off this import path

    if not run_id:
        return RunProvenance()
    try:
        task_run = TaskRun.objects.select_related("task", "task__created_by").get(id=run_id)
        return run_provenance(task_run)
    except Exception:
        logger.exception("run_provenance_load_failed", run_id=str(run_id))
        return RunProvenance()


def _task_url(team_id: int, task_id: str | UUID, run_id: str | UUID) -> str:
    path = f"/project/{team_id}/tasks/{task_id}?runId={run_id}"
    # Mirrors the Slack onboarding links: in local dev the tunnel is what makes a link
    # posted into Slack actually reachable.
    if settings.DEBUG and settings.NGROK_URL:
        return f"{settings.NGROK_URL.rstrip('/')}{path}"
    return absolute_uri(path)


def _viewer_has_posthog_code_access(viewer: User | None) -> bool:
    if viewer is None:
        return False
    try:
        return has_tasks_access(viewer)
    except Exception:
        logger.exception("run_provenance_access_check_failed", user_id=getattr(viewer, "id", None))
        return False
