from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.db.models import F, Max, QuerySet

from drf_spectacular.utils import extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilter

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import LOGS_RETENTION_FEATURES_BY_DAYS
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.logs.backend.facade.retention import suggest_retention_rule_name
from products.logs.backend.models import LogsRetentionRule
from products.logs.backend.presentation.filter_group_validation import (
    MAX_FILTER_GROUP_DEPTH,
    MAX_FILTER_GROUP_LEAF_VALUES,
    MAX_FILTER_GROUP_NODES,
    MAX_FILTER_GROUP_VALUE_LENGTH,
    filter_group_depth,
    filter_group_has_oversized_value,
    filter_group_leaf_value_count,
    filter_group_node_count,
)

# Retention tiers a rule may assign. Derived from the same source as the team-wide setting in
# `TeamSerializer` (`posthog/api/team.py`): 14 is the always-available default, and every other
# tier must have an entitlement feature in `LOGS_RETENTION_FEATURES_BY_DAYS` (currently just 30).
# Deriving it keeps rules in lockstep with the team-wide setting — a per-log rule can never grant a
# tier the org couldn't set team-wide, and a new tier (e.g. 90) becomes available here the moment it
# gets an entitlement mapping.
VALID_RETENTION_DAYS = {14} | set(LOGS_RETENTION_FEATURES_BY_DAYS.keys())


def retention_filter_group_error(filter_group: Any) -> str | None:
    """Shape and size validation shared by rule writes and the name-suggestion endpoint.

    Returns a message describing the problem, or None when the group is valid. Callers nest the
    message under whichever field key their payload uses.
    """
    # A retention rule with no filter_group would match every log, silently overriding the
    # team default for all traffic — require an explicit selector.
    if filter_group is None:
        return "A retention rule requires a filter_group."
    # Validate shape against PropertyGroupFilter so malformed payloads are rejected at write time
    # rather than flowing through to the ingestion worker. Mirrors sampling_api / alerts_api.
    try:
        PropertyGroupFilter.model_validate(filter_group)
    except PydanticValidationError as e:
        return f"Invalid filter_group shape: {e.errors()[0]['msg']}"
    # Bound depth and total node count — the Node ingestion worker recurses per record over this
    # tree, so an adversarially deep or wide group is a stack-overflow + CPU footgun on every log
    # line. Matches MAX_FILTER_GROUP_DEPTH / MAX_FILTER_GROUP_NODES shared with the sampling rules.
    if filter_group_depth(filter_group) > MAX_FILTER_GROUP_DEPTH:
        return f"filter_group is nested too deeply (max depth {MAX_FILTER_GROUP_DEPTH})."
    if filter_group_node_count(filter_group) > MAX_FILTER_GROUP_NODES:
        return f"filter_group has too many nodes (max {MAX_FILTER_GROUP_NODES} groups + leaves)."
    # A single leaf can smuggle a huge value array or multi-megabyte string while counting as one
    # node — the ingestion matcher would then scan that per record. Bound total leaf values and
    # per-value length, matching the metric-rules validator.
    if filter_group_leaf_value_count(filter_group) > MAX_FILTER_GROUP_LEAF_VALUES:
        return f"filter_group has too many filter values (max {MAX_FILTER_GROUP_LEAF_VALUES} across all filters)."
    if filter_group_has_oversized_value(filter_group):
        return f"filter_group contains a value longer than {MAX_FILTER_GROUP_VALUE_LENGTH} characters."
    return None


class LogsRetentionRuleSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this retention rule.")
    name = serializers.CharField(max_length=255, help_text="User-visible label for this rule.")
    enabled = serializers.BooleanField(
        default=False,
        help_text="When false, the rule is ignored by ingestion and listing UIs that show active rules only.",
    )
    priority = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="Lower numbers are evaluated first; the first matching rule wins. Omit to append after existing rules.",
    )
    config = serializers.JSONField(
        help_text=(
            "Retention rule JSON. Required keys: `retention_days` (integer — how long matching logs are "
            "kept; must be a tier the organization is entitled to, same as the team-wide Logs retention "
            "setting) and `filter_group` (PropertyGroupFilter shape — an AND/OR tree of property "
            "predicates evaluated per record to decide which logs this rule matches). "
            'Example: `{"retention_days":30,"filter_group":{"type":"AND","values":[{"type":"AND",'
            '"values":[{"key":"service.name","operator":"exact","value":"api"}]}]}}`. Logs matching no '
            "enabled rule keep the environment's default retention."
        )
    )
    version = serializers.IntegerField(
        read_only=True, help_text="Incremented on each update for worker cache coherency."
    )
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)  # ty: ignore[invalid-assignment]

    class Meta:
        model = LogsRetentionRule
        fields = [
            "id",
            "name",
            "enabled",
            "priority",
            "config",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        config = attrs.get("config")
        if config is None and self.instance is not None:
            config = self.instance.config
        if not isinstance(config, dict):
            raise ValidationError({"config": "config must be a JSON object."})

        retention_days = config.get("retention_days")
        # bool is an int subclass — reject it explicitly so `true`/`false` don't slip through.
        if isinstance(retention_days, bool) or not isinstance(retention_days, int):
            raise ValidationError({"config": {"retention_days": "Must be an integer."}})
        if retention_days not in VALID_RETENTION_DAYS:
            raise ValidationError(
                {"config": {"retention_days": f"Must be one of {sorted(VALID_RETENTION_DAYS)} days."}}
            )
        # Gate paid tiers on the org entitlement, mirroring TeamSerializer.validate_logs_settings —
        # otherwise a Logs editor could grant a per-log retention tier the org can't set team-wide.
        required_feature = LOGS_RETENTION_FEATURES_BY_DAYS.get(retention_days)
        if required_feature is not None:
            get_organization = self.context.get("get_organization")
            organization = get_organization() if callable(get_organization) else None
            if organization is None or not organization.is_feature_available(required_feature):
                raise PermissionDenied(
                    f"This organization does not have permission to set Logs retention to {retention_days} days."
                )

        self._validate_filter_group(config.get("filter_group"))
        return attrs

    def _validate_filter_group(self, filter_group: Any) -> None:
        message = retention_filter_group_error(filter_group)
        if message:
            raise ValidationError({"config": {"filter_group": message}})


class LogsRetentionRuleReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Rule IDs in the desired evaluation order (first element is highest priority / lowest order index).",
    )


