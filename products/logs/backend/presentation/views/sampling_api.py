from __future__ import annotations

from collections.abc import Mapping
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
from rest_framework.views import APIView

from posthog.schema import PropertyGroupFilter

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.logs.backend.models import LogsExclusionRule
from products.logs.backend.presentation.filter_group_validation import (
    MAX_FILTER_GROUP_DEPTH,
    MAX_FILTER_GROUP_NODES,
    filter_group_depth,
    filter_group_has_empty_group,
    filter_group_node_count,
)


class LogsSamplingRuleSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this sampling rule.")
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
    rule_type = serializers.ChoiceField(
        choices=LogsExclusionRule.RuleType.choices,
        help_text="Rule kind: severity_sampling, path_drop, or rate_limit (caps matching log volume at ingestion).",
    )
    scope_service = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=512,
        help_text="Optional legacy service-name scope; new rules use `config.filter_group` for matching instead.",
    )
    scope_path_pattern = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=1024,
        help_text="Optional regex matched against a path-like log attribute when present.",
    )
    scope_attribute_filters = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
        help_text='Optional list of predicates over string attributes, e.g. [{"key":"http.route","op":"eq","value":"/api"}].',
    )
    config = serializers.JSONField(
        help_text=(
            "Type-specific JSON. For path_drop: object with optional `filter_group` (PropertyGroupFilter shape — "
            "AND/OR tree of property predicates evaluated per record) and/or legacy `patterns` (list of regex strings) "
            "+ `match_attribute_key` (string). When both are present a record is dropped if EITHER matches. "
            'Filter group example: `{"type":"AND","values":[{"type":"AND","values":['
            '{"key":"service.name","operator":"exact","value":"api"}]}]}`. Every group in '
            "`filter_group` must contain at least one filter — empty groups never match, so the "
            "rule would never apply. "
            "For severity_sampling: object with `actions` per severity level and optional `always_keep`. "
            "For rate_limit: object with EITHER `logs_per_second` (integer 1–1000000, optional `burst_logs` "
            "integer ≥ logs_per_second, max 10000000) OR `kb_per_second` (integer 1–1000000 = 1 GB/s, "
            "optional `burst_kb` integer ≥ kb_per_second, max 10000000) — not both. Plus optional "
            "`filter_group` to narrow which logs the cap applies to. KB-mode charges each log its own "
            "uncompressed byte size, matching how billing measures ingested bytes."
        )
    )
    # `source` collides with DRF's Field.source typing (the attribute lookup), hence the ignore.
    source: serializers.ChoiceField = serializers.ChoiceField(  # type: ignore[assignment]
        choices=LogsExclusionRule.RecordSource.choices,
        # No serializer default: a generated client would then fill `logs` into every update body and trip
        # the immutability check on span rules. `validate()` applies the default on create only.
        required=False,
        help_text=(
            "Record source the rule filters: `logs` (default) runs in the logs pipeline, `spans` in the traces "
            "pipeline. Immutable after creation. Span rules support path_drop and rate_limit only."
        ),
    )
    version = serializers.IntegerField(
        read_only=True, help_text="Incremented on each update for worker cache coherency."
    )
    created_by: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)  # ty: ignore[invalid-assignment]

    class Meta:
        model = LogsExclusionRule
        fields = [
            "id",
            "name",
            "enabled",
            "priority",
            "rule_type",
            "scope_service",
            "scope_path_pattern",
            "scope_attribute_filters",
            "config",
            "source",
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if self.instance is not None:
            if "source" in self.initial_data and attrs.get("source") != self.instance.source:
                raise ValidationError({"source": "source is immutable after creation. Create a new rule instead."})
            attrs["source"] = self.instance.source
        else:
            attrs.setdefault("source", LogsExclusionRule.RecordSource.LOGS)
        rule_type = attrs.get("rule_type")
        if rule_type is None and self.instance is not None:
            rule_type = self.instance.rule_type
        if (
            attrs.get("source") == LogsExclusionRule.RecordSource.SPANS
            and rule_type == LogsExclusionRule.RuleType.SEVERITY_SAMPLING
        ):
            # Spans carry no severity, so every span would rank as info and one action would hit all of them.
            raise ValidationError({"rule_type": "severity_sampling rules are not supported for spans."})
        config = attrs.get("config")
        # Only reject vacuous groups on requests that actually write config: rows that
        # predate this validator can carry an empty group, and a PATCH of unrelated
        # fields (e.g. disabling the rule) must not be blocked by the stored config.
        reject_vacuous = config is not None
        if config is None and self.instance is not None:
            config = self.instance.config

        if rule_type == LogsExclusionRule.RuleType.PATH_DROP:
            if not isinstance(config, dict):
                raise ValidationError({"config": "path_drop rules require config to be a JSON object."})
            patterns = config.get("patterns")
            if patterns is not None:
                if not isinstance(patterns, list):
                    raise ValidationError({"config": "patterns must be a list of strings."})
                for i, p in enumerate(patterns):
                    if not isinstance(p, str):
                        raise ValidationError({"config": {f"patterns[{i}]": "Each pattern must be a string."}})
            mak = config.get("match_attribute_key")
            if mak is not None and mak != "" and not isinstance(mak, str):
                raise ValidationError({"config": {"match_attribute_key": "Must be a string when provided."}})
            self._validate_filter_group(config.get("filter_group"), reject_vacuous=reject_vacuous)
        if rule_type == LogsExclusionRule.RuleType.RATE_LIMIT:
            if not isinstance(config, dict):
                raise ValidationError({"config": "rate_limit rules require config to be a JSON object."})
            self._validate_filter_group(config.get("filter_group"), reject_vacuous=reject_vacuous)
            self._validate_rate_limit_config(config)
        return attrs

    def _validate_rate_limit_config(self, config: dict[str, Any]) -> None:
        # A rate_limit rule charges either one token per log line (`logs_per_second` +
        # optional `burst_logs`) or one token per byte of `bytes_uncompressed`
        # (`kb_per_second` + optional `burst_kb`). The two shapes are mutually
        # exclusive — picking one or the other is a deliberate operator choice that
        # changes how billing reconciles. Older rules using `logs_per_second` continue
        # to work unchanged.
        has_lines = "logs_per_second" in config
        has_kb = "kb_per_second" in config
        if has_lines and has_kb:
            raise ValidationError(
                {"config": "Set either `logs_per_second` or `kb_per_second` on a rate_limit rule, not both."}
            )
        if not has_lines and not has_kb:
            raise ValidationError({"config": "rate_limit rules require either `logs_per_second` or `kb_per_second`."})
        if has_kb:
            self._validate_rate_limit_kb(config)
        else:
            self._validate_rate_limit_lines(config)

    def _validate_rate_limit_lines(self, config: dict[str, Any]) -> None:
        lps = config.get("logs_per_second")
        if isinstance(lps, bool) or not isinstance(lps, int):
            raise ValidationError({"config": {"logs_per_second": "Must be an integer (logs per second sustained)."}})
        if lps < 1 or lps > 1_000_000:
            raise ValidationError({"config": {"logs_per_second": "Must be between 1 and 1000000 logs/sec inclusive."}})
        burst = config.get("burst_logs", None)
        if burst is not None:
            if isinstance(burst, bool) or not isinstance(burst, int):
                raise ValidationError({"config": {"burst_logs": "Must be an integer when provided."}})
            if burst < lps:
                raise ValidationError({"config": {"burst_logs": "Must be greater than or equal to logs_per_second."}})
            if burst > 10_000_000:
                raise ValidationError({"config": {"burst_logs": "Must be at most 10000000 logs."}})

    def _validate_rate_limit_kb(self, config: dict[str, Any]) -> None:
        kbps = config.get("kb_per_second")
        if isinstance(kbps, bool) or not isinstance(kbps, int):
            raise ValidationError({"config": {"kb_per_second": "Must be an integer (kilobytes per second sustained)."}})
        if kbps < 1 or kbps > 1_000_000:
            raise ValidationError(
                {"config": {"kb_per_second": "Must be between 1 KB/s and 1000000 KB/s (1 GB/s) inclusive."}}
            )
        burst = config.get("burst_kb", None)
        if burst is not None:
            if isinstance(burst, bool) or not isinstance(burst, int):
                raise ValidationError({"config": {"burst_kb": "Must be an integer when provided."}})
            if burst < kbps:
                raise ValidationError({"config": {"burst_kb": "Must be greater than or equal to kb_per_second."}})
            if burst > 10_000_000:
                raise ValidationError({"config": {"burst_kb": "Must be at most 10000000 KB."}})

    def _validate_filter_group(self, filter_group: Any, *, reject_vacuous: bool = False) -> None:
        if filter_group is None:
            return
        # Validate shape against PropertyGroupFilter so malformed payloads
        # (e.g. a list where an object is expected) are rejected at write
        # time rather than letting them flow through to the ingestion worker.
        # Mirrors the pattern used for alert filters in alerts_api.py.
        try:
            PropertyGroupFilter.model_validate(filter_group)
        except PydanticValidationError as e:
            raise ValidationError({"config": {"filter_group": f"Invalid filter_group shape: {e.errors()[0]['msg']}"}})
        # Bound nesting depth — the Node ingestion worker recurses per
        # record over this tree, so an adversarially deep group is a
        # stack-overflow + CPU footgun on every log line. Matches
        # `MAX_FILTER_GROUP_DEPTH` in
        # `nodejs/src/logs/sampling/filter-group-match.ts`.
        if filter_group_depth(filter_group) > MAX_FILTER_GROUP_DEPTH:
            raise ValidationError(
                {"config": {"filter_group": f"filter_group is nested too deeply (max depth {MAX_FILTER_GROUP_DEPTH})."}}
            )
        # Bound total node count — depth alone doesn't bound work per
        # record. A single AND with thousands of sibling leaves is the
        # more realistic abuse vector: it passes the depth check but
        # costs O(leaves) on every log line through the ingestion
        # worker. Matches `MAX_FILTER_GROUP_NODES` in `compile-rules.ts`.
        if filter_group_node_count(filter_group) > MAX_FILTER_GROUP_NODES:
            raise ValidationError(
                {
                    "config": {
                        "filter_group": f"filter_group has too many nodes (max {MAX_FILTER_GROUP_NODES} groups + leaves)."
                    }
                }
            )
        # Well-formed but empty groups pass Pydantic, yet the worker treats them as
        # no-match — the rule would be silently inert (see filter_group_has_empty_group).
        # Ordering constraint: this walk recurses without its own depth short-circuit,
        # so it must run only after the depth check above has bounded the tree.
        if reject_vacuous and filter_group_has_empty_group(filter_group):
            raise ValidationError(
                {
                    "config": {
                        "filter_group": (
                            "Every group in filter_group must contain at least one filter — an empty group "
                            "never matches, so the rule would never apply. For rate_limit rules, omit "
                            "filter_group entirely to cap all matching logs."
                        )
                    }
                }
            )

    def validate_scope_attribute_filters(self, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValidationError("scope_attribute_filters must be a list.")
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValidationError({str(i): "Each filter must be an object."})
            if "key" not in item or "op" not in item:
                raise ValidationError({str(i): "Each filter must include key and op."})
        return value


class LogsSamplingRuleSourceQuerySerializer(serializers.Serializer):
    source: serializers.ChoiceField = serializers.ChoiceField(  # type: ignore[assignment]
        choices=LogsExclusionRule.RecordSource.choices,
        default=LogsExclusionRule.RecordSource.LOGS,
        required=False,
        help_text="Record source whose rules to list or reorder. Defaults to `logs`.",
    )


class LogsSamplingRuleReorderSerializer(serializers.Serializer):
    ordered_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Rule IDs in the desired evaluation order (first element is highest priority / lowest order index).",
    )


class LogsSamplingRuleSimulateResponseSerializer(serializers.Serializer):
    estimated_reduction_pct = serializers.FloatField(
        help_text="Rough percent of log volume this rule would drop (0–100). Stub until ClickHouse-backed estimate ships."
    )
    notes = serializers.CharField(help_text="Human-readable caveats for the estimate.")


# Logs consumers on a release that does not filter rules by `source` would apply span rules to logs.
# Turn this on only after every logs consumer reads `source=logs` rules alone.
LOGS_SPAN_DROP_RULES_FLAG = "logs-span-drop-rules"


class LogsSamplingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsExclusionRule.objects.all().order_by("priority", "created_at")
    serializer_class = LogsSamplingRuleSerializer
    lookup_field = "id"

    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        # A span rule drops trace data, so API keys need authority over tracing as well as logs.
        if self.action in ("list", "retrieve") and self._request_targets_spans(request):
            return ["logs:read", "tracing:read"]
        if self.action in ("create", "update", "partial_update", "destroy", "reorder") and self._request_targets_spans(
            request
        ):
            return ["logs:write", "tracing:write"]
        return None

    def _request_targets_spans(self, request: Request) -> bool:
        if self.action == "create":
            # drf-spectacular calls this with a mock request during schema generation.
            data = getattr(request, "data", None)
            # A non-object body has no source. The serializer rejects it with a 400.
            return isinstance(data, Mapping) and data.get("source") == LogsExclusionRule.RecordSource.SPANS
        if self.action in ("list", "reorder"):
            query_params = getattr(request, "query_params", None) or {}
            return query_params.get("source") == LogsExclusionRule.RecordSource.SPANS
        rule_id = self.kwargs.get(self.lookup_field)
        if not isinstance(rule_id, str):
            # Schema generation has no rule id.
            return False
        try:
            # Not get_object(): its object permission check resolves scopes again and recurses into this hook.
            source = (
                LogsExclusionRule.objects.filter(team_id=self.team_id, id=rule_id)
                .values_list("source", flat=True)
                .first()
            )
        except Exception:
            # Schema generation has no resolved team, and a malformed id has no spans rule to gate.
            return False
        return source == LogsExclusionRule.RecordSource.SPANS

    def _assert_tracing_access_for_span_rules(self, source: str, level: AccessControlLevel = "editor") -> None:
        # A span rule acts on trace data, and AccessControlPermission only checks the view's `logs` scope.
        if source != LogsExclusionRule.RecordSource.SPANS:
            return
        user_access_control = UserAccessControl(user=cast(User, self.request.user), team=self.team)
        if not user_access_control.check_access_level_for_resource("tracing", level):
            verb = "Managing" if level == "editor" else "Viewing"
            raise PermissionDenied(f"{verb} span drop rules requires {level} access to tracing.")

    def _assert_span_rule_writes_enabled(self, source: str) -> None:
        if source != LogsExclusionRule.RecordSource.SPANS:
            return
        user = cast(User, self.request.user)
        if not posthog_feature_flag_enabled(
            LOGS_SPAN_DROP_RULES_FLAG,
            str(user.distinct_id),
            organization_id=self.organization.id,
            team_id=self.team_id,
        ):
            raise PermissionDenied("Span drop rules are not available for this project yet.")

    def _requested_source(self) -> str:
        query = LogsSamplingRuleSourceQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data["source"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team_id=self.team_id)
        if self.action == "list":
            queryset = queryset.filter(source=self._requested_source())
        return queryset

    @extend_schema(parameters=[LogsSamplingRuleSourceQuerySerializer])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._assert_tracing_access_for_span_rules(self._requested_source(), "viewer")
        return super().list(request, *args, **kwargs)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = cast(LogsExclusionRule, self.get_object())
        self._assert_tracing_access_for_span_rules(instance.source, "viewer")
        return Response(self.get_serializer(instance).data)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        self._assert_tracing_access_for_span_rules(s.validated_data["source"])
        self._assert_span_rule_writes_enabled(s.validated_data["source"])
        max_priority = LogsExclusionRule.objects.filter(
            team_id=self.team_id, source=s.validated_data["source"]
        ).aggregate(m=Max("priority"))["m"]
        raw_priority = s.validated_data.pop("priority", None)
        if raw_priority is not None:
            priority = int(raw_priority)
        else:
            priority = 0 if max_priority is None else max_priority + 1
        instance = s.save(
            team_id=self.team_id,
            created_by=user if user.is_authenticated else None,
            priority=priority,
            version=1,
        )
        report_user_action(
            user,
            "logs sampling rule created",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type, "source": instance.source},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        self._assert_tracing_access_for_span_rules(cast(LogsExclusionRule, s.instance).source)
        self._assert_span_rule_writes_enabled(cast(LogsExclusionRule, s.instance).source)
        instance = cast(LogsExclusionRule, s.save())
        LogsExclusionRule.objects.filter(pk=instance.pk, team_id=self.team_id).update(version=F("version") + 1)
        instance.refresh_from_db(fields=["version", "updated_at"])
        report_user_action(
            user,
            "logs sampling rule updated",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type, "source": instance.source},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsExclusionRule) -> None:
        self._assert_tracing_access_for_span_rules(instance.source)
        user = cast(User, self.request.user)
        report_user_action(
            user,
            "logs sampling rule deleted",
            {"rule_id": str(instance.id)},
            team=self.team,
            request=self.request,
        )
        super().perform_destroy(instance)

    @extend_schema(
        request=LogsSamplingRuleReorderSerializer,
        parameters=[LogsSamplingRuleSourceQuerySerializer],
        responses={200: LogsSamplingRuleSerializer(many=True)},
        description=(
            "Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1). "
            "Log and span rules have separate orders; the `source` query parameter picks which one."
        ),
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = LogsSamplingRuleReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data["ordered_ids"]
        source = self._requested_source()
        self._assert_tracing_access_for_span_rules(source)
        self._assert_span_rule_writes_enabled(source)
        team_rule_ids = set(
            LogsExclusionRule.objects.filter(team_id=self.team_id, source=source).values_list("id", flat=True)
        )
        if set(ordered_ids) != team_rule_ids or len(ordered_ids) != len(team_rule_ids):
            raise ValidationError(f"ordered_ids must list every {source} sampling rule for this team exactly once.")
        with transaction.atomic():
            for index, rid in enumerate(ordered_ids):
                LogsExclusionRule.objects.filter(id=rid, team_id=self.team_id).update(
                    priority=index,
                    version=F("version") + 1,
                )
        qs = LogsExclusionRule.objects.filter(team_id=self.team_id, source=source).order_by("priority", "created_at")
        return Response(LogsSamplingRuleSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={200: LogsSamplingRuleSimulateResponseSerializer},
        description="Dry-run estimate for how much volume this rule would remove (placeholder response until CH-backed simulation is wired).",
    )
    @action(detail=True, methods=["post"], url_path="simulate")
    def simulate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _ = self.get_object()
        return Response(
            {
                "estimated_reduction_pct": 0.0,
                "notes": "Simulation not yet implemented against ClickHouse.",
            },
            status=status.HTTP_200_OK,
        )
