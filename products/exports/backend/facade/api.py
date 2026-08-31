"""Public Python interface for creating and retrieving one-off exports."""

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.http.response import HttpResponseBase

import structlog
from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy

from posthog.hogql.constants import LimitContext

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports.workflows import ExportAssetWorkflow, ExportAssetWorkflowInputs

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.exported_asset import (
    DATASET_EXPORT_KIND as DATASET_EXPORT_KIND,
    ExportedAsset,
    get_content_response,
    save_content_from_file as _save_content_from_file,
)
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.models.subscription_context import SubscriptionContext
from products.exports.backend.tasks.failure_handler import (
    InvalidExportContext as InvalidExportContext,
    RetryableExportError as RetryableExportError,
)
from products.product_analytics.backend.facade.api import viewable_insight_ids_for_user
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

JSONL_EXPORT_FORMAT = ExportedAsset.ExportFormat.JSONL
_AI_REPORT_SNAPSHOT_KEY = "ai_report"

# Caps the whole workflow including retries; callers block on this, so it must stay
# well under the web tier's request timeout.
RENDER_TIMEOUT = timedelta(seconds=90)
EXPORT_WORKFLOW_TIMEOUT = timedelta(minutes=35)


@frozen
class AuthorizedSubscription:
    id: int
    resource_type: str


@frozen
class PersistedAIReportDelivery:
    delivery_id: UUID
    base_report: str
    target_type: str
    target_value: str


def create_export_asset_async(
    *,
    team: Team,
    created_by: User,
    export_format: str,
    export_context: dict[str, object],
) -> ExportedAsset:
    if export_format not in ExportedAsset.get_supported_format_values():
        raise ValueError(f"Unsupported export format: {export_format}")

    asset = ExportedAsset.objects.create(
        team=team,
        created_by=created_by,
        export_format=export_format,
        export_context=export_context,
    )

    async def _start() -> None:
        client = await async_connect()
        await client.start_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.id,
                team_id=team.id,
                distinct_id=str(created_by.distinct_id),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            execution_timeout=EXPORT_WORKFLOW_TIMEOUT,
        )

    try:
        async_to_sync(_start)()
    except Exception as error:
        logger.info("export_workflow_failed_gracefully", asset_id=asset.id, error=str(error))
        asset.refresh_from_db()
        if not asset.exception:
            asset.exception = "The export could not be started. Try again."
            asset.exception_type = type(error).__name__
            asset.save(update_fields=["exception", "exception_type"])
    asset.refresh_from_db()
    return asset


def get_export_asset(*, team_id: int, asset_id: int) -> ExportedAsset | None:
    return ExportedAsset.objects.filter(team_id=team_id, id=asset_id).first()


def subscription_exists_for_team(*, team_id: int, subscription_id: int) -> bool:
    """Whether an active subscription belongs to one team."""
    return Subscription.objects.filter(team_id=team_id, id=subscription_id, deleted=False).exists()


def get_persisted_ai_report_delivery(
    *, team_id: int, subscription_id: int, delivery_id: UUID
) -> PersistedAIReportDelivery | None:
    """Return the persisted recipient-safe AI report for one exact delivery binding."""
    delivery = (
        SubscriptionDelivery.objects.filter(
            id=delivery_id,
            team_id=team_id,
            subscription_id=subscription_id,
            subscription__prompt__isnull=False,
            subscription__dashboard__isnull=True,
            subscription__insight__isnull=True,
        )
        .values("content_snapshot", "target_type", "target_value")
        .first()
    )
    if delivery is None:
        return None
    snapshot = delivery["content_snapshot"]
    report = snapshot.get(_AI_REPORT_SNAPSHOT_KEY) if isinstance(snapshot, dict) else None
    if not isinstance(report, str) or not report:
        return None
    target_type = delivery["target_type"]
    target_value = delivery["target_value"]
    return PersistedAIReportDelivery(
        delivery_id=delivery_id,
        base_report=report,
        target_type=target_type,
        target_value=target_value,
    )


