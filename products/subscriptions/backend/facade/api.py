"""
Facade for subscriptions.

With contracts.py, temporal.py and testing.py, the only modules core and other
products may import. Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING

from products.subscriptions.backend.logic import (
    auto_disable,
    queries,
    subscription_reads,
    subscription_utils,
    subscription_writes,
    summary_quota,
)
from products.subscriptions.backend.logic.subscription_utils import MAX_INSIGHTS as MAX_INSIGHTS
from products.subscriptions.backend.logic.teams_subscriptions import (
    TEAMS_WEBHOOK_URL_ERROR as TEAMS_WEBHOOK_URL_ERROR,
    TEAMS_WEBHOOK_URL_MASKED_ERROR as TEAMS_WEBHOOK_URL_MASKED_ERROR,
)
from products.subscriptions.backend.models.subscription import (
    AIQueryPlanStatus,
    Subscription,
    SubscriptionDelivery,
    unsubscribe_using_token,
)
from products.subscriptions.backend.temporal.ai_subscription import spec_generator
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH as AI_PROMPT_MAX_LENGTH,
)
from products.subscriptions.backend.temporal.types import (
    AI_REPORT_CHARTS_KEY as AI_REPORT_CHARTS_KEY,
    AI_REPORT_DIAGNOSTICS_KEY as AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY as AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_QUERY_FAILURE_TYPE as AI_REPORT_QUERY_FAILURE_TYPE,
    AI_REPORT_QUERY_PLAN_STATUS_KEY as AI_REPORT_QUERY_PLAN_STATUS_KEY,
    AI_REPORT_SNAPSHOT_KEY as AI_REPORT_SNAPSHOT_KEY,
)

from . import contracts

if TYPE_CHECKING:
    from posthog.event_usage import AnalyticsProps
    from posthog.models.organization import Organization
    from posthog.models.sharing_configuration import SharingConfiguration
    from posthog.models.team import Team
    from posthog.models.user import User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

# The value sets the API accepts and returns, as (value, label) pairs. A serializer field built from
# one of these gets the same OpenAPI enum component as the model field it mirrors.
TARGET_TYPE_CHOICES = Subscription.SubscriptionTarget.choices
FREQUENCY_CHOICES = Subscription.SubscriptionFrequency.choices
WEEKDAY_CHOICES = Subscription.SubscriptionByWeekDay.choices
RESOURCE_TYPE_CHOICES = Subscription.ResourceType.choices
AI_WINDOW_MODE_CHOICES = Subscription.AIWindowMode.choices
AI_QUERY_PLAN_STATUS_CHOICES = AIQueryPlanStatus.choices
DELIVERY_STATUS_CHOICES = SubscriptionDelivery.Status.choices

TARGET_TYPE_TEAMS: str = Subscription.SubscriptionTarget.TEAMS.value
AI_WINDOW_MODE_SINCE_LAST_SENT: str = Subscription.AIWindowMode.SINCE_LAST_SENT.value
AI_WINDOW_MODE_LAST_N_DAYS: str = Subscription.AIWindowMode.LAST_N_DAYS.value
MAX_AI_SUBSCRIPTION_CONTEXTS: int = subscription_writes.MAX_AI_SUBSCRIPTION_CONTEXTS

__all__ = [
    "AI_PROMPT_MAX_LENGTH",
    "AI_QUERY_PLAN_STATUS_CHOICES",
    "AI_REPORT_CHARTS_KEY",
    "AI_REPORT_DIAGNOSTICS_KEY",
    "AI_REPORT_PROMPT_SNAPSHOT_KEY",
    "AI_REPORT_QUERY_FAILURE_TYPE",
    "AI_REPORT_QUERY_PLAN_STATUS_KEY",
    "AI_REPORT_SNAPSHOT_KEY",
    "AI_WINDOW_MODE_CHOICES",
    "AI_WINDOW_MODE_LAST_N_DAYS",
    "AI_WINDOW_MODE_SINCE_LAST_SENT",
    "DELIVERY_STATUS_CHOICES",
    "FREQUENCY_CHOICES",
    "MAX_AI_SUBSCRIPTION_CONTEXTS",
    "MAX_INSIGHTS",
    "RESOURCE_TYPE_CHOICES",
    "TARGET_TYPE_CHOICES",
    "TARGET_TYPE_TEAMS",
    "TEAMS_WEBHOOK_URL_ERROR",
    "TEAMS_WEBHOOK_URL_MASKED_ERROR",
    "WEEKDAY_CHOICES",
    "ai_query_plan_status",
    "create_subscription",
    "dashboard_has_active_full_subscription",
    "dashboard_ids_with_subscriptions",
    "delete_insight_subscriptions",
    "failed_delivery_counts",
    "get_subscription",
    "get_subscription_delivery",
    "get_subscription_ref",
    "get_summary_quota",
    "insight_has_active_subscription",
    "insight_ids_with_subscriptions",
    "is_ai_prompt_subscription",
    "list_subscription_deliveries",
    "list_subscription_summaries",
    "list_subscriptions",
    "normalize_ai_window",
    "render_shared_insight_image",
    "sanitize_prompt",
    "start_test_delivery",
    "subscription_ids_in_team",
    "unsubscribe",
    "update_subscription",
    "user_has_slack_subscription",
    "validate_re_enable",
    "viewable_live_insight_id",
]


def validate_re_enable(target_type: str | None, integration_id: int | None) -> str | None:
    """The user-facing reason a subscription cannot be re-enabled, or None when it can."""
    return auto_disable.validate_re_enable(target_type, integration_id)


def sanitize_prompt(raw: str | None) -> str:
    """Clean an AI report prompt. Raises contracts.PromptRejectedError when the prompt is unusable."""
    return spec_generator.sanitize_prompt(raw)


def ai_query_plan_status(ai_query_plan: object | None) -> str:
    """The status value of a stored AI query plan: frozen, not frozen, or outdated by a planner change."""
    return spec_generator.get_ai_query_plan_status(ai_query_plan).value


def render_shared_insight_image(sharing_configuration: SharingConfiguration) -> contracts.SharedInsightImage | None:
    """Render the first insight a share link shows as an image. Returns None when it shows no insight."""
    return subscription_utils.shared_insight_image(sharing_configuration)


def unsubscribe(token: str) -> None:
    """Remove the email in an unsubscribe token from its subscription. Raises jwt.DecodeError for a bad token."""
    unsubscribe_using_token(token)


def failed_delivery_counts(*, team_id: int, since: datetime, limit: int) -> list[contracts.FailedDeliveryCount]:
    """Subscriptions that failed to deliver since `since`, most failures first. Deleted subscriptions are left out."""
    return queries.failed_delivery_counts(team_id=team_id, since=since, limit=limit)


def subscription_ids_in_team(*, team_id: int, subscription_ids: Collection[int]) -> set[int]:
    """Which of the given subscription ids belong to the team."""
    return queries.subscription_ids_in_team(team_id=team_id, subscription_ids=subscription_ids)


def user_has_slack_subscription(*, team_id: int, user_id: int) -> bool:
    """Whether the user created a subscription that delivers to Slack in this team. A disabled one counts."""
    return queries.user_has_slack_subscription(team_id=team_id, user_id=user_id)


def delete_insight_subscriptions(*, project_id: int, insight_ids: Collection[int]) -> None:
    # nosemgrep: environment-model-scoped-by-project -- insights are project-level, so deleting one removes its subscriptions in every environment
    for subscription in Subscription.objects.filter(team__project_id=project_id, insight_id__in=insight_ids):
        subscription.delete()


def insight_ids_with_subscriptions(insight_ids: Collection[int]) -> set[int]:
    """Which of the given insights have a subscription that has not been deleted.

    Paused subscriptions (enabled=False) count: disabling delivery does not withdraw the intent
    to deliver this insight again.
    """
    # Caller-supplied ids that are already team-scoped by the caller's own query; this only maps
    # ids to ids and returns no row data.
    # nosemgrep: idor-lookup-without-team
    return set(
        Subscription.objects.filter(insight_id__in=insight_ids, deleted=False).values_list("insight_id", flat=True)
    )


def dashboard_ids_with_subscriptions(dashboard_ids: Collection[int]) -> set[int]:
    """Which of the given dashboards have a subscription that has not been deleted.

    Paused subscriptions (enabled=False) count: disabling delivery does not withdraw the intent
    to deliver this dashboard again.
    """
    # Caller-supplied ids that are already team-scoped by the caller's own query; this only maps
    # ids to ids and returns no row data.
    # nosemgrep: idor-lookup-without-team
    return set(
        Subscription.objects.filter(dashboard_id__in=dashboard_ids, deleted=False).values_list(
            "dashboard_id", flat=True
        )
    )


def insight_has_active_subscription(insight_id: int) -> bool:
    """Whether an enabled subscription delivers this insight, directly or as a dashboard tile."""
    return queries.insight_has_active_subscription(insight_id)


def dashboard_has_active_full_subscription(dashboard_id: int) -> bool:
    """Whether an enabled subscription delivers every insight on this dashboard."""
    return queries.dashboard_has_active_full_subscription(dashboard_id)


# The subscription API. Each function takes the team the request is scoped to. A refusal is raised as
# one of the error types in contracts.py, and the caller decides which HTTP response it becomes.


def list_subscriptions(
    *, team_id: int, query: contracts.SubscriptionListQuery, viewer: UserAccessControl, offset: int, limit: int
) -> contracts.SubscriptionPage:
    """One page of the team's subscriptions that the viewer may see, in `query.ordering`.

    A subscription is hidden when the viewer cannot view an insight or a dashboard it delivers.
    """
    return subscription_reads.list_subscriptions(
        team_id=team_id, query=query, viewer=viewer, offset=offset, limit=limit
    )


def get_subscription_ref(
    *,
    team_id: int,
    subscription_id: str | int,
    filters: contracts.SubscriptionFilters,
    viewer: UserAccessControl,
) -> contracts.SubscriptionRef:
    """One subscription of the team that `filters` leave in.

    Raises `SubscriptionNotFoundError` when there is none, and `SubscriptionPermissionDeniedError`
    when the viewer cannot view an insight or a dashboard it delivers. An id that is not a number
    raises ValueError, as the row lookup does.
    """
    return subscription_reads.get_subscription_ref(
        team_id=team_id, subscription_id=subscription_id, filters=filters, viewer=viewer
    )


def get_subscription(*, team_id: int, subscription_id: int) -> contracts.SubscriptionRecord:
    """Every value a response shows for a subscription that `get_subscription_ref` returned."""
    return subscription_reads.get_subscription(team_id=team_id, subscription_id=subscription_id)


def is_ai_prompt_subscription(*, team_id: int, subscription_id: str | int) -> bool:
    """Whether the team has a subscription with this id that an AI prompt drives."""
    return subscription_reads.is_ai_prompt_subscription(team_id=team_id, subscription_id=subscription_id)


def create_subscription(
    *,
    team: Team,
    organization: Organization,
    user: User,
    viewer: UserAccessControl,
    write: contracts.SubscriptionWrite,
    analytics_props: AnalyticsProps,
) -> contracts.SubscriptionRecord:
    """Create a subscription and, unless it is disabled or `send_test_now` is false, start its first delivery.

    Raises `SubscriptionRequestInvalidError`, `SubscriptionPermissionDeniedError` or
    `SubscriptionQuotaExceededError` when a rule refuses the write.
    """
    return subscription_writes.create_subscription(
        team=team,
        organization=organization,
        user=user,
        viewer=viewer,
        write=write,
        analytics_props=analytics_props,
    )


def update_subscription(
    *,
    team: Team,
    organization: Organization,
    user: User,
    viewer: UserAccessControl,
    subscription_id: int,
    write: contracts.SubscriptionWrite,
    partial: bool,
    analytics_props: AnalyticsProps,
) -> contracts.SubscriptionRecord:
    """Change a subscription and start a delivery when the change asks for one or changes what gets delivered.

    Raises the same errors as `create_subscription`.
    """
    return subscription_writes.update_subscription(
        team=team,
        organization=organization,
        user=user,
        viewer=viewer,
        subscription_id=subscription_id,
        write=write,
        partial=partial,
        analytics_props=analytics_props,
    )


def start_test_delivery(*, team_id: int, subscription_id: int) -> contracts.ManualDeliveryResult:
    """Start one delivery of the subscription now, outside its schedule."""
    return subscription_writes.start_test_delivery(team_id=team_id, subscription_id=subscription_id)


def get_summary_quota(organization: Organization) -> contracts.SummaryQuota:
    """The organization's active AI summaries against its plan's cap. Cached for a minute."""
    return summary_quota.summary_quota(organization)


def normalize_ai_window(window: contracts.JsonValue) -> dict[str, contracts.JsonValue]:
    """A stored AI report window in the shape the API returns, with any malformed value replaced by the default."""
    return Subscription.normalize_ai_window(window)


def list_subscription_deliveries(
    *,
    team_id: int,
    subscription_id: str | None,
    status: str | None,
    viewer: UserAccessControl,
    window: contracts.CreatedAtCursorWindow,
    filter_by_object_access: bool,
    include_all_if_admin: bool,
) -> list[contracts.SubscriptionDeliveryRecord]:
    """One window of a subscription's delivery history that the viewer may see."""
    return subscription_reads.list_subscription_deliveries(
        team_id=team_id,
        subscription_id=subscription_id,
        status=status,
        viewer=viewer,
        window=window,
        filter_by_object_access=filter_by_object_access,
        include_all_if_admin=include_all_if_admin,
    )


