from __future__ import annotations

import re
from functools import cached_property
from typing import Any, cast

from django.db import connection, transaction
from django.db.models import F, QuerySet

from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from posthog.schema import PropertyGroupFilter

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rbac.user_access_control import UserAccessControl

from products.logs.backend.models import (
    MAX_ENABLED_METRIC_RULES,
    MAX_METRIC_RULE_GROUP_BY_KEYS,
    METRIC_RULE_GROUP_BY_TOP_LEVEL_KEYS,
    LogsMetricRule,
)
from products.logs.backend.presentation.filter_group_validation import (
    MAX_FILTER_GROUP_DEPTH,
    MAX_FILTER_GROUP_LEAF_VALUES,
    MAX_FILTER_GROUP_NODES,
    MAX_FILTER_GROUP_VALUE_LENGTH,
    filter_group_depth,
    filter_group_has_empty_group,
    filter_group_has_oversized_value,
    filter_group_leaf_value_count,
    filter_group_node_count,
)

# OTLP-safe metric name: leading letter, then letters/digits/dot/underscore/dash.
METRIC_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]*$")

ATTRIBUTE_KEY_PREFIXES = ("attributes.", "resource_attributes.")

# Advisory-lock namespace for `pg_advisory_xact_lock(ns, canonical_team_id)` — serializes
# metric-rule writes per team so the enabled-rule cap can't be raced past.
_METRIC_RULE_LOCK_NAMESPACE = 0x106_2E7A  # "LOG-RULE"-ish; just needs to be unique enough.


class MetricRuleCanonicalTeamPermission(BasePermission):
    """Authorize against the canonical (data-owning) team, not just the URL environment team.

    LogsMetricRule rows canonicalize to the parent (project-root) team on save, so a request made
    against a child environment reads and writes the PARENT's rules. The default team gate only
    checks membership of the URL team; re-anchor authorization to the canonical team so a
    credential scoped solely to a child environment can't touch the parent's rules. Mirrors
    stamphog's StamphogCanonicalTeamAccessPermission.
    """

    message = "You don't have access to the project that owns this data."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user.is_authenticated:
            return True  # IsAuthenticated handles the unauthenticated case first
        assert isinstance(view, LogsMetricRuleViewSet)
        team = view.team
        if team.parent_team_id is None or team.parent_team_id == team.id or team.parent_team is None:
            return True
        authenticator = request.successful_authenticator
        scoped_teams = None
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            scoped_teams = authenticator.access_token.scoped_teams
        elif isinstance(authenticator, PersonalAPIKeyAuthentication):
            scoped_teams = authenticator.personal_api_key.scoped_teams
        if scoped_teams and team.parent_team_id not in scoped_teams:
            return False
        level = view.user_permissions.team(team.parent_team).effective_membership_level
        return level is not None


class LogsMetricRuleSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this metric rule.")
    name = serializers.CharField(max_length=255, help_text="User-visible label for this rule.")
    metric_name = serializers.CharField(
        max_length=200,
        help_text=(
            "Name of the generated metric as it appears in the Metrics product. Must start with a letter and "
            "contain only letters, digits, dots, underscores, and dashes. Unique per project and immutable "
            "after creation — create a new rule to emit under a different name."
        ),
    )
    enabled = serializers.BooleanField(
        default=False,
        help_text=f"When true, ingestion evaluates this rule against every log record. At most {MAX_ENABLED_METRIC_RULES} rules can be enabled per project.",
    )
    filter_group = serializers.JSONField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "PropertyGroupFilter JSON (AND/OR tree of property predicates) selecting which log records feed the "
            'metric, e.g. `{"type":"AND","values":[{"type":"AND","values":[{"key":"service.name","operator":"exact",'
            '"value":"api","type":"log_attribute"}]}]}`. Null matches every ingested log record. Every group must '
            "contain at least one filter — empty groups never match."
        ),
    )
    value_attribute = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=512,
        default=None,
        help_text=(
            "Log attribute key holding a numeric value to aggregate into a distribution (count + sum), e.g. "
            "`attributes.duration_ms` or `resource_attributes.batch.size`. Omit to count matching log records "
            "instead. Immutable after creation — it determines the emitted metric type."
        ),
    )
    group_by = serializers.ListField(
        child=serializers.CharField(max_length=512),
        required=False,
        default=list,
        help_text=(
            f"Up to {MAX_METRIC_RULE_GROUP_BY_KEYS} dimension keys; each distinct value combination becomes its own "
            f"metric series. Allowed: {', '.join(METRIC_RULE_GROUP_BY_TOP_LEVEL_KEYS)}, or map keys prefixed with "
            "`attributes.` / `resource_attributes.`. Avoid high-cardinality keys (user IDs, request IDs) — excess "
            "series are dropped at ingestion."
        ),
    )
    version = serializers.IntegerField(
        read_only=True, help_text="Incremented on each update for worker cache coherency."
    )
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)  # ty: ignore[invalid-assignment]

    class Meta:
        model = LogsMetricRule
        fields = [
            "id",
            "name",
            "metric_name",
            "enabled",
            "filter_group",
            "value_attribute",
            "group_by",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]

    def validate_metric_name(self, value: str) -> str:
        if not METRIC_NAME_PATTERN.match(value):
            raise ValidationError(
                "Metric name must start with a letter and contain only letters, digits, dots, underscores, and dashes."
            )
        return value

    def validate_group_by(self, value: list[str]) -> list[str]:
        if len(value) > MAX_METRIC_RULE_GROUP_BY_KEYS:
            raise ValidationError(f"At most {MAX_METRIC_RULE_GROUP_BY_KEYS} group-by keys are allowed.")
        for key in value:
            if key in METRIC_RULE_GROUP_BY_TOP_LEVEL_KEYS:
                continue
            if any(key.startswith(prefix) and len(key) > len(prefix) for prefix in ATTRIBUTE_KEY_PREFIXES):
                continue
            raise ValidationError(
                f"Invalid group-by key {key!r}. Use one of {', '.join(METRIC_RULE_GROUP_BY_TOP_LEVEL_KEYS)}, or a "
                "key prefixed with `attributes.` / `resource_attributes.`."
            )
        return value

    def validate_value_attribute(self, value: str | None) -> str | None:
        if value is None:
            return value
        if not any(value.startswith(prefix) and len(value) > len(prefix) for prefix in ATTRIBUTE_KEY_PREFIXES):
            raise ValidationError("value_attribute must be prefixed with `attributes.` or `resource_attributes.`.")
        return value

    def validate_filter_group(self, value: Any) -> Any:
        if value is None:
            return value
        try:
            PropertyGroupFilter.model_validate(value)
        except PydanticValidationError as e:
            raise ValidationError(f"Invalid filter_group shape: {e.errors()[0]['msg']}")
        if filter_group_depth(value) > MAX_FILTER_GROUP_DEPTH:
            raise ValidationError(f"filter_group is nested too deeply (max depth {MAX_FILTER_GROUP_DEPTH}).")
        if filter_group_node_count(value) > MAX_FILTER_GROUP_NODES:
            raise ValidationError(f"filter_group has too many nodes (max {MAX_FILTER_GROUP_NODES} groups + leaves).")
        if filter_group_leaf_value_count(value) > MAX_FILTER_GROUP_LEAF_VALUES:
            raise ValidationError(
                f"filter_group has too many filter values (max {MAX_FILTER_GROUP_LEAF_VALUES} across all filters)."
            )
        if filter_group_has_oversized_value(value):
            raise ValidationError(
                f"filter_group contains a value longer than {MAX_FILTER_GROUP_VALUE_LENGTH} characters."
            )
        if filter_group_has_empty_group(value):
            raise ValidationError(
                "Every group in filter_group must contain at least one filter — an empty group never matches, "
                "so the rule would never produce data points. Omit filter_group to match all logs."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if self.instance is not None:
            self._validate_immutable_fields(attrs)
        return attrs

    def _validate_immutable_fields(self, attrs: dict[str, Any]) -> None:
        assert self.instance is not None
        # `initial_data` (not validated attrs) distinguishes "field omitted from PATCH"
        # from "field explicitly sent" — defaults would otherwise read as a change.
        for field in ("metric_name", "value_attribute"):
            if field in self.initial_data and attrs.get(field) != getattr(self.instance, field):
                raise ValidationError({field: f"{field} is immutable after creation — create a new rule to change it."})


class LogsMetricRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    # `.unscoped()` because this evaluates at import time, before any team context exists;
    # `safely_get_queryset` re-applies the team filter per request.
    queryset = LogsMetricRule.objects.unscoped().order_by("created_at")
    serializer_class = LogsMetricRuleSerializer
    lookup_field = "id"
    posthog_feature_flag = "logs-metric-rules"
    permission_classes = [PostHogFeatureFlagPermission, MetricRuleCanonicalTeamPermission]

    @cached_property
    def canonical_team_id(self) -> int:
        # RootTeamMixin.save() stores rules under the parent (canonical) team; every read,
        # cap check, and version bump must target that same id or child-environment
        # requests silently miss the rows they just wrote.
        return resolve_effective_team_id(self.team_id)

    def _should_skip_parents_filter(self) -> bool:
        # safely_get_queryset scopes by canonical_team_id; the default parent-lookup filter
        # would AND the raw URL team id back in and hide rows stored under the parent.
        return True

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # Metric rules publish log attribute values into the Metrics product, so API-key
        # writes need authority over both resources.
        if self.action in ("create", "update", "partial_update", "destroy"):
            return ["logs:write", "metrics:write"]
        return None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.canonical_team_id)

    def _assert_metrics_editor_access(self, user: User) -> None:
        # Rule authors export log attribute values as metrics readable by anyone with
        # metrics access — creating or changing a rule therefore requires metrics editor
        # rights, so a logs editor can't publish logs data past a metrics restriction.
        canonical_team = self.team.parent_team or self.team
        user_access_control = UserAccessControl(user=user, team=canonical_team)
        if not user_access_control.check_access_level_for_resource("metrics", "editor"):
            raise PermissionDenied("Creating or updating metric rules requires editor access to metrics.")

    def _validate_team_limits(self, serializer: LogsMetricRuleSerializer, exclude_pk: Any = None) -> None:
        team_rules = LogsMetricRule.objects.filter(team_id=self.canonical_team_id)
        if exclude_pk is not None:
            team_rules = team_rules.exclude(pk=exclude_pk)

        metric_name = serializer.validated_data.get("metric_name")
        if metric_name and team_rules.filter(metric_name=metric_name).exists():
            raise ValidationError({"metric_name": "A rule already emits this metric name in this project."})

        wants_enabled = serializer.validated_data.get("enabled")
        if wants_enabled and team_rules.filter(enabled=True).count() >= MAX_ENABLED_METRIC_RULES:
            raise ValidationError(
                {"enabled": f"At most {MAX_ENABLED_METRIC_RULES} metric rules can be enabled per project."}
            )

    def _lock_team_rules(self) -> None:
        # Advisory xact lock serializes rule writes per canonical team so concurrent
        # requests can't all pass the enabled-rule count before any of them saves.
        # Must run inside transaction.atomic() — the lock releases on commit/rollback.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", [_METRIC_RULE_LOCK_NAMESPACE, self.canonical_team_id]
            )

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsMetricRuleSerializer, serializer)
        user = cast(User, self.request.user)
        self._assert_metrics_editor_access(user)
        with transaction.atomic():
            self._lock_team_rules()
            self._validate_team_limits(s)
            instance = s.save(
                team_id=self.canonical_team_id,
                created_by=user if user.is_authenticated else None,
                version=1,
            )
        report_user_action(
            user,
            "logs metric rule created",
            {"rule_id": str(instance.id), "is_distribution": instance.value_attribute is not None},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsMetricRuleSerializer, serializer)
        user = cast(User, self.request.user)
        assert s.instance is not None
        self._assert_metrics_editor_access(user)
        with transaction.atomic():
            self._lock_team_rules()
            self._validate_team_limits(s, exclude_pk=s.instance.pk)
            instance = cast(LogsMetricRule, s.save())
            LogsMetricRule.objects.filter(pk=instance.pk, team_id=self.canonical_team_id).update(
                version=F("version") + 1
            )
        instance.refresh_from_db(fields=["version", "updated_at"])
        report_user_action(
            user,
            "logs metric rule updated",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsMetricRule) -> None:
        user = cast(User, self.request.user)
        report_user_action(
            user,
            "logs metric rule deleted",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )
        super().perform_destroy(instance)
