import json
import hashlib
from datetime import datetime, timedelta
from typing import Final, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction
from django.utils import timezone

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import CachedHogQLQueryResponse, HogQLQuery, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.printer import to_printed_hogql

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.models.utils import uuid7

from products.cdp.backend.facade.api import compile_filters_expr
from products.mcp_events.backend.facade.contracts import (
    MCP_EVENT_NAME,
    MCPEventData,
    MCPEventEnvelope,
    MCPEventPreview,
    MCPEventSubscriptionPage,
    MCPEventSubscriptionRecord,
)
from products.mcp_events.backend.logic.callback import verify_callback
from products.mcp_events.backend.logic.destination import disable_destination, save_destination
from products.mcp_events.backend.logic.filters import (
    MCPEventFilterAccessValidator,
    parse_event_filters,
    restricted_event_property_names,
)
from products.mcp_events.backend.logic.properties import MCPEventPropertyAccess
from products.mcp_events.backend.models import MCPEventSubscription

EXPIRY_BATCH_SIZE: Final = 500
MAX_SUBSCRIPTIONS_PER_USER: Final = 20
MAX_SUBSCRIPTIONS_PER_PROJECT: Final = 100
MAX_TTL_MS: Final = 24 * 60 * 60 * 1000
PREVIEW_LOOKBACK_DAYS: Final = 7
PREVIEW_SAMPLE_LIMIT: Final = 5
VERIFICATION_REUSE_WINDOW: Final = timedelta(hours=1)
# Arbitrary namespace for pg_advisory_xact_lock, so the quota lock cannot collide with another feature's lock.
QUOTA_LOCK_NAMESPACE: Final = 0x4D435045


def subscription_record(subscription: MCPEventSubscription) -> MCPEventSubscriptionRecord:
    return MCPEventSubscriptionRecord(
        id=subscription.id,
        arguments=cast(dict[str, JsonValue], subscription.arguments),
        callback_host=urlsplit(subscription.delivery["url"]).hostname or "",
        expires_at=subscription.expires_at,
        active=subscription.active,
        created_at=subscription.created_at,
    )


def deactivate(subscription: MCPEventSubscription) -> None:
    """Stop delivery. The caller holds the row lock."""
    subscription.active = False
    subscription.generation = uuid7()
    subscription.save(update_fields=["active", "generation", "updated_at"])
    disable_destination(subscription)