class LogsRetentionRuleSuggestNameSerializer(serializers.Serializer):
    retention_days = serializers.IntegerField(help_text="Retention tier the rule would assign, in days.")
    filter_group = serializers.JSONField(help_text="PropertyGroupFilter tree the rule would match on.")

    def validate_retention_days(self, value: int) -> int:
        if value not in VALID_RETENTION_DAYS:
            raise ValidationError(f"Must be one of {sorted(VALID_RETENTION_DAYS)} days.")
        return value

    def validate_filter_group(self, value: Any) -> Any:
        # Same bounds as a real write — an unbounded tree must never reach the LLM prompt.
        message = retention_filter_group_error(value)
        if message:
            raise ValidationError(message)
        return value


class LogsRetentionRuleNameSuggestionSerializer(serializers.Serializer):
    name = serializers.CharField(
        allow_blank=True,
        help_text="Suggested rule name. Empty when no suggestion could be generated — clients hide the hint.",
    )


class LogsRetentionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsRetentionRule.objects.all().order_by("priority", "created_at")
    serializer_class = LogsRetentionRuleSerializer
    lookup_field = "id"
    posthog_feature_flag = "logs-settings-retention-rules"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsRetentionRuleSerializer, serializer)
        user = cast(User, self.request.user)
        # `or -1` would misfire when the current max is 0 (0 is falsy), so check for None explicitly.
        max_priority = LogsRetentionRule.objects.filter(team_id=self.team_id).aggregate(m=Max("priority"))["m"]
        raw_priority = s.validated_data.pop("priority", None)
        priority = int(raw_priority) if raw_priority is not None else (0 if max_priority is None else max_priority + 1)
        instance = s.save(
            team_id=self.team_id,
            created_by=user if user.is_authenticated else None,
            priority=priority,
            version=1,
        )
        report_user_action(
            user,
            "logs retention rule created",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsRetentionRuleSerializer, serializer)
        user = cast(User, self.request.user)
        # priority is managed via the reorder action; a null in an update payload would reach the
        # non-nullable column and raise a 500. Drop it so the stored value is preserved.
        if s.validated_data.get("priority") is None:
            s.validated_data.pop("priority", None)
        instance = cast(LogsRetentionRule, s.save())
        LogsRetentionRule.objects.filter(pk=instance.pk, team_id=self.team_id).update(version=F("version") + 1)
        instance.refresh_from_db(fields=["version", "updated_at"])
        report_user_action(
            user,
            "logs retention rule updated",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsRetentionRule) -> None:
        user = cast(User, self.request.user)
        report_user_action(
            user,
            "logs retention rule deleted",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )
        super().perform_destroy(instance)

    @extend_schema(
        request=LogsRetentionRuleReorderSerializer,
        responses={200: LogsRetentionRuleSerializer(many=True)},
        description="Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).",
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = LogsRetentionRuleReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data["ordered_ids"]
        with transaction.atomic():
            # Validate inside the transaction (and lock the rows) so a concurrent create/delete
            # can't invalidate the check between validation and the priority writes (TOCTOU).
            team_rule_ids = set(
                LogsRetentionRule.objects.select_for_update().filter(team_id=self.team_id).values_list("id", flat=True)
            )
            if set(ordered_ids) != team_rule_ids or len(ordered_ids) != len(team_rule_ids):
                raise ValidationError("ordered_ids must list every retention rule for this team exactly once.")
            for index, rid in enumerate(ordered_ids):
                LogsRetentionRule.objects.filter(id=rid, team_id=self.team_id).update(
                    priority=index,
                    version=F("version") + 1,
                )
        qs = self.safely_get_queryset(LogsRetentionRule.objects.all()).order_by("priority", "created_at")
        return Response(LogsRetentionRuleSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=LogsRetentionRuleSuggestNameSerializer,
        responses={200: LogsRetentionRuleNameSuggestionSerializer},
        description=(
            "Suggest a human-readable name for a retention rule from its retention tier and filter "
            "group. Used by the create form as an auto-suggest; nothing is persisted. Returns an empty "
            "name when a suggestion can't be generated."
        ),
    )
    # Each call is an inline LLM request, so it takes the shared AI rate limits. pagination_class=None
    # keeps drf-spectacular from attaching limit/offset params to a non-list response.
    @action(
        detail=False,
        methods=["post"],
        url_path="suggest_name",
        pagination_class=None,
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def suggest_name(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied("AI data processing must be approved by your organization to suggest names")
        serializer = LogsRetentionRuleSuggestNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        # A suggestion doesn't grant a retention tier, so entitlement is deliberately not checked here —
        # unlike a write, where LOGS_RETENTION_FEATURES_BY_DAYS gates the paid tiers.
        name = suggest_retention_rule_name(
            serializer.validated_data["retention_days"],
            serializer.validated_data["filter_group"],
            distinct_id=str(user.distinct_id) if user.is_authenticated else "logs-retention-name",
            team_id=self.team_id,
        )
        return Response({"name": name}, status=status.HTTP_200_OK)
