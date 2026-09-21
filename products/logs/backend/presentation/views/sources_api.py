from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from django.conf import settings
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_api_host
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.logs.backend.facade.sources import (
    AWS_REGION_RE,
    FIREHOSE_BUFFER_INTERVAL_SECONDS,
    FIREHOSE_BUFFER_SIZE_MB,
    FIREHOSE_ENDPOINT_PATH,
    FIREHOSE_RETRY_DURATION_SECONDS,
    NO_DELIVERIES,
    LogsSource,
    LogsSourceHealthStatus,
    LogsSourceProvider,
    fetch_sources_health,
    quick_create_url,
)


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
        return LogsSource.objects.for_team(validated_data["team"].id).create(**validated_data)


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
    # A template rather than a URL: the log group is left as a placeholder the customer replaces,
    # so `URLField` would advertise a `uri` that does not resolve as given.
    quick_create_url = serializers.CharField(
        allow_null=True,
        help_text=(
            "CloudFormation quick-create link with the endpoint, key and stack name filled in, and the log group "
            "left as a placeholder for the customer to replace. Null when no template is published."
        ),
    )


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
        instance = serializer.save(team=self.team, created_by=user if user.is_authenticated else None)
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
        endpoint_url = f"{get_api_host()}{endpoint_path}"
        region = str(source.config.get("region", ""))
        data = {
            "endpoint_path": endpoint_path,
            "endpoint_url": endpoint_url,
            "access_key": self.team.api_token,
            "buffering_size_mb": FIREHOSE_BUFFER_SIZE_MB,
            "buffering_interval_seconds": FIREHOSE_BUFFER_INTERVAL_SECONDS,
            "retry_duration_seconds": FIREHOSE_RETRY_DURATION_SECONDS,
            "content_encoding": "GZIP",
            "quick_create_url": (
                quick_create_url(
                    region=region,
                    template_url=settings.LOGS_CLOUD_SOURCES_TEMPLATE_URL,
                    endpoint_url=endpoint_url,
                    access_key=self.team.api_token,
                    source_name=source.name,
                    source_id=str(source.id),
                )
                if settings.LOGS_CLOUD_SOURCES_TEMPLATE_URL
                else None
            ),
        }
        return Response(LogsSourceSetupSerializer(data).data)

    @extend_schema(
        request=None,
        responses={200: LogsSourcesHealthSerializer},
        description="Delivery status of every source in this environment over the last 24 hours, from ingestion metrics.",
    )
    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        sources = list(self.get_queryset().values_list("id", "enabled"))
        now = datetime.now(UTC)
        health = fetch_sources_health(self.team_id, [str(source_id) for source_id, _ in sources], now)
        data = {
            "sources": {
                str(source_id): health.get(str(source_id), NO_DELIVERIES).as_payload(enabled=enabled, now=now)
                for source_id, enabled in sources
            }
        }
        return Response(LogsSourcesHealthSerializer(data).data)