def get_authorized_subscription(*, team: Team, user: User, subscription_id: int) -> AuthorizedSubscription | None:
    """Resolve a subscription only when the caller can read its underlying resource."""
    subscription = (
        Subscription.objects.filter(team_id=team.id, id=subscription_id, deleted=False)
        .select_related("insight", "dashboard")
        .first()
    )
    if subscription is None:
        return None
    access_control = UserAccessControl(user=user, team=team)
    if subscription.resource_type == Subscription.ResourceType.AI_PROMPT:
        if not access_control.check_access_level_for_resource("query", "viewer"):
            return None
        contexts = (
            SubscriptionContext.objects.for_team(team.id)
            .filter(subscription_id=subscription.id)
            .select_related("dashboard", "insight")
        )
        for context in contexts:
            target = context.dashboard if context.dashboard_id is not None else context.insight
            if target is None or not access_control.check_access_level_for_object(target, "viewer"):
                return None
            if context.dashboard_id is not None:
                for tile in DashboardTile.objects.filter(
                    dashboard_id=context.dashboard_id, insight_id__isnull=False
                ).select_related("insight"):
                    if tile.insight is not None and not access_control.check_access_level_for_object(
                        tile.insight, "viewer"
                    ):
                        return None
    elif subscription.insight is not None:
        if not access_control.check_access_level_for_object(subscription.insight, "viewer"):
            return None
    elif subscription.dashboard is not None and not access_control.check_access_level_for_object(
        subscription.dashboard, "viewer"
    ):
        return None
    return AuthorizedSubscription(id=subscription.id, resource_type=subscription.resource_type)


def snapshot_contexts_are_viewable(*, team: Team, user: User, contexts: object) -> bool:
    """Check immutable run snapshot contexts against the caller's current access."""
    if not isinstance(contexts, list) or len(contexts) > 3:
        return False
    parsed_contexts: list[tuple[str, int]] = []
    insight_ids: set[int] = set()
    for context in contexts:
        if not isinstance(context, dict) or set(context) not in ({"dashboard_id"}, {"insight_id"}):
            return False
        key, identifier = next(iter(context.items()))
        if not isinstance(identifier, int) or identifier < 1:
            return False
        parsed_contexts.append((key, identifier))
        if key == "insight_id":
            insight_ids.add(identifier)

    viewable_insight_ids = viewable_insight_ids_for_user(team=team, user=user, insight_ids=insight_ids)
    access_control = UserAccessControl(user=user, team=team)
    for key, identifier in parsed_contexts:
        if key == "insight_id":
            if identifier not in viewable_insight_ids:
                return False
            continue
        target = Dashboard.objects.filter(team_id=team.id, id=identifier).first()
        if target is None or not access_control.check_access_level_for_object(target, "viewer"):
            return False
        for tile in DashboardTile.objects.filter(dashboard_id=identifier, insight_id__isnull=False).select_related(
            "insight"
        ):
            if tile.insight is not None and not access_control.check_access_level_for_object(tile.insight, "viewer"):
                return False
    return True


def snapshot_contexts_are_viewable_preloaded(
    *, team: Team, user: User, contexts_by_key: Mapping[UUID, object]
) -> set[UUID]:
    """Return snapshot keys whose contexts are viewable using bulk-loaded targets."""
    parsed_contexts_by_key: dict[UUID, list[tuple[str, int]]] = {}
    insight_ids: set[int] = set()
    dashboard_ids: set[int] = set()
    for key, contexts in contexts_by_key.items():
        if not isinstance(contexts, list) or len(contexts) > 3:
            continue
        parsed_contexts: list[tuple[str, int]] = []
        for context in contexts:
            if not isinstance(context, dict) or set(context) not in ({"dashboard_id"}, {"insight_id"}):
                parsed_contexts = []
                break
            context_type, identifier = next(iter(context.items()))
            if not isinstance(identifier, int) or identifier < 1:
                parsed_contexts = []
                break
            parsed_contexts.append((context_type, identifier))
            if context_type == "dashboard_id":
                dashboard_ids.add(identifier)
            else:
                insight_ids.add(identifier)
        else:
            parsed_contexts_by_key[key] = parsed_contexts

    dashboards_by_id = {
        dashboard.id: dashboard for dashboard in Dashboard.objects.filter(team_id=team.id, id__in=dashboard_ids)
    }
    dashboard_tiles_by_dashboard_id: dict[int, list[DashboardTile]] = {
        dashboard_id: [] for dashboard_id in dashboard_ids
    }
    for tile in DashboardTile.objects.filter(dashboard_id__in=dashboard_ids, insight_id__isnull=False).select_related(
        "insight"
    ):
        dashboard_tiles_by_dashboard_id.setdefault(tile.dashboard_id, []).append(tile)

    viewable_insight_ids = viewable_insight_ids_for_user(team=team, user=user, insight_ids=insight_ids)
    access_control = UserAccessControl(user=user, team=team)
    visible_keys: set[UUID] = set()
    for key, contexts in parsed_contexts_by_key.items():
        is_viewable = True
        for context_type, identifier in contexts:
            if context_type == "insight_id":
                if identifier not in viewable_insight_ids:
                    is_viewable = False
                    break
                continue
            target = dashboards_by_id.get(identifier)
            if target is None or not access_control.check_access_level_for_object(target, "viewer"):
                is_viewable = False
                break
            for tile in dashboard_tiles_by_dashboard_id.get(identifier, []):
                if tile.insight is None or not access_control.check_access_level_for_object(tile.insight, "viewer"):
                    is_viewable = False
                    break
            if not is_viewable:
                break
        if is_viewable:
            visible_keys.add(key)
    return visible_keys


