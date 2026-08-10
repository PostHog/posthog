"""The muted line under a finished reply: where to open the run, what produced it, and
where to change that.

The whole concern lives here — what the footer can say, how it is gathered, and how it
renders. The tasks product is reached only through its facade, so no ORM model crosses
the boundary and the run is described by a DTO.

Rendering is pure: `reply_footer_block` needs no client and no database, so the footer's
shape is testable on its own. `SlackThreadHandler` owns the flag gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings

import structlog

from posthog.models.user import User
from posthog.utils import absolute_uri

from products.slack_app.backend.services.blocks import context_block
from products.slack_app.backend.services.model_catalogue import describe_run_model

logger = structlog.get_logger(__name__)

# The scheme a production desktop install registers. Dev builds register
# `posthog-code-dev://` instead, which the server can't tell apart from here, so links
# minted server-side always target the production build.
DESKTOP_URL_SCHEME = "posthog-code"


@dataclass(frozen=True)
class RunFooter:
    """What a reply can say about the run behind it.

    Constant for the life of a handler, so it is supplied once at construction rather
    than threaded through every posting method. An empty instance is the "say nothing"
    case, which is what every caller outside the footer rollout gets.
    """

    task_url: str | None = None
    desktop_url: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None

    def has_content(self) -> bool:
        """Whether this would render as anything.

        A caller checks it to skip the flag lookups behind a footer that can't appear.
        Spelled out rather than given as ``__bool__`` so that ``footer or RunFooter()``
        keeps meaning "None-coalesce" and cannot silently discard a partial instance.
        """
        return any((self.task_url, self.desktop_url, self.model))


def load_run_footer(run_id: str | UUID | None) -> RunFooter:
    """Describe a run for the footer.

    Never raises: the footer is the last thing added to an answer that is already
    written, so failing to describe the run must not cost the reader the answer.

    Both links hang off the task creator's PostHog Code access and fail closed — the app
    is rolled out via cohort + invite redemption, so surfacing deep links to people who
    can't open them sends them into an install flow we don't want to scale. Which model
    ran is not access-sensitive and survives the gate.
    """
    # Deferred so the tasks product stays off this module's import path, matching
    # `model_catalogue`.
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415
    from products.tasks.backend.facade.run_config import parse_run_state  # noqa: PLC0415

    if not run_id:
        return RunFooter()
    try:
        run = get_task_run(run_id)
        if run is None:
            return RunFooter()
        state = parse_run_state(run.state)
        if not _creator_has_posthog_code_access(run.created_by_id):
            return RunFooter(model=state.model, reasoning_effort=state.reasoning_effort)
        return RunFooter(
            task_url=_task_url(run.team_id, run.task_id, run.id),
            # Task-scoped, matching the desktop app's own task route — the run id has no
            # equivalent there.
            desktop_url=f"{DESKTOP_URL_SCHEME}://task/{run.task_id}",
            model=state.model,
            reasoning_effort=state.reasoning_effort,
        )
    except Exception:
        logger.exception("slack_app_run_footer_load_failed", run_id=str(run_id))
        return RunFooter()


def reply_footer_block(footer: RunFooter, configure_url: str | None = None) -> dict[str, Any] | None:
    """The footer as a `context` block, or `None` when there is nothing to say.

    The answer itself is the message, so this is muted rather than competing with the
    prose. A run with no links and no pinned model contributes no segments and gets no
    trailing line at all.
    """
    segments: list[str] = []
    if footer.task_url:
        segments.append(f"<{footer.task_url}|View on web>")
    if footer.desktop_url:
        segments.append(f"<{footer.desktop_url}|View on desktop>")
    if footer.model:
        segments.append(describe_run_model(footer.model, footer.reasoning_effort))
    if configure_url:
        segments.append(f"<{configure_url}|Configure>")
    if not segments:
        return None
    return context_block(" · ".join(segments))


def _task_url(team_id: int, task_id: UUID, run_id: UUID) -> str:
    path = f"/project/{team_id}/tasks/{task_id}?runId={run_id}"
    # Mirrors the Slack onboarding links: in local dev the tunnel is what makes a link
    # posted into Slack actually reachable.
    if settings.DEBUG and settings.NGROK_URL:
        return f"{settings.NGROK_URL.rstrip('/')}{path}"
    return absolute_uri(path)


def _creator_has_posthog_code_access(user_id: int | None) -> bool:
    from products.tasks.backend.facade.access import has_tasks_access  # noqa: PLC0415

    if user_id is None:
        return False
    user = User.objects.filter(id=user_id).first()
    if user is None:
        return False
    try:
        return has_tasks_access(user)
    except Exception:
        logger.exception("slack_app_run_footer_access_check_failed", user_id=user_id)
        return False
