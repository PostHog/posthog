"""Components the presenter adds under a finished agent answer.

Any caller with a delivered answer can run it. Best effort: a failure shows whatever arrived before
it, and the answer stands as text alone.
"""

from typing import Any

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.object_tags.slack import rewrite_object_tags_for_slack
from posthog.temporal.common.utils import close_db_connections

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_rich_replies_enabled
from products.slack_app.backend.logic.reply_presentation import (
    ALL_COMPONENT_KINDS,
    BlockAssembler,
    ComponentChecker,
    ComponentKind,
    PresentationAttribution,
    ThrottledMessage,
    present_components,
    presentation_deltas,
)
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import project_web_url
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, with_teams
from products.slack_app.backend.temporal.types import (
    PresentSlackReplyInput,
    SlackReplyPresentation,
    SlackReplyPresentationGateInput,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ee.hogai.utils.feature_flags import is_privacy_mode_enabled

logger = structlog.get_logger(__name__)

PRESENTATION_MESSAGE_TEXT = "Highlights from this answer"


@frozen
class _RunThread:
    run: TaskRunDTO
    mapping: SlackThreadTaskMapping
    integration: WorkspaceIntegration


def _run_thread(run_id: str) -> _RunThread | None:
    run = tasks_facade.get_task_run(run_id)
    if run is None:
        return None
    mapping = (
        SlackThreadTaskMapping.objects.filter(task_run_id=run.id, team_id=run.team_id)
        .select_related("integration")
        .first()
    )
    if mapping is None:
        return None
    return _RunThread(run=run, mapping=mapping, integration=with_teams([mapping.integration])[0])


def _offered_kinds(run: TaskRunDTO, team: Team) -> frozenset[ComponentKind]:
    kinds = set(ALL_COMPONENT_KINDS)
    if (run.state or {}).get("slack_chart_links"):
        # Slack already unfurls the PostHog links in this run's replies, with their charts.
        kinds -= {"resource", "chart"}
    if not team.organization.allow_publicly_shared_resources:
        # The chart image opens without a PostHog login.
        kinds.discard("chart")
    return frozenset(kinds)


@activity.defn
@close_db_connections
def is_slack_reply_presentation_enabled_activity(input: SlackReplyPresentationGateInput) -> bool:
    thread = _run_thread(input.run_id)
    if thread is None:
        return False
    return is_slack_app_rich_replies_enabled(thread.integration, thread.run.created_by_distinct_id)


@activity.defn
@close_db_connections
def present_slack_reply_activity(input: PresentSlackReplyInput) -> SlackReplyPresentation | None:
    """Gating is the caller's, through `is_slack_reply_presentation_enabled_activity`, so a caller
    can change how it posts the answer before the presenter runs."""
    # noqa reason: the unfurl module's import chain reaches the tasks workflows, which import this module.
    from products.slack_app.backend.slack_link_unfurl import (  # noqa: PLC0415
        reply_chart_request,
        resource_card_blocks,
        start_reply_charts,
    )
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler  # noqa: PLC0415

    if not input.answer_markdown.strip():
        return None
    thread = _run_thread(input.run_id)
    if thread is None:
        return None
    run, mapping, integration = thread.run, thread.mapping, thread.integration
    # Cards and charts are built with the access of the person whose run this is, as the unfurls of its replies are.
    user = User.objects.filter(id=run.created_by_id).first() if run.created_by_id else None
    if user is None:
        return None
    team = integration.team
    context = SlackThreadContext.from_mapping(mapping)
    handler = SlackThreadHandler(context)
    slack_user_id = mapping.latest_actor_slack_user_id or mapping.mentioning_slack_user_id or ""
    # The presenter reads the answer as the reader sees it, so a cited object counts as a link it can show.
    answer = rewrite_object_tags_for_slack(input.answer_markdown, project_url=project_web_url(run.team_id))

    assembler = BlockAssembler(
        render_resource=lambda url: resource_card_blocks(
            integration=integration,
            user=user,
            slack_user_id=slack_user_id,
            channel=context.channel,
            thread_ts=context.thread_ts,
            url=url,
        )
    )
    message = ThrottledMessage(
        post=lambda blocks: handler.post_blocks(PRESENTATION_MESSAGE_TEXT, blocks),
        update=lambda ts, blocks: handler.update_blocks(ts, PRESENTATION_MESSAGE_TEXT, blocks),
    )
    stream_ts = input.stream_ts

    def deliver(assembled: BlockAssembler, final: bool) -> None:
        if stream_ts is not None:
            handler.append_status_blocks(stream_ts, assembled.take_settled(final=final))
        else:
            message.show(assembled.snapshot(), final=final)

    kinds = _offered_kinds(run, team)
    outcome = present_components(
        presentation_deltas(
            answer,
            kinds,
            PresentationAttribution(
                trace_id=input.trace_id,
                distinct_id=run.created_by_distinct_id,
                task_id=str(run.task_id),
                run_id=str(run.id),
                privacy_mode=is_privacy_mode_enabled(team),
            ),
        ),
        ComponentChecker(answer, kinds),
        assembler,
        deliver,
    )
    if outcome.error:
        logger.warning("slack_app_reply_presentation_stopped", error=outcome.error)

    chart_requests = [
        request for chart in outcome.charts if (request := reply_chart_request(team, chart.url, chart.title))
    ]
    charts_started = start_reply_charts(
        integration=integration,
        user=user,
        slack_user_id=slack_user_id,
        channel=context.channel,
        thread_ts=context.thread_ts,
        message_ts=stream_ts or message.ts or context.thread_ts,
        charts=chart_requests,
    )

    component_count = sum(outcome.accepted.values())
    properties: dict[str, Any] = {
        "outcome": "failed" if outcome.error and not component_count else "presented" if component_count else "empty",
        "delivery": "stream" if stream_ts is not None else "message",
        "components": dict(outcome.accepted),
        "rejected_count": len(outcome.rejections),
        "unrendered_resources": outcome.unrendered_resources,
        "charts_started": charts_started,
        "first_component_ms": outcome.first_component_ms,
        "error": outcome.error,
    }
    capture_slack_event(integration, "slack app reply presented", posthog_user=user, **properties)
    if outcome.rejections:
        logger.info("slack_app_reply_presentation_rejections", rejections=list(outcome.rejections))
    return SlackReplyPresentation(components=component_count)