def get_subscription_delivery(
    *, team_id: int, subscription_id: str | None, delivery_id: str, viewer: UserAccessControl
) -> contracts.SubscriptionDeliveryRecord:
    """One delivery of a subscription. Raises `SubscriptionNotFoundError` when the viewer cannot see it."""
    return subscription_reads.get_subscription_delivery(
        team_id=team_id, subscription_id=subscription_id, delivery_id=delivery_id, viewer=viewer
    )


def viewable_live_insight_id(*, team_id: int, insight_id: int, viewer: UserAccessControl) -> int:
    """The id of a live insight of the team that the viewer may view.

    Raises `SubscriptionNotFoundError` when there is none, and `SubscriptionPermissionDeniedError`
    when the viewer may not view it.
    """
    return subscription_reads.viewable_live_insight_id(team_id=team_id, insight_id=insight_id, viewer=viewer)


def list_subscription_summaries(
    *,
    team_id: int,
    insight_id: int | None,
    dashboard_id: int | None,
    viewer: UserAccessControl,
    window: contracts.CreatedAtCursorWindow,
) -> list[contracts.SubscriptionSummaryRecord]:
    """One window of the AI summaries that live subscriptions on one insight or one dashboard delivered.

    Pass exactly one of `insight_id` and `dashboard_id`, after checking that the viewer may view it.
    """
    return subscription_reads.list_subscription_summaries(
        team_id=team_id, insight_id=insight_id, dashboard_id=dashboard_id, viewer=viewer, window=window
    )
