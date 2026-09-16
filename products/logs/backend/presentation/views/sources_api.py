from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django.db import models
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import get_api_host
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.logs.backend.facade.sources import LogsSource, LogsSourceProvider

# Matches every commercial, GovCloud and isolated AWS region name, e.g. us-east-1, eu-central-2, us-gov-west-1.
AWS_REGION_RE = r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d$"

FIREHOSE_ENDPOINT_PATH = "/i/v1/logs/aws/firehose"

# Firehose buffering that keeps one request under capture-logs' body limit once CloudWatch's
# gzip output is base64-encoded, while still delivering within about a minute.
FIREHOSE_BUFFER_SIZE_MB = 1
FIREHOSE_BUFFER_INTERVAL_SECONDS = 60
FIREHOSE_RETRY_DURATION_SECONDS = 300

# app_metrics2 rows the logs consumer writes per source, keyed by instance_id = source id.
SOURCE_RECEIVED_METRIC = "source_records_received"
SOURCE_DROPPED_METRIC = "source_records_dropped"
HEALTH_WINDOW = timedelta(hours=24)
# app_metrics2 truncates timestamps to the hour, so "recent" has to allow a full bucket plus slack.
STALE_AFTER = timedelta(hours=2)


class LogsSourceHealthStatus(models.TextChoices):
    RECEIVING = "receiving", "Receiving"
    WAITING = "waiting", "Waiting for first delivery"
    STALE = "stale", "No recent data"
    DISABLED = "disabled", "Disabled"


@frozen
class SourceHealth:
    last_received_at: datetime | None
    records_received_24h: int
    records_dropped_24h: int

    def status(self, *, enabled: bool, now: datetime) -> LogsSourceHealthStatus:
        if not enabled:
            return LogsSourceHealthStatus.DISABLED
        if self.last_received_at is None:
            return LogsSourceHealthStatus.WAITING
        if now - self.last_received_at > STALE_AFTER:
            return LogsSourceHealthStatus.STALE
        return LogsSourceHealthStatus.RECEIVING


NO_DELIVERIES = SourceHealth(last_received_at=None, records_received_24h=0, records_dropped_24h=0)


class LogsSourceConfigSerializer(serializers.Serializer):
    region = serializers.RegexField(
        AWS_REGION_RE,
        help_text="AWS region of the CloudWatch log groups and the Firehose stream, e.g. us-east-1.",
    )
    default_labels = serializers.DictField(
        child=serializers.CharField(max_length=1024),
        required=False,
        default=dict,
        help_text='Resource attributes added to every log row from this source, e.g. {"env": "prod"}.',
    )
    service_name_overrides = serializers.DictField(
        child=serializers.CharField(max_length=512),
        required=False,
        default=dict,
        help_text="Map of CloudWatch log group name to the service.name it should carry, overriding the inferred value.",
    )

    def to_representation(self, instance: Any) -> Any:
        # A row written by another path may lack keys; reading must not 500 on it.
        return super().to_representation({"region": "", "default_labels": {}, "service_name_overrides": {}, **instance})


class LogsSourceSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this log source.")
    name = serializers.CharField(max_length=255, help_text="User-visible label for this source.")
    provider = serializers.ChoiceField(
        choices=LogsSourceProvider.choices, help_text="Cloud provider the logs come from."
    )
    mode = serializers.CharField(
        read_only=True,
        help_text="How logs reach PostHog. Only push, where the provider delivers to a PostHog endpoint, exists.",
    )
    enabled = serializers.BooleanField(
        default=True,
        help_text="When false, ingestion drops deliveries that carry this source id.",
    )
    config = LogsSourceConfigSerializer(help_text="Provider-specific settings.")
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True, help_text="Id of the user who created this source."
    )

    class Meta:
        model = LogsSource
        fields = [
            "id",
            "name",
            "provider",
            "mode",
            "enabled",
            "config",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "mode", "created_by", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if self.instance is not None and self.partial and "config" in attrs:
            # A partial PATCH of config must merge into the stored config, otherwise the keys the
            # client did not send (region above all) are silently erased.
            merged = LogsSourceConfigSerializer(data={**self.instance.config, **attrs["config"]})
            merged.is_valid(raise_exception=True)
            attrs["config"] = merged.validated_data
        return attrs

    def create(self, validated_data: dict[str, Any]) -> LogsSource:
        # The environment-scoped manager refuses ambient access, so create through for_team().
        team_id = validated_data["team_id"]
        return LogsSource.objects.for_team(team_id).create(**validated_data)


class LogsSourceSetupSerializer(serializers.Serializer):
    endpoint_path = serializers.CharField(
        help_text="Path of the Firehose HTTP endpoint for this source, relative to the ingestion host."
    )
    endpoint_url = serializers.URLField(help_text="Full HTTPS URL to configure as the Firehose HTTP endpoint.")
    access_key = serializers.CharField(
        help_text="Value for the Firehose access key field. This is the project API key."
    )
    buffering_size_mb = serializers.IntegerField(help_text="Recommended Firehose buffer size in MB.")
    buffering_interval_seconds = serializers.IntegerField(help_text="Recommended Firehose buffer interval.")
    retry_duration_seconds = serializers.IntegerField(help_text="Recommended Firehose retry duration.")
    content_encoding = serializers.CharField(help_text="Recommended Firehose content encoding.")


class LogsSourceHealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=LogsSourceHealthStatus.choices,
        help_text="receiving: data arrived in the last two hours. waiting: nothing received yet. stale: data stopped. disabled: the source is switched off.",
    )
    last_received_at = serializers.DateTimeField(
        allow_null=True,
        help_text="Hour bucket in which the most recent batch from this source was ingested, if any in the last 24 hours.",
    )
    records_received_24h = serializers.IntegerField(
        help_text="Log records this source delivered in the last 24 hours, counted before quota, sampling and exclusion rules apply."
    )
    records_dropped_24h = serializers.IntegerField(
        help_text="Log records dropped from this source in the last 24 hours, for example while it was disabled."
    )


