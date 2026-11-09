"""Components the presenter adds under a finished agent answer.

Any caller with a posted answer can run it. Best-effort: a failure returns no presentation,
and the answer stands as text alone.
"""

import structlog
from temporalio import activity

from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.object_tags.slack import rewrite_object_tags_for_slack
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_rich_replies_enabled
from products.slack_app.backend.logic.reply_presentation import (
    PresentationAttribution,
    present_reply,
    presentation_blocks,
)
from products.slack_app.backend.services.slack_messages import project_web_url
from products.slack_app.backend.services.workspace_integrations import with_teams
from products.slack_app.backend.temporal.types import PresentSlackReplyInput, SlackReplyPresentation
from products.tasks.backend.facade import api as tasks_facade

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

logger = structlog.get_logger(__name__)


@activity.defn
@close_db_connections
def present_slack_reply_activity(input: PresentSlackReplyInput) -> SlackReplyPresentation | None:
    if not input.answer_markdown.strip():
        return None
    run = tasks_facade.get_task_run(input.run_id)
    if run is None:
        return None
    # nosemgrep: idor-lookup-without-team (internal context, ID from Slack event mapping)
    row = Integration.objects.filter(id=input.integration_id, team_id=run.team_id).first()
    if row is None:
        return None
    integration = with_teams([row])[0]
    if not is_slack_app_rich_replies_enabled(integration, run.created_by_distinct_id):
        return None
    user = User.objects.filter(id=run.created_by_id).first() if run.created_by_id else None

    # The presenter reads the answer as the reader sees it, so a cited object counts as a link it can show.
    answer_markdown = rewrite_object_tags_for_slack(input.answer_markdown, project_url=project_web_url(run.team_id))
    try:
        presentation = present_reply(
            answer_markdown,
            PresentationAttribution(
                trace_id=input.trace_id,
                distinct_id=run.created_by_distinct_id,
                task_id=str(run.task_id),
                run_id=str(run.id),
                privacy_mode=is_privacy_mode_enabled(integration.team),
            ),
        )
    except Exception:
        logger.warning("slack_app_reply_presentation_failed", exc_info=True)
        capture_slack_event(integration, "slack app reply presented", posthog_user=user, outcome="failed")
        return None

    spec = presentation.spec
    if spec is None:
        outcome = "invalid"
    elif spec.is_empty:
        outcome = "empty"
    else:
        outcome = "presented"
    capture_slack_event(
        integration,
        "slack app reply presented",
        posthog_user=user,
        outcome=outcome,
        attempts=presentation.attempts,
        metric_count=len(spec.metrics) if spec else 0,
        link_count=len(spec.links) if spec else 0,
    )
    if spec is None:
        logger.info("slack_app_reply_presentation_invalid", errors=list(presentation.errors))
        return None
    if spec.is_empty:
        return None
    return SlackReplyPresentation(blocks=presentation_blocks(spec))