def subscription_snapshot_contexts_are_authorized(
    *, team: Team, user: User, subscription_id: int, contexts: object
) -> bool:
    subscription = get_authorized_subscription(team=team, user=user, subscription_id=subscription_id)
    if subscription is None or subscription.resource_type != Subscription.ResourceType.AI_PROMPT:
        return False
    if not snapshot_contexts_are_viewable(team=team, user=user, contexts=contexts):
        return False
    if not isinstance(contexts, list):
        return False

    current_contexts = {
        ("dashboard_id", dashboard_id) if dashboard_id is not None else ("insight_id", insight_id)
        for dashboard_id, insight_id in SubscriptionContext.objects.for_team(team.id)
        .filter(subscription_id=subscription_id)
        .values_list("dashboard_id", "insight_id")
    }
    snapshot_contexts = {(key, identifier) for context in contexts for key, identifier in context.items()}
    return len(snapshot_contexts) == len(contexts) and snapshot_contexts == current_contexts


def subscription_snapshot_contexts_are_authorized_preloaded(
    *,
    team: Team,
    user: User,
    subscription: Subscription,
    contexts: Sequence[SubscriptionContext],
    dashboard_tiles_by_dashboard_id: Mapping[int, Sequence[DashboardTile]],
    access_control: UserAccessControl,
) -> bool:
    """Check a scheduled AI subscription using only caller-provided bulk-loaded rows."""
    if (
        subscription.team_id != team.id
        or subscription.deleted
        or subscription.resource_type != Subscription.ResourceType.AI_PROMPT
        or not access_control.check_access_level_for_resource("query", "viewer")
        or len(contexts) > 3
    ):
        return False
    snapshot_contexts: set[tuple[str, int]] = set()
    for context in contexts:
        if context.team_id != team.id or context.subscription_id != subscription.id:
            return False
        target: Dashboard | Insight | None
        identifier: int | None
        if context.dashboard_id is not None:
            target = context.dashboard
            key = "dashboard_id"
            identifier = context.dashboard_id
            tiles = dashboard_tiles_by_dashboard_id.get(identifier, ())
        else:
            target = context.insight
            key = "insight_id"
            identifier = context.insight_id
            tiles = ()
        if (
            identifier is None
            or target is None
            or target.team_id != team.id
            or (key == "insight_id" and target.deleted)
            or not access_control.check_access_level_for_object(target, "viewer")
        ):
            return False
        snapshot_contexts.add((key, identifier))
        for tile in tiles:
            if tile.dashboard_id != identifier or tile.insight is None:
                return False
            if not access_control.check_access_level_for_object(tile.insight, "viewer"):
                return False
    return len(snapshot_contexts) == len(contexts)


def get_export_asset_content_response(*, asset: ExportedAsset, download: bool) -> HttpResponseBase:
    return get_content_response(asset, download=download)


def save_export_asset_content_from_file(
    *,
    asset: ExportedAsset,
    file_path: str,
    max_database_bytes: int | None = None,
) -> None:
    _save_content_from_file(asset, file_path, max_database_bytes=max_database_bytes)


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


# The limit contexts an export writer can pin, keyed by the string it stores in export_context.
# The API rejects this key from clients, so only PostHog's own writers reach this map.
_PINNABLE_EXPORT_LIMIT_CONTEXTS = {"posthog_ai": LimitContext.POSTHOG_AI}


def export_limit_context(export_context: dict | None) -> LimitContext:
    requested = (export_context or {}).get("limit_context")
    if isinstance(requested, str):
        return _PINNABLE_EXPORT_LIMIT_CONTEXTS.get(requested, LimitContext.QUERY)
    return LimitContext.QUERY


def _validate_adhoc_export_context(export_context: dict) -> None:
    """The ad-hoc render pipeline (viewport sizing, the exporter page's Query dispatch) draws a
    chart for an InsightVizNode-wrapped source, or for a DataVisualizationNode over HogQL. Anything
    else renders a JSON dump instead of a chart, so reject it here with a real error instead."""
    source = export_context.get("source")
    if isinstance(source, dict):
        kind = source.get("kind")
        if kind == "InsightVizNode":
            return
        inner = source.get("source")
        if kind == "DataVisualizationNode" and isinstance(inner, dict) and inner.get("kind") == "HogQLQuery":
            return
    raise ValueError("export_context.source must be an InsightVizNode- or DataVisualizationNode-wrapped query")


