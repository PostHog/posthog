from __future__ import annotations

from typing import Any, cast

from django.db import transaction
from django.db.models import F, Max, QuerySet

from drf_spectacular.utils import extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import PropertyGroupFilter

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.logs.backend.models import LogsExclusionRule

# Keep aligned with `MAX_FILTER_GROUP_DEPTH` / `MAX_FILTER_GROUP_NODES` in
# `nodejs/src/logs-ingestion/sampling/filter-group-match.ts` and
# `compile-rules.ts`. Both depth and breadth are bounded so an adversarially
# deep or wide filter_group cannot stack-overflow or CPU-burn the per-record
# evaluator in the Node ingestion worker. The breadth cap is the more
# realistic abuse vector — depth 1 with 10k sibling leaves passes the depth
# check but costs O(leaves) per log record.
MAX_FILTER_GROUP_DEPTH = 16
MAX_FILTER_GROUP_NODES = 256


def _filter_group_depth(node: Any, depth: int = 0) -> int:
    # Short-circuit once we've crossed the cap — we don't need the true depth,
    # just that it exceeds MAX_FILTER_GROUP_DEPTH. Prevents Python RecursionError
    # on adversarial payloads that pass pydantic-core (Rust) validation, which
    # has a more generous recursion limit than ours.
    if depth > MAX_FILTER_GROUP_DEPTH:
        return depth
    if not isinstance(node, dict):
        return depth
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return depth
    max_child = depth
    for child in values:
        d = _filter_group_depth(child, depth + 1)
        if d > max_child:
            max_child = d
    return max_child


def _filter_group_node_count(node: Any) -> int:
    """Total node count across the filter group (groups + leaves). Short-circuits
    once the cap is exceeded so adversarial payloads don't get fully traversed."""
    if not isinstance(node, dict):
        return 1
    total = 1
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return total
    for child in values:
        total += _filter_group_node_count(child)
        if total > MAX_FILTER_GROUP_NODES:
            return total
    return total


def _filter_group_has_empty_group(node: Any) -> bool:
    """True when any group node in the tree has an empty `values` list. The worker's
    matchFilterGroup treats empty groups as no-match (dropping is irreversible, so
    vacuous filters fail closed), which makes a rule carrying one silently inert —
    worst on rate_limit, where `{"type": "AND", "values": []}` reads like "cap
    everything" but caps nothing.

    Recurses without a depth short-circuit of its own — callers must run the
    MAX_FILTER_GROUP_DEPTH check first so the tree is already bounded."""
    if not isinstance(node, dict):
        return False
    values = node.get("values")
    if not isinstance(values, list) or node.get("type") not in ("AND", "OR"):
        return False
    if len(values) == 0:
        return True
    return any(_filter_group_has_empty_group(child) for child in values)


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
            "version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "version", "created_by", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        rule_type = attrs.get("rule_type")
        if rule_type is None and self.instance is not None:
            rule_type = self.instance.rule_type
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
        # `nodejs/src/logs-ingestion/sampling/filter-group-match.ts`.
        if _filter_group_depth(filter_group) > MAX_FILTER_GROUP_DEPTH:
            raise ValidationError(
                {"config": {"filter_group": f"filter_group is nested too deeply (max depth {MAX_FILTER_GROUP_DEPTH})."}}
            )
        # Bound total node count — depth alone doesn't bound work per
        # record. A single AND with thousands of sibling leaves is the
        # more realistic abuse vector: it passes the depth check but
        # costs O(leaves) on every log line through the ingestion
        # worker. Matches `MAX_FILTER_GROUP_NODES` in `compile-rules.ts`.
        if _filter_group_node_count(filter_group) > MAX_FILTER_GROUP_NODES:
            raise ValidationError(
                {
                    "config": {
                        "filter_group": f"filter_group has too many nodes (max {MAX_FILTER_GROUP_NODES} groups + leaves)."
                    }
                }
            )
        # Well-formed but empty groups pass Pydantic, yet the worker treats them as
        # no-match — the rule would be silently inert (see _filter_group_has_empty_group).
        # Ordering constraint: this walk recurses without its own depth short-circuit,
        # so it must run only after the depth check above has bounded the tree.
        if reject_vacuous and _filter_group_has_empty_group(filter_group):
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


class LogsSamplingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsExclusionRule.objects.all().order_by("priority", "created_at")
    serializer_class = LogsSamplingRuleSerializer
    lookup_field = "id"
    posthog_feature_flag = "logs-settings-drop-rules"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        max_priority = LogsExclusionRule.objects.filter(team_id=self.team_id).aggregate(m=Max("priority"))["m"] or -1
        raw_priority = s.validated_data.pop("priority", None)
        priority = max_priority + 1 if raw_priority is None else int(raw_priority)
        instance = s.save(
            team_id=self.team_id,
            created_by=user if user.is_authenticated else None,
            priority=priority,
            version=1,
        )
        report_user_action(
            user,
            "logs sampling rule created",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type},
            team=self.team,
            request=self.request,
        )

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        s = cast(LogsSamplingRuleSerializer, serializer)
        user = cast(User, self.request.user)
        instance = cast(LogsExclusionRule, s.save())
        LogsExclusionRule.objects.filter(pk=instance.pk, team_id=self.team_id).update(version=F("version") + 1)
        instance.refresh_from_db(fields=["version", "updated_at"])
        report_user_action(
            user,
            "logs sampling rule updated",
            {"rule_id": str(instance.id), "rule_type": instance.rule_type},
            team=self.team,
            request=self.request,
        )

    def perform_destroy(self, instance: LogsExclusionRule) -> None:
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
        responses={200: LogsSamplingRuleSerializer(many=True)},
        description="Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).",
    )
    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = LogsSamplingRuleReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ordered_ids = serializer.validated_data["ordered_ids"]
        team_rule_ids = set(LogsExclusionRule.objects.filter(team_id=self.team_id).values_list("id", flat=True))
        if set(ordered_ids) != team_rule_ids or len(ordered_ids) != len(team_rule_ids):
            raise ValidationError("ordered_ids must list every sampling rule for this team exactly once.")
        with transaction.atomic():
            for index, rid in enumerate(ordered_ids):
                LogsExclusionRule.objects.filter(id=rid, team_id=self.team_id).update(
                    priority=index,
                    version=F("version") + 1,
                )
        qs = self.safely_get_queryset(LogsExclusionRule.objects.all()).order_by("priority", "created_at")
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