class LogsSourcesHealthSerializer(serializers.Serializer):
    sources = serializers.DictField(
        child=LogsSourceHealthSerializer(),
        help_text="Delivery status of every source in this environment, keyed by source id.",
    )


def fetch_sources_health(team_id: int, source_ids: list[str], now: datetime) -> dict[str, SourceHealth]:
    """One ClickHouse query for every source in the environment, so a sources list costs one round trip."""
    if not source_ids:
        return {}
    tag_queries(product=Product.LOGS, feature=Feature.QUERY, source="logs_sources_health", team_id=str(team_id))
    rows = sync_execute(
        """
        SELECT
            instance_id,
            maxOrNullIf(timestamp, metric_name = %(received)s),
            sumIf(count, metric_name = %(received)s),
            sumIf(count, metric_name = %(dropped)s)
        FROM app_metrics2
        WHERE team_id = %(team_id)s
          AND app_source = 'logs'
          AND app_source_id = ''
          AND instance_id IN %(instance_ids)s
          AND metric_name IN (%(received)s, %(dropped)s)
          AND timestamp >= toDateTime64(%(after)s, 6)
        GROUP BY instance_id
        """,
        {
            "team_id": team_id,
            "instance_ids": source_ids,
            "received": SOURCE_RECEIVED_METRIC,
            "dropped": SOURCE_DROPPED_METRIC,
            "after": (now - HEALTH_WINDOW).strftime("%Y-%m-%dT%H:%M:%S"),
        },
        team_id=team_id,
    )
    health: dict[str, SourceHealth] = {}
    for instance_id, last_received_at, received, dropped in rows or []:
        if last_received_at is not None and last_received_at.tzinfo is None:
            last_received_at = last_received_at.replace(tzinfo=UTC)
        health[str(instance_id)] = SourceHealth(
            last_received_at=last_received_at,
            records_received_24h=int(received or 0),
            records_dropped_24h=int(dropped or 0),
        )
    return health


class LogsSourceViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    # `.unscoped()` because this evaluates at import time; `safely_get_queryset` scopes per request
    # by the environment's own id, never the canonical project id (sources are per environment).
    queryset = LogsSource.objects.unscoped().order_by("created_at")
    serializer_class = LogsSourceSerializer
    lookup_field = "id"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        user = cast(User, self.request.user)
        instance = serializer.save(team_id=self.team_id, created_by=user if user.is_authenticated else None)
        report_user_action(
            user,
            "logs source created",
            {"source_id": str(instance.id), "provider": instance.provider, "mode": instance.mode},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        user = cast(User, self.request.user)
        instance = cast(LogsSource, serializer.save())
        report_user_action(
            user,
            "logs source updated",
            {"source_id": str(instance.id), "provider": instance.provider, "enabled": instance.enabled},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsSource) -> None:
        user = cast(User, self.request.user)
        report_user_action(
            user,
            "logs source deleted",
            {"source_id": str(instance.id), "provider": instance.provider},
            team=self.team,
            request=self.request,
        )
        super().perform_destroy(instance)

    @extend_schema(
        request=None,
        responses={200: LogsSourceSetupSerializer},
        description="Values to configure on the customer's Firehose stream so it delivers to this source.",
    )
    @action(detail=True, methods=["get"], url_path="setup")
    def firehose_setup(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        source = cast(LogsSource, self.get_object())
        endpoint_path = f"{FIREHOSE_ENDPOINT_PATH}/{source.id}"
        data = {
            "endpoint_path": endpoint_path,
            "endpoint_url": f"{get_api_host()}{endpoint_path}",
            "access_key": self.team.api_token,
            "buffering_size_mb": FIREHOSE_BUFFER_SIZE_MB,
            "buffering_interval_seconds": FIREHOSE_BUFFER_INTERVAL_SECONDS,
            "retry_duration_seconds": FIREHOSE_RETRY_DURATION_SECONDS,
            "content_encoding": "GZIP",
        }
        return Response(LogsSourceSetupSerializer(data).data)

    @extend_schema(
        request=None,
        responses={200: LogsSourcesHealthSerializer},
        description="Delivery status of every source in this environment over the last 24 hours, from ingestion metrics.",
    )
    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        sources = list(self.safely_get_queryset(LogsSource.objects.unscoped()))
        now = datetime.now(UTC)
        health = fetch_sources_health(self.team_id, [str(source.id) for source in sources], now)
        data = {
            "sources": {
                str(source.id): {
                    "status": (h := health.get(str(source.id), NO_DELIVERIES)).status(enabled=source.enabled, now=now),
                    "last_received_at": h.last_received_at,
                    "records_received_24h": h.records_received_24h,
                    "records_dropped_24h": h.records_dropped_24h,
                }
                for source in sources
            }
        }
        return Response(LogsSourcesHealthSerializer(data).data)