class MCPEventSubscriptions:
    def __init__(self, *, team: Team, user: User, principal: str) -> None:
        self.team = team
        self.user = user
        self.principal = principal

    def normalize_filters(self, raw_filters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        MCPEventFilterAccessValidator.validate_actions(raw_filters, team=self.team, user=self.user)
        filters = parse_event_filters(raw_filters, team=self.team, enabled=True)
        MCPEventFilterAccessValidator.validate_snapshot(
            MCPEventFilterAccessValidator.property_dependencies(filters, team=self.team),
            team=self.team,
            user=self.user,
        )
        try:
            to_printed_hogql(
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=compile_filters_expr(filters, team_id=self.team.pk),
                ),
                self.team,
            )
        except QueryError as error:
            raise ValidationError(
                {
                    "filters": "This filter cannot be previewed. Use functions supported by HogQL queries and real-time destinations."
                }
            ) from error
        return filters

    def identity(self, filters: dict[str, JsonValue], url: str) -> UUID:
        arguments = json.dumps({"project_id": self.team.pk, "filters": filters}, sort_keys=True, separators=(",", ":"))
        identity = json.dumps([self.principal, MCP_EVENT_NAME, url, arguments], separators=(",", ":"))
        return uuid5(NAMESPACE_URL, hashlib.sha256(identity.encode()).hexdigest())

    def list_subscriptions(self, *, limit: int, offset: int) -> MCPEventSubscriptionPage:
        subscriptions = (
            MCPEventSubscription.objects.for_team(self.team.pk)
            .filter(created_by=self.user)
            .order_by("-created_at", "-id")
        )
        return MCPEventSubscriptionPage(
            count=subscriptions.count(),
            results=[subscription_record(subscription) for subscription in subscriptions[offset : offset + limit]],
        )

    def get(self, subscription_id: UUID) -> MCPEventSubscriptionRecord | None:
        subscription = (
            MCPEventSubscription.objects.for_team(self.team.pk).filter(created_by=self.user, pk=subscription_id).first()
        )
        return subscription_record(subscription) if subscription is not None else None

    def preview(self, raw_filters: dict[str, JsonValue]) -> MCPEventPreview:
        filters = self.normalize_filters(raw_filters)
        cutoff = timezone.now() - timedelta(days=PREVIEW_LOOKBACK_DAYS)
        query = ast.SelectQuery(
            select=[ast.Field(chain=[field]) for field in ("uuid", "event", "distinct_id", "timestamp", "properties")],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    compile_filters_expr(filters, team_id=self.team.pk),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=cutoff),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=PREVIEW_SAMPLE_LIMIT),
        )
        with tags_context(product=Product.PIPELINE_DESTINATIONS, feature=Feature.QUERY, api_queries_budgeted=True):
            runner = HogQLQueryRunner(
                query=HogQLQuery(query=to_printed_hogql(query, self.team)), team=self.team, user=self.user
            )
            runner.is_query_service = True
            result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)
            assert isinstance(result, (HogQLQueryResponse, CachedHogQLQueryResponse))
        redaction = MCPEventPropertyAccess.redaction(restricted_event_property_names(team=self.team, user=self.user))
        examples: list[MCPEventEnvelope] = []
        for event_id, event, distinct_id, timestamp, raw_properties in result.results or []:
            properties = json.loads(raw_properties) if isinstance(raw_properties, str) else raw_properties
            examples.append(
                MCPEventEnvelope(
                    eventId=str(event_id),
                    name=MCP_EVENT_NAME,
                    timestamp=timestamp,
                    data=MCPEventData(
                        event=str(event),
                        distinct_id=str(distinct_id),
                        properties=MCPEventPropertyAccess.redact(
                            properties if isinstance(properties, dict) else {}, redaction
                        ),
                    ),
                    cursor=None,
                )
            )
        return MCPEventPreview(
            filters=filters,
            examples=examples,
            lookback_days=PREVIEW_LOOKBACK_DAYS,
            sample_limit=PREVIEW_SAMPLE_LIMIT,
        )

    def subscribe(
        self,
        *,
        raw_filters: dict[str, JsonValue],
        url: str,
        secret: str,
        ttl_ms: int | None,
        credential_expires_at: datetime | None,
    ) -> MCPEventSubscriptionRecord:
        filters = self.normalize_filters(raw_filters)
        subscription_id = self.identity(filters, url)
        now = timezone.now()
        existing = (
            MCPEventSubscription.objects.for_team(self.team.pk)
            .filter(id=subscription_id, created_by=self.user, principal=self.principal)
            .first()
        )
        verified = bool(
            existing
            and existing.active
            and existing.expires_at > now
            and existing.verified_at
            and existing.verified_at > now - VERIFICATION_REUSE_WINDOW
            and existing.delivery["secret"] == secret
        )
        if not verified:
            verify_callback(subscription_id=str(subscription_id), url=url, secret=secret)

        now = timezone.now()
        if credential_expires_at is not None and credential_expires_at <= now:
            raise PermissionDenied("The subscription credential expired. Reconnect and try again.")
        with transaction.atomic():
            # Serialize project quota admission without locking a busy Team row.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [QUOTA_LOCK_NAMESPACE, self.team.pk])
            subscription, created = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .select_for_update()
                .get_or_create(
                    id=subscription_id,
                    defaults={
                        "team_id": self.team.pk,
                        "created_by": self.user,
                        "principal": self.principal,
                        "arguments": {"project_id": self.team.pk, "filters": filters},
                        "delivery": {"url": url, "secret": secret},
                        "expires_at": now,
                    },
                )
            )
            live = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .filter(active=True, expires_at__gt=now)
                .exclude(id=subscription_id)
            )
            if (
                live.count() >= MAX_SUBSCRIPTIONS_PER_PROJECT
                or live.filter(created_by=self.user).count() >= MAX_SUBSCRIPTIONS_PER_USER
            ):
                raise ValidationError("Subscription limit reached. Stop an existing subscription and try again.")
            if subscription.created_by_id != self.user.pk or subscription.principal != self.principal:
                raise PermissionDenied("This subscription belongs to another account.")
            if created or not subscription.active or subscription.expires_at <= now:
                subscription.generation = uuid7()
            subscription.delivery = {"url": url, "secret": secret}
            subscription.expires_at = now + timedelta(milliseconds=min(ttl_ms or MAX_TTL_MS, MAX_TTL_MS))
            if credential_expires_at is not None:
                subscription.expires_at = min(subscription.expires_at, credential_expires_at)
            if not verified:
                subscription.verified_at = now
            subscription.renewed_at = now
            subscription.active = True
            subscription.property_dependencies = MCPEventFilterAccessValidator.property_dependencies(
                filters, team=self.team
            )
            subscription.restricted_properties = restricted_event_property_names(team=self.team, user=self.user)
            subscription.hog_function_id = save_destination(subscription)
            subscription.save()
        return subscription_record(subscription)

    def unsubscribe(self, *, raw_filters: dict[str, JsonValue], url: str) -> None:
        # Cancelling must work after a filtered action is deleted, so the filters are parsed without compiling.
        filters = parse_event_filters(raw_filters, team=self.team, enabled=False)
        with transaction.atomic():
            subscription = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .select_for_update()
                .filter(id=self.identity(filters, url), created_by=self.user, principal=self.principal)
                .first()
            )
            if subscription is not None:
                deactivate(subscription)

    @staticmethod
    def expire() -> int:
        # A bounded cross-project sweep discovers work; each mutation uses its own team scope and lock.
        candidates = list(
            MCPEventSubscription.objects.unscoped()
            .filter(active=True, expires_at__lte=timezone.now())
            .order_by("expires_at")
            .values_list("team_id", "id")[:EXPIRY_BATCH_SIZE]
        )
        count = 0
        for team_id, subscription_id in candidates:
            with transaction.atomic():
                subscription = (
                    MCPEventSubscription.objects.for_team(team_id)
                    .select_for_update()
                    .filter(id=subscription_id, active=True, expires_at__lte=timezone.now())
                    .first()
                )
                if subscription is None:
                    continue
                deactivate(subscription)
                count += 1
        return count