def get_delivery_image_url(
    *, team_id: int, asset_id: int, expiry_delta: timedelta, created_by_id: int | None = None
) -> str | None:
    """Mint a delivery-purposed url for one of the team's own rendered images.

    The token authenticates anonymously and bypasses the org's publicly-shared-resources
    setting, so it is minted on demand rather than stored anywhere a lower-privileged
    reader could reach. Callers are responsible for only passing an ``asset_id`` they
    established server-side; the format and team filters bound the damage if one leaks —
    an image url can never be turned into a CSV or XLSX download. The manager also
    excludes assets past their TTL.

    Pass ``created_by_id`` when the ``asset_id`` comes from a store a caller cannot fully
    trust (e.g. an id read back from a shared cache): it pins the asset to the user that
    rendered it, so a substituted id belonging to another same-team user mints nothing.
    """
    asset_filter = {"team_id": team_id, "id": asset_id, "export_format": ExportedAsset.ExportFormat.PNG}
    if created_by_id is not None:
        asset_filter["created_by_id"] = created_by_id
    asset = ExportedAsset.objects.filter(**asset_filter).first()
    if asset is None:
        return None
    return asset.get_subscription_delivery_content_url(expiry_delta=expiry_delta)


def render_png_export(
    *,
    team: Team,
    created_by: User,
    export_context: dict | None = None,
    insight_id: int | None = None,
    insight_short_id: str | None = None,
    is_system: bool = False,
    expires_after: datetime | None = None,
) -> tuple[ExportedAsset, bytes | None]:
    """Render a PNG export synchronously and return the asset together with its content bytes.

    Blocks until the export workflow finishes (typically a few seconds). On failure the
    returned bytes are None and ``asset.exception`` carries the error.

    ``is_system`` marks the asset as created by an internal process, which excludes it from
    the user's export listings and the per-team export quota. ``expires_after`` overrides
    the format's default TTL; pass it when the render backs a short-lived delivery URL so
    the stored bytes do not outlive their only consumer by months.
    """
    if created_by is None:
        # Access control below resolves against created_by; a principal-less render would
        # silently skip it, so service callers must attribute the render to a real user.
        raise ValueError("created_by is required")
    if sum(value is not None for value in (export_context, insight_id, insight_short_id)) != 1:
        raise ValueError("Provide exactly one of export_context, insight_id or insight_short_id")
    if export_context is not None:
        _validate_adhoc_export_context(export_context)
        # An ad-hoc render runs whatever query the caller supplies, so it needs the same gate as
        # running that query directly; the object-level check below covers only saved insights.
        if not UserAccessControl(user=created_by, team=team).check_access_level_for_resource("query", "viewer"):
            raise ValueError("You need query access to render this export")
    if insight_id is not None or insight_short_id is not None:
        insight_filter = {"id": insight_id} if insight_id is not None else {"short_id": insight_short_id}
        insight = Insight.objects.filter(team_id=team.id, deleted=False, **insight_filter).first()
        # Object-level access matters here: created_by may not be allowed to view the insight.
        if insight is None or not UserAccessControl(user=created_by, team=team).check_access_level_for_object(
            insight, "viewer"
        ):
            raise ValueError("Insight not found")
        insight_id = insight.id

    asset = ExportedAsset.objects.create(
        team=team,
        created_by=created_by,
        export_format=ExportedAsset.ExportFormat.PNG,
        export_context=export_context,
        insight_id=insight_id,
        is_system=is_system,
        # None keeps the model's format-default TTL (see ExportedAsset.save).
        expires_after=expires_after,
    )

    async def _run() -> None:
        client = await async_connect()
        await client.execute_workflow(
            ExportAssetWorkflow.run,
            ExportAssetWorkflowInputs(
                exported_asset_id=asset.id,
                team_id=team.id,
                distinct_id=str(created_by.distinct_id),
            ),
            id=f"export-asset-{asset.id}",
            task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            execution_timeout=RENDER_TIMEOUT,
        )

    try:
        async_to_sync(_run)()
    except Exception as e:
        # export_asset_direct records activity failures on the asset, but a dispatch
        # failure (Temporal unreachable, workflow never started) would leave
        # asset.exception empty — record it so the documented failure contract
        # ("bytes are None and asset.exception carries the error") always holds.
        logger.info("render_png_export_failed", asset_id=asset.id, error=str(e))
        asset.refresh_from_db()
        if not asset.exception:
            asset.exception = str(e) or "Export dispatch failed"
            asset.save(update_fields=["exception"])

    asset.refresh_from_db()
    if asset.exception:
        return asset, None
    content = asset.content
    if not content and asset.content_location:
        content = object_storage.read_bytes(asset.content_location)
    if not content:
        # A workflow that reports success but stores nothing would otherwise return no bytes
        # and no exception, leaving callers unable to tell it apart from a successful render.
        asset.exception = "Export produced no content"
        asset.save(update_fields=["exception"])
        return asset, None
    return asset, bytes(content)
