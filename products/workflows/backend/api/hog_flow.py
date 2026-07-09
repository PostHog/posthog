import re
import json
import uuid as uuid_mod
import dataclasses
from datetime import timedelta
from typing import Any, Optional, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
import posthoganalytics
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.schema import ProductKey

from posthog.api.app_metrics2 import AppMetricsMixin, fetch_app_metric_totals_by_source
from posthog.api.documentation import _FallbackSerializer
from posthog.api.hog_invocation_rerun import HogInvocationRerunRequestSerializer, HogInvocationRerunResponseSerializer
from posthog.api.hog_invocation_results import (
    HogInvocationResultDetailSerializer,
    HogInvocationResultSerializer,
    HogInvocationResultsRequestSerializer,
    fetch_hog_invocation_result,
    fetch_hog_invocation_results,
    tag_invocation_results_query,
)
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import log_activity_from_viewset
from posthog.auth import InternalAPIAuthentication
from posthog.cdp.validation import (
    HogFunctionFiltersSerializer,
    InputsSchemaItemSerializer,
    InputsSerializer,
    generate_template_bytecode,
)
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.event_usage import EventSource, get_event_source
from posthog.models import Team
from posthog.models.filters import Filter
from posthog.plugins.plugin_server_api import (
    create_hog_flow_invocation_test,
    create_hog_flow_scheduled_invocation,
    rerun_hog_invocations,
)
from posthog.utils import relative_date_parse_with_delta_mapping

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import get_all_cohort_dependencies
from products.feature_flags.backend.user_blast_radius import (
    PERSON_BATCH_SIZE,
    get_user_blast_radius,
    get_user_blast_radius_persons,
)
from products.notifications.backend.facade.api import publish_resource_edited
from products.workflows.backend.api.graph_operations import apply_graph_operations
from products.workflows.backend.api.graph_validation import validate_graph
from products.workflows.backend.api.hog_flow_batch_job import HogFlowBatchJobSerializer
from products.workflows.backend.api.message_assets import (
    MessageAssetContentRequestSerializer,
    MessageAssetSerializer,
    MessageAssetsRequestSerializer,
    fetch_message_asset_html,
    fetch_message_assets,
)
from products.workflows.backend.models.hog_flow.hog_flow import (
    BILLABLE_ACTION_TYPES,
    PERSON_DEPENDENT_ACTION_TYPES,
    HogFlow,
)
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import SCHEDULED_TRIGGER_TYPES, HogFlowSchedule
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule

logger = structlog.get_logger(__name__)

# Delay durations are strings like "30m", "2h", "1.5d". Must match the regex in the Node.js executor
# (nodejs/src/cdp/services/hogflows/actions/delay.ts) that throws at runtime on mismatch.
DELAY_DURATION_REGEX = re.compile(r"^\d*\.?\d+[dhm]$")

# Active workflows are read-only via MCP for now: edits can break runs already scheduled or in flight,
# and there's no revision history to roll back. Shared by the plain update path and the graph endpoint.
MCP_ACTIVE_EDIT_REJECTION = (
    "Editing an active workflow isn't supported via MCP yet — changes can break runs already "
    "scheduled or in flight, and there's no revision history to roll back. If you need different "
    "behavior, create a new draft workflow."
)

# A batch audience is a one-time snapshot of everyone matching the conditions at run time, so each
# condition must resolve to a concrete set of persons/groups. Feature flag evaluation is dynamic
# (rollout %, distinct_id hashing, super-conditions, holdouts) and has no such fixed membership, so a
# flag condition can't be turned into an audience query — it falls through to a NotImplementedError
# deeper in HogQL property compilation. Reject it up front with a clear 400 instead.
BATCH_FLAG_CONDITION_REJECTION = (
    "Feature flags can't be used as a batch audience condition. Use person properties or cohorts instead."
)


def reject_flag_conditions_in_audience(team: Team, filters: dict) -> None:
    property_groups = Filter(data=filters or {}, team=team).property_groups
    if any(prop.type == "flag" for prop in property_groups.flat):
        raise exceptions.ValidationError(BATCH_FLAG_CONDITION_REJECTION)


def _validation_error_message(error: exceptions.ValidationError) -> str:
    detail = error.detail
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return str(detail)


def _first_error_string(detail: Any) -> Optional[str]:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        for item in detail:
            if message := _first_error_string(item):
                return message
    if isinstance(detail, dict):
        for value in detail.values():
            if message := _first_error_string(value):
                return message
    return None


def _describe_action_errors(errors: list[Any], actions: list[dict]) -> str:
    # The many=True error list mirrors the actions list, with {} entries for valid actions. Raising it
    # as-is gets flattened by the exception handler to that first empty dict, so the client sees "{}".
    # Name each offending step instead so the error points at what to fix.
    parts = []
    for action_data, error in zip(actions, errors):
        if not error:
            continue
        message = _first_error_string(error) or "has an invalid configuration"
        name = action_data.get("name") if isinstance(action_data, dict) else None
        parts.append(f"step '{name or 'unnamed'}': {message}")
    return f"Can't enable this workflow. Fix {'; '.join(parts) or 'the invalid steps'} and try again."


def _should_validate_strictly(context: dict, is_draft: Optional[bool]) -> bool:
    # Non-draft saves always validate fully. Drafts stay lenient for the web UI builder (which saves
    # incomplete graphs mid-edit) and for internal re-saves (e.g. the refresh management command), which
    # only re-persist already-accepted data. Programmatic authoring clients (MCP, posthog-code, raw API)
    # validate drafts fully too, so an unsupported config is rejected at create rather than silently stored
    # and surfacing only at enable. The viewset sets event_source; absent it (internal/no request), drafts
    # stay lenient.
    if not is_draft:
        return True
    source = context.get("event_source")
    return source is not None and source != EventSource.WEB


def _event_config_has_event_or_action(event_config: dict) -> bool:
    # An "events to wait for" / conversion entry that targets neither events nor actions compiles to
    # always-true bytecode and would fire on every incoming event. Action-based entries (events empty,
    # actions set) are real and kept. Shared by the wait_until_condition and conversion strips so the
    # rule lives in one place (mirrors hasEventOrActionTarget in the matcher consumer).
    filters = event_config.get("filters") or {}
    return bool(filters.get("events") or filters.get("actions"))


class BlastRadiusRequestSerializer(serializers.Serializer):
    filters = serializers.DictField(help_text="Property filters to apply")
    group_type_index = serializers.IntegerField(
        required=False, allow_null=True, help_text="Group type index for group-based targeting"
    )


class BlastRadiusSerializer(serializers.Serializer):
    affected = serializers.IntegerField(help_text="Number of users matching the filters")
    total = serializers.IntegerField(help_text="Total number of users")
    limit = serializers.IntegerField(help_text="Maximum allowed audience size for batch triggers for this team.")


class WorkflowGlobalStatsRequestSerializer(serializers.Serializer):
    after = serializers.CharField(
        required=False,
        default="-7d",
        help_text="Start of the window, matched on metric time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d.",
    )
    before = serializers.CharField(
        required=False,
        help_text="End of the window. Same format as 'after'. Defaults to now.",
    )


class WorkflowStatsRowSerializer(serializers.Serializer):
    workflow_id = serializers.CharField(help_text="The workflow these counts are for.")
    succeeded = serializers.IntegerField(help_text="Successful invocations in the window.")
    failed = serializers.IntegerField(help_text="Failed invocations in the window.")


class HogFlowConfigFunctionInputsSerializer(serializers.Serializer):
    inputs_schema = serializers.ListField(child=InputsSchemaItemSerializer(), required=False)
    inputs = InputsSerializer(required=False)

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)


class HogFlowEdgeSerializer(serializers.Serializer):
    to = serializers.CharField(help_text="Target action id.")
    type = serializers.ChoiceField(
        choices=["continue", "branch"],
        help_text=(
            "continue: fall-through (sequential or the no-match path of conditional_branch). "
            "branch: requires 'index' matching config.conditions[index]."
        ),
    )
    index = serializers.IntegerField(
        required=False,
        help_text=(
            "Required for type='branch'. conditional_branch: index into config.conditions[index]. "
            "wait_until_condition: use index:0 — it advances via the index:0 branch edge when it "
            "resolves (a condition match or an events entry firing)."
        ),
    )

    def get_fields(self):
        # 'from' is a Python keyword so it can't be a class attribute. Inject it here
        # so DRF / drf-spectacular still see a typed field on the wire.
        fields = super().get_fields()
        fields["from"] = serializers.CharField(help_text="Source action id.")
        return fields


# Schema-only typing for the polymorphic action config. The MCP tool schema is generated from this
# (via zod), the MCP server parses tool input with that zod schema, and handlers receive the PARSED
# result — a matched zod object branch strips keys it doesn't declare. The free-form branch is
# deliberately FIRST so it wins union parsing for every config shape: the typed
# wait_until_condition branch exists purely as shape guidance for agents and never strips or
# rejects anything.
_HOG_FLOW_WAIT_UNTIL_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "filters": {
            "anyOf": [{"$ref": "#/components/schemas/HogFunctionFilters"}, {"type": "null"}],
            "description": (
                "Event/action filters; the workflow wakes when a matching event fires. Must target "
                "at least one event or action (entries targeting neither are dropped)."
            ),
        },
        "name": {"type": "string", "description": "Optional display name."},
    },
}

HOG_FLOW_ACTION_CONFIG_SCHEMA = {
    "anyOf": [
        {
            "type": "object",
            "additionalProperties": True,
            "description": (
                "Config for every action type except wait_until_condition — see the field "
                "description for per-type shapes."
            ),
        },
        {
            "type": "object",
            "description": (
                "Config for type='wait_until_condition'. Provide 'condition' and/or 'events' — an "
                "events-only wait (no condition) is valid."
            ),
            "required": ["max_wait_duration"],
            "properties": {
                "condition": {
                    "type": "object",
                    "description": (
                        "Property-based wait condition; continues when the person matches. A condition "
                        "with no property filters is ignored — the wait then relies on 'events' and the "
                        "max_wait_duration timeout."
                    ),
                    "properties": {
                        "filters": {
                            "anyOf": [{"$ref": "#/components/schemas/HogFunctionFilters"}, {"type": "null"}],
                            "description": "Property conditions, e.g. {properties: [{key, value, operator, type}]}.",
                        },
                        "name": {"type": "string", "description": "Optional display name."},
                    },
                },
                "events": {
                    "type": "array",
                    "items": _HOG_FLOW_WAIT_UNTIL_EVENT_SCHEMA,
                    "description": (
                        "Events to wait for: continues when ANY entry fires (OR'd with 'condition'). "
                        "Each entry: {filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}."
                    ),
                },
                "max_wait_duration": {
                    "type": "string",
                    "description": "'<number><unit>' with unit m|h|d, e.g. '30m' (same rules as delay).",
                },
            },
        },
    ],
}


@extend_schema_field(HOG_FLOW_ACTION_CONFIG_SCHEMA)
class HogFlowActionConfigField(serializers.JSONField):
    # Runtime stays a lenient JSONField: per-type validation lives in HogFlowActionSerializer.validate.
    pass


class HogFlowActionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Unique node ID within the workflow.")
    name = serializers.CharField(max_length=400, help_text="Display name.")
    description = serializers.CharField(allow_blank=True, default="", help_text="Optional description.")
    on_error = serializers.ChoiceField(
        choices=["continue", "abort"],
        required=False,
        allow_null=True,
        help_text="On failure: continue (skip the action and proceed) or abort (stop the run).",
    )
    created_at = serializers.IntegerField(required=False, help_text="Created at (epoch ms). Frontend-managed.")
    updated_at = serializers.IntegerField(required=False, help_text="Updated at (epoch ms). Frontend-managed.")
    filters = HogFunctionFiltersSerializer(
        required=False, default=None, allow_null=True, help_text="Property filters gating this action."
    )
    type = serializers.CharField(
        max_length=100,
        help_text=(
            "trigger | function | function_email | function_sms | delay | "
            "conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit."
        ),
    )
    config = HogFlowActionConfigField(
        help_text=(
            "Type-specific config keyed by action type. "
            "trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. "
            "filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], "
            "actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, "
            "type: event|person|group}. "
            "function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable "
            "hog templating ({person.x}, {event.x}); flat strings won't interpolate. "
            "Dictionary input values are template strings too — write booleans/numbers as single-expression "
            "templates ('{true}', '{42}'), which evaluate to the typed value. "
            "delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; "
            "seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. "
            "Max 30d. "
            "conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. "
            "wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, "
            "type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as "
            "delay). Continues when condition.filters match OR any events entry fires; each events entry "
            "must target at least one event or action. On resolution (a condition match or any events "
            "entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout "
            "falls through the 'continue' edge. "
            "exit: {reason}."
        ),
    )
    output_variable = serializers.JSONField(
        required=False, allow_null=True, help_text="Output variable definition for downstream actions."
    )

    def to_internal_value(self, data):
        # Weirdly nested serializers don't get this set...
        self.initial_data = data
        return super().to_internal_value(data)

    def _reject_behavioral_cohorts_in_audience(self, properties) -> None:
        # Batch/schedule audiences resolve offline by precalculated membership and can't evaluate event
        # behavior the way it's intended; the UI hides behavioral cohorts from the audience picker. Mirror
        # that for API/MCP callers. Static cohorts are exempt regardless of how they were built — their
        # membership is frozen and precalculated — matching the audience-picker exemption in
        # _build_cohort_dependency_graph in products/cohorts/backend/models/dependencies.py.
        if not isinstance(properties, list):
            return
        cohort_ids = [
            p["value"]
            for p in properties
            if isinstance(p, dict) and p.get("type") == "cohort" and p.get("value") is not None
        ]
        if not cohort_ids:
            return
        project_id = self.context["get_team"]().project_id
        for cohort_id in cohort_ids:
            try:
                cohort = Cohort.objects.get(pk=cohort_id, team__project_id=project_id, deleted=False)
            except (Cohort.DoesNotExist, ValueError, TypeError):
                continue  # missing/invalid cohort surfaces during audience resolution, not here
            if cohort.is_static:
                continue
            for dep in [cohort, *get_all_cohort_dependencies(cohort)]:
                if dep.is_static:
                    continue
                if any(p.type == "behavioral" for p in dep.properties.flat):
                    raise serializers.ValidationError(
                        {
                            "filters": (
                                f"Cohort '{dep.name}' targets event behavior, which batch/schedule audiences "
                                "can't evaluate. Use a static or property-based cohort, or an event trigger "
                                "for behavioral targeting."
                            )
                        }
                    )

    def validate(self, data):
        is_draft = self.context.get("is_draft")
        # Drafts from the web builder stay lenient (incomplete graphs save fine); programmatic callers
        # (MCP/API) get full validation even on drafts so a broken or unsupported config fails at create
        # time rather than being silently stored and surfacing only at enable.
        strict = _should_validate_strictly(self.context, is_draft)

        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "manual", "tracking_pixel"]:
                trigger_is_function = True
            elif data.get("config", {}).get("type") == "event":
                filters = data.get("config", {}).get("filters", {})
                # Move filter_test_accounts into filters for bytecode compilation
                if data.get("config", {}).get("filter_test_accounts") is not None:
                    filters["filter_test_accounts"] = data["config"].pop("filter_test_accounts")
                if filters:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    if not strict:
                        if serializer.is_valid():
                            data["config"]["filters"] = serializer.validated_data
                    else:
                        serializer.is_valid(raise_exception=True)
                        data["config"]["filters"] = serializer.validated_data
            elif data.get("config", {}).get("type") == "batch":
                filters = data.get("config", {}).get("filters", {})
                if strict:
                    if not filters:
                        raise serializers.ValidationError({"filters": "Filters are required for batch triggers."})
                    if not isinstance(filters, dict):
                        raise serializers.ValidationError({"filters": "Filters must be a dictionary."})
                    properties = filters.get("properties", None)
                    if properties is not None and not isinstance(properties, list):
                        raise serializers.ValidationError({"filters": {"properties": "Properties must be an array."}})
                if strict and isinstance(filters, dict):
                    # The audience targets who a person is (properties / cohort membership), not what they did.
                    # Event/action filters are silently dropped by the person-based blast radius (resolving to
                    # "everyone"), so reject them outright — same rejection as a behavioral cohort below.
                    if filters.get("events") or filters.get("actions"):
                        raise serializers.ValidationError(
                            {
                                "filters": (
                                    "Batch trigger audiences can't filter on event behavior. Use person "
                                    "properties or a static/property-based cohort, or an event trigger for "
                                    "behavioral targeting."
                                )
                            }
                        )
                    self._reject_behavioral_cohorts_in_audience(filters.get("properties"))
            elif data.get("config", {}).get("type") == "schedule":
                # The schedule definition lives on a separate HogFlowSchedule row, but a schedule trigger
                # resolves the same offline audience as batch — guard its cohort refs the same way.
                if strict:
                    filters = data.get("config", {}).get("filters", {})
                    if isinstance(filters, dict):
                        self._reject_behavioral_cohorts_in_audience(filters.get("properties"))
            elif data.get("config", {}).get("type") == "data-warehouse-table":
                # Warehouse-triggered workflows are person-less ("row-scoped"): one workflow run
                # per synced row, filtering only against the row payload. The dot-notated table_name
                # must match the format produced by the Python CDPProducer so producer gating and
                # trigger config use identical strings.
                config = data.get("config", {})
                table_name = config.get("table_name")
                if not is_draft and (not table_name or not isinstance(table_name, str)):
                    raise serializers.ValidationError(
                        {"table_name": "A data warehouse table name is required for this trigger."}
                    )

                # Compile the row-property filters to bytecode so the executor can evaluate them.
                # We force the data-warehouse-table source so only row properties are considered.
                filters = config.get("filters", {}) or {}
                if not isinstance(filters, dict):
                    raise serializers.ValidationError({"filters": "Filters must be a dictionary."})
                filters["source"] = "data-warehouse-table"
                serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                if is_draft:
                    if serializer.is_valid():
                        data["config"]["filters"] = serializer.validated_data
                else:
                    serializer.is_valid(raise_exception=True)
                    data["config"]["filters"] = serializer.validated_data
            else:
                if strict:
                    raise serializers.ValidationError({"config": "Invalid trigger type"})

        if "function" in data.get("type", "") or trigger_is_function:
            template_id = data.get("config", {}).get("template_id", "")
            template = HogFunctionTemplate.get_template(template_id)
            if not template:
                if strict:
                    raise serializers.ValidationError({"template_id": "Template not found"})
            else:
                input_schema = template.inputs_schema
                inputs = data.get("config", {}).get("inputs", {})

                function_config_serializer = HogFlowConfigFunctionInputsSerializer(
                    data={
                        "inputs_schema": input_schema,
                        "inputs": inputs,
                    },
                    context={
                        "function_type": template.type,
                        "is_dwh_source": self.context.get("is_dwh_source", False),
                    },
                )

                if not strict:
                    if function_config_serializer.is_valid():
                        data["config"]["inputs"] = function_config_serializer.validated_data["inputs"]
                else:
                    function_config_serializer.is_valid(raise_exception=True)
                    data["config"]["inputs"] = function_config_serializer.validated_data["inputs"]

        conditions = data.get("config", {}).get("conditions", [])

        single_condition = data.get("config", {}).get("condition", None)
        if conditions and single_condition:
            if strict:
                raise serializers.ValidationError({"config": "Cannot specify both 'conditions' and 'condition' fields"})
        if single_condition:
            conditions = [single_condition]

        is_conditional_branch = data.get("type") == "conditional_branch"
        if conditions:
            for condition in conditions:
                filters = condition.get("filters")
                if filters is None:
                    # A conditional_branch condition without a 'filters' wrapper (e.g. a bare {properties: [...]})
                    # has nothing to compile, so it silently becomes always-false and the branch never matches.
                    # Reject it for strict callers with a fixable message; web-builder drafts stay lenient
                    # (incomplete mid-edit). wait_until_condition waits on `events` instead, so a null condition
                    # filter is legitimate there — only enforce this for conditional_branch.
                    if strict and is_conditional_branch:
                        raise serializers.ValidationError(
                            {
                                "config": (
                                    "Each conditional_branch condition must wrap its filters in a 'filters' key, e.g. "
                                    "{conditions: [{filters: {properties: [...]}}]} (same shape as a trigger's "
                                    "filters). A condition without 'filters' compiles to always-false and never matches."
                                )
                            }
                        )
                    continue
                if "events" in filters:
                    if strict:
                        raise serializers.ValidationError("Event filters are not allowed in conditionals")
                else:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    if not strict:
                        if serializer.is_valid():
                            condition["filters"] = serializer.validated_data
                    else:
                        serializer.is_valid(raise_exception=True)
                        condition["filters"] = serializer.validated_data

        if data.get("type") == "wait_until_condition":
            config = data.get("config")
            if isinstance(config, dict) and config.get("condition") is None:
                # The visual editor seeds every wait node with a condition object ({filters: null}) and
                # StepWaitUntilCondition assumes it's present. MCP/API callers can author an events-only
                # wait with no condition; default it so the stored shape matches what the editor renders.
                # An empty condition is ignored at runtime (isEvaluableCondition), so this is behaviour-neutral.
                config["condition"] = {"filters": None}
            wait_events = data.get("config", {}).get("events") or []
            # Drop "events to wait for" entries that target neither events nor actions. An empty
            # event filter compiles to always-true bytecode, which would wake the job on every
            # incoming event and bypass the property condition. The UI can leave such an entry
            # behind when the last event is removed; "nothing targeted" must mean "nothing wakes
            # this", not "everything". Action-based entries (events empty, actions set) are kept.
            wait_events = [ec for ec in wait_events if _event_config_has_event_or_action(ec)]
            data["config"]["events"] = wait_events
            for event_config in wait_events:
                filters = event_config.get("filters")
                if filters is not None:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    if not strict:
                        if serializer.is_valid():
                            event_config["filters"] = serializer.validated_data
                    else:
                        serializer.is_valid(raise_exception=True)
                        event_config["filters"] = serializer.validated_data

        if data.get("type") == "delay":
            delay_duration = data.get("config", {}).get("delay_duration")
            if not isinstance(delay_duration, str) or not DELAY_DURATION_REGEX.match(delay_duration):
                if strict:
                    raise serializers.ValidationError(
                        {
                            "config": (
                                "delay_duration must be a string matching ^\\d*\\.?\\d+[dhm]$ "
                                "(e.g. '30m', '2h', '1d'). ISO-8601 formats are not supported. "
                                "For seconds, use a fraction of a minute."
                            )
                        }
                    )

        return data


class HogFlowVariableSerializer(serializers.ListSerializer):
    child = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="Variable: {key, type: string|number|boolean, default}.",
    )

    def validate(self, attrs):
        # Make sure the keys are unique
        keys = [item.get("key") for item in attrs]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Variable keys must be unique")

        # Make sure entire variables definition is less than 5KB
        # This is just a check for massive keys / default values, we also have a check for dynamically
        # set variables during execution
        total_size = sum(len(json.dumps(item)) for item in attrs)
        if total_size > 5120:
            raise serializers.ValidationError("Total size of variables definition must be less than 5KB")

        return super().validate(attrs)


class HogFlowMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(
        required=False,
        min_value=60,
        max_value=60 * 60 * 24 * 365 * 3,
        allow_null=True,
        help_text="Seconds (60 to ~94M / 3y) to suppress repeat firings of the same hash.",
    )
    threshold = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.",
    )
    hash = serializers.CharField(
        required=True,
        help_text="HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl.",
    )
    bytecode = serializers.JSONField(required=False, allow_null=True, help_text="Auto-compiled from hash. Do not set.")

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


@extend_schema_field(HogFunctionFiltersSerializer)
class HogFlowConversionEventFiltersField(serializers.JSONField):
    # Schema-typed as HogFunctionFilters for codegen, but runtime-lenient: drafts may hold invalid
    # filters, and HogFlowSerializer.validate compiles/validates these with draft leniency.
    pass


class HogFlowConversionEventSerializer(serializers.Serializer):
    filters = HogFlowConversionEventFiltersField(
        help_text=(
            "Event/action filters for this conversion event, same shape as trigger filters: "
            "{events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], "
            "properties?: [<cond>]}. bytecode is compiled server-side."
        )
    )


class HogFlowConversionSerializer(serializers.Serializer):
    filters = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text=(
            "Property-based conversion conditions, as an ARRAY of property filters: "
            "[{key, value, operator, type: event|person|group}, ...]. Event-based goals do NOT go here — "
            "put them in 'events'. Empty array = any event within the window converts."
        ),
    )
    events = serializers.ListField(
        child=HogFlowConversionEventSerializer(),
        required=False,
        help_text="Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}].",
    )
    window_minutes = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Conversion window in minutes after a person enters the workflow. null = no explicit window.",
    )
    # Not DRF read_only: drf-spectacular puts readOnly fields in the component's `required` list
    # (shared by request and response schemas), which would make generated write schemas demand a
    # server-computed field. Instead it's optional here and stripped in to_internal_value, so a
    # client-supplied value still never reaches validated_data.
    bytecode = serializers.JSONField(
        required=False, allow_null=True, help_text="Compiled server-side from 'filters'. Do not set; ignored if sent."
    )

    def to_internal_value(self, data):
        # bytecode is server-computed; never trust a client-supplied value (the matcher executes it).
        if isinstance(data, dict) and "bytecode" in data:
            data = {k: v for k, v in data.items() if k != "bytecode"}
        # Legacy shape guard (mirrors the one-time backfill in migration 0009): some clients sent an
        # event-based goal as an object in 'filters' (e.g. {"events": [...], "source": "events"}).
        # That belongs in 'events' — relocate it before field validation so the old shape is still
        # accepted and compiled (filters only takes an array of property conditions) instead of 400ing.
        if isinstance(data, dict) and isinstance(data.get("filters"), dict) and data["filters"].get("events"):
            data = {**data, "events": [*(data.get("events") or []), {"filters": data["filters"]}], "filters": []}
        return super().to_internal_value(data)

    def to_representation(self, value):
        # Pass stored JSON through untouched — rows written before the 'events' slot existed may hold
        # legacy shapes (object in 'filters') that field-level coercion would mangle on read.
        return value


class HogFlowScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = HogFlowSchedule
        fields = [
            "id",
            "rrule",
            "starts_at",
            "timezone",
            "variables",
            "status",
            "next_run_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "next_run_at", "created_at", "updated_at"]
        extra_kwargs = {
            "rrule": {
                "help_text": (
                    "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once "
                    "per hour."
                )
            },
            "starts_at": {"help_text": "ISO 8601 datetime the schedule starts from."},
            "timezone": {"help_text": "IANA timezone for interpreting the RRULE (default 'UTC')."},
            "variables": {"help_text": "Variable value overrides merged with the workflow defaults on each run."},
            "status": {"help_text": "active, paused, or completed (set once the RRULE's COUNT/UNTIL is exhausted)."},
            "next_run_at": {"help_text": "Next scheduled fire time, computed by the scheduler."},
        }

    def validate(self, data):
        # For partial updates, fall back to instance values
        instance = self.instance
        rrule_str = data.get("rrule", getattr(instance, "rrule", None))
        starts_at = data.get("starts_at", getattr(instance, "starts_at", None))
        timezone_str = data.get("timezone", getattr(instance, "timezone", "UTC"))

        if not rrule_str:
            raise serializers.ValidationError({"rrule": "RRULE string is required."})

        if "rrule" in data:
            try:
                validate_rrule(rrule_str)
            except (ValueError, TypeError) as e:
                logger.warning("Invalid RRULE encountered during validation", rrule=rrule_str, error=str(e))
                raise serializers.ValidationError({"rrule": "Invalid RRULE."})

        if not starts_at:
            raise serializers.ValidationError({"starts_at": "Start date is required."})

        try:
            sample = compute_next_occurrences(rrule_str, starts_at, timezone_str=timezone_str, count=2)
        except (KeyError, ValueError):
            raise serializers.ValidationError({"timezone": "Invalid or unknown timezone."})

        if len(sample) == 0:
            raise serializers.ValidationError({"rrule": "Schedule produces no future occurrences."})
        if len(sample) == 2 and (sample[1] - sample[0]) < timedelta(hours=1):
            raise serializers.ValidationError({"rrule": "Schedules must run at most once per hour."})

        return data

    def update(self, instance, validated_data):
        if any(field in validated_data for field in ("rrule", "starts_at", "timezone")):
            # Force the scheduler to recalculate the next occurrence on its next poll
            instance.next_run_at = None
            if instance.status != HogFlowSchedule.Status.PAUSED:
                instance.status = HogFlowSchedule.Status.ACTIVE
        return super().update(instance, validated_data)


class HogFlowMinimalSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "updated_at",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
            "variables",
            "billable_action_types",
        ]
        read_only_fields = fields


class HogFlowSerializer(HogFlowMinimalSerializer):
    name = serializers.CharField(
        max_length=400, required=False, allow_null=True, allow_blank=True, help_text="Workflow name."
    )
    description = serializers.CharField(required=False, allow_blank=True, default="", help_text="Optional description.")
    status = serializers.ChoiceField(
        choices=HogFlow.State.choices,
        required=False,
        help_text="draft (no execution), active (live), archived (disabled).",
    )
    trigger_masking = HogFlowMaskingSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Optional dedup/throttle on an already-matched trigger: {hash: <HogQL template>, "
            "ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then "
            "suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire "
            "once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an "
            "already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; "
            "omit to disable."
        ),
    )
    conversion = HogFlowConversionSerializer(
        required=False,
        allow_null=True,
        help_text=(
            "Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; "
            "events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. "
            "Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. "
            "bytecode compiled server-side."
        ),
    )
    exit_condition = serializers.ChoiceField(
        choices=HogFlow.ExitCondition.choices,
        required=False,
        help_text=(
            "exit_only_at_end: only at exit node (default). "
            "exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). "
            "exit_on_trigger_not_matched: also when trigger filter stops matching. "
            "exit_on_trigger_not_matched_or_conversion: both (needs 'conversion')."
        ),
    )
    edges = serializers.ListField(
        child=HogFlowEdgeSerializer(),
        required=False,
        help_text=(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through "
            "(sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches "
            "config.conditions[index] on conditional_branch / wait_until_condition. Every non-exit action "
            "needs a reachable next action ('No next action found' otherwise)."
        ),
    )
    actions = serializers.ListField(
        child=HogFlowActionSerializer(),
        required=True,
        help_text="Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too.",
    )
    variables = HogFlowVariableSerializer(required=False, help_text="Workflow vars (key, type, default). Total <5KB.")
    schedules = HogFlowScheduleSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). "
            "A batch/schedule workflow only fires when it's active AND has an active schedule. Empty for "
            "non-scheduled workflows."
        ),
    )

    def to_internal_value(self, data):
        status = data.get("status")
        if status is None and self.instance:
            status = self.instance.status
        if status != "active":
            self.context["is_draft"] = True

        # Warehouse-table triggers are row-scoped: step inputs may use the `{record.x}` alias for the
        # synced row. Flag it before child action validation so function-input compilation rewrites it.
        actions = data.get("actions")
        if actions is None and self.instance:
            actions = self.instance.actions
        self.context["is_dwh_source"] = any(
            isinstance(action, dict)
            and action.get("type") == "trigger"
            and (action.get("config") or {}).get("type") == "data-warehouse-table"
            for action in (actions or [])
        )
        return super().to_internal_value(data)

    class Meta:
        model = HogFlow
        fields = [
            "id",
            "name",
            "description",
            "version",
            "status",
            "created_at",
            "created_by",
            "updated_at",
            "trigger",
            "trigger_masking",
            "conversion",
            "exit_condition",
            "edges",
            "actions",
            "abort_action",
            "variables",
            "billable_action_types",
            "schedules",
        ]
        read_only_fields = [
            "id",
            "version",
            "created_at",
            "created_by",
            "updated_at",
            "trigger",  # Derived from the trigger action in the actions array
            "abort_action",
            "billable_action_types",  # Computed field, not user-editable
            "schedules",  # Managed via the schedules sub-resource, surfaced read-only here
        ]

    def validate(self, data):
        instance = cast(Optional[HogFlow], self.instance)
        is_draft = self.context.get("is_draft")
        actions = data.get("actions", instance.actions if instance else [])

        # When activating a draft, re-validate actions from the instance with full (non-draft) checks
        status = data.get("status", instance.status if instance else "draft")
        if status == "active" and instance and instance.status != "active" and "actions" not in data:
            action_serializer = HogFlowActionSerializer(data=instance.actions, many=True, context=self.context)
            if not action_serializer.is_valid():
                # many=True yields a list of per-action errors despite the ReturnDict annotation
                action_errors = cast(list[Any], action_serializer.errors)
                raise serializers.ValidationError({"actions": _describe_action_errors(action_errors, instance.actions)})
            actions = action_serializer.validated_data

        # The trigger is derived from the actions. We can trust the action level validation and pull it out
        trigger_actions = [action for action in actions if action.get("type") == "trigger"]

        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})

        data["trigger"] = trigger_actions[0]["config"]

        # Warehouse-triggered workflows are person-less ("row-scoped"): one run per synced row with no
        # associated person. Person-dependent steps and person-aware exit conditions would silently
        # assume person data, so we block them here — the serializer is the source of truth, so the API,
        # MCP, and frontend can't bypass it. We force exit_only_at_end since the other exit conditions
        # re-evaluate trigger/conversion filters that may reference person properties.
        if data["trigger"].get("type") == "data-warehouse-table":
            data["exit_condition"] = HogFlow.ExitCondition.ONLY_AT_END
            if not is_draft:
                offending_types = sorted(
                    {
                        action.get("type", "")
                        for action in actions
                        if action.get("type") in PERSON_DEPENDENT_ACTION_TYPES
                    }
                )
                if offending_types:
                    raise serializers.ValidationError(
                        {
                            "actions": (
                                "These step types rely on person data, which is unavailable for data warehouse "
                                f"table triggers: {', '.join(offending_types)}"
                            )
                        }
                    )

        # Compute and store unique billable action types for efficient quota checking
        # Only track billable actions defined in BILLABLE_ACTION_TYPES
        billable_action_types = sorted(
            {action.get("type", "") for action in actions if action.get("type") in BILLABLE_ACTION_TYPES}
        )
        data["billable_action_types"] = billable_action_types

        # Web-builder drafts stay lenient; programmatic (MCP/API) callers get full validation even on
        # drafts — same posture as HogFlowActionSerializer, so a conversion filter that can't compile
        # (e.g. a cohort reference) fails at create rather than being silently stored.
        strict = _should_validate_strictly(self.context, self.context.get("is_draft"))

        # Graph wiring (dangling edges, branch-index range, abort_action, reachability) is enforced only on
        # the surgical /graph endpoint (which sets enforce_graph_structure and builds a clean graph by
        # construction). On every other save it's advisory: existing workflows carry pre-existing structural
        # corruption (stale branch edges from removed conditions, legacy null endpoints), and a normal edit —
        # even an unrelated one — must not be blocked by graph state the caller didn't introduce. We log it
        # for telemetry instead. The web builder's incomplete drafts (not strict) skip the check entirely.
        enforce_graph = self.context.get("enforce_graph_structure", False)
        if strict or enforce_graph:
            edges = data.get("edges", instance.edges if instance else [])
            try:
                warnings = validate_graph(actions, edges, abort_action=instance.abort_action if instance else None)
            except serializers.ValidationError as exc:
                if enforce_graph:
                    raise
                graph_errors = exc.detail.get("graph", []) if isinstance(exc.detail, dict) else [exc.detail]
                for error in graph_errors:
                    logger.warning(
                        "hog_flow_graph_structural_error",
                        error=str(error),
                        hog_flow_id=str(instance.id) if instance else None,
                    )
                warnings = []
            for warning in warnings:
                logger.info(
                    "hog_flow_graph_warning", warning=warning, hog_flow_id=str(instance.id) if instance else None
                )

        conversion = data.get("conversion")
        if conversion is not None:
            filters = conversion.get("filters")
            if filters:
                serializer = HogFunctionFiltersSerializer(data={"properties": filters}, context=self.context)
                if not strict:
                    if serializer.is_valid():
                        compiled_filters = serializer.validated_data
                        data["conversion"]["filters"] = compiled_filters.get("properties", [])
                        data["conversion"]["bytecode"] = compiled_filters.get("bytecode", [])
                else:
                    serializer.is_valid(raise_exception=True)
                    compiled_filters = serializer.validated_data
                    data["conversion"]["filters"] = compiled_filters.get("properties", [])
                    data["conversion"]["bytecode"] = compiled_filters.get("bytecode", [])
            if "bytecode" not in data["conversion"]:
                data["conversion"]["bytecode"] = []

            # Drop conversion "events" entries that target neither events nor actions, for the same
            # always-true reason as the wait_until_condition guard above: an empty entry would mark
            # every incoming event as a conversion. Action-based entries (events empty, actions set)
            # are kept.
            conversion_events = [ec for ec in (conversion.get("events") or []) if _event_config_has_event_or_action(ec)]
            data["conversion"]["events"] = conversion_events
            for event_config in conversion_events:
                event_filters = event_config.get("filters")
                if event_filters is not None:
                    event_serializer = HogFunctionFiltersSerializer(data=event_filters, context=self.context)
                    if not strict:
                        if event_serializer.is_valid():
                            event_config["filters"] = event_serializer.validated_data
                        elif isinstance(event_filters, dict):
                            # Draft with invalid filters: never keep client-supplied bytecode.
                            # Conversion isn't revalidated on a status-only activation, so stored
                            # bytecode would activate unvalidated and the matcher would execute it.
                            # Strip it so the filter fails closed (no bytecode = never matches).
                            event_filters.pop("bytecode", None)
                    else:
                        event_serializer.is_valid(raise_exception=True)
                        event_config["filters"] = event_serializer.validated_data

        return data

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlow:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


GRAPH_OPERATION_TYPES = [
    "update_action",
    "add_action",
    "remove_action",
    "add_edge",
    "remove_edge",
    "replace_action_edges",
]

# Per-op required fields, validated in HogFlowGraphOperationSerializer.validate so a malformed op is
# rejected before any are applied (the whole batch is atomic).
_GRAPH_OPERATION_REQUIRED_FIELDS: dict[str, list[str]] = {
    "update_action": ["id", "patch"],
    "add_action": ["action"],
    "remove_action": ["id"],
    "add_edge": ["edge"],
    "remove_edge": ["edge"],
    "replace_action_edges": ["id", "edges"],
}


class HogFlowGraphOperationSerializer(serializers.Serializer):
    op = serializers.ChoiceField(
        choices=GRAPH_OPERATION_TYPES,
        help_text=(
            "Graph edit. update_action {id, patch}: deep-merge patch into the action's fields (a null leaf "
            "deletes that key) — the surgical path for tweaking one config value. add_action {action}: append "
            "a full action node. remove_action {id}: delete a node and reconnect its incoming edges to its "
            "first outgoer. add_edge {edge} / remove_edge {edge}: add or delete one edge. "
            "replace_action_edges {id, edges}: replace this action's outgoing edges with the given set "
            "(use when adding/removing branch conditions); incoming edges are left intact."
        ),
    )
    id = serializers.CharField(
        required=False, help_text="Action id. Required for update_action, remove_action, replace_action_edges."
    )
    patch = serializers.JSONField(
        required=False,
        help_text=(
            "update_action only. Partial action fields, deep-merged into the existing action; a null leaf "
            "deletes that key. e.g. {config: {inputs: {subject: {value: 'Hi'}}}} changes only that input."
        ),
    )
    action = serializers.JSONField(
        required=False,
        help_text="add_action only. A full action node {id, name, type, config, ...}; same shape as in actions.",
    )
    edge = HogFlowEdgeSerializer(
        required=False, help_text="add_edge / remove_edge only. The edge {from, to, type, index?}."
    )
    edges = serializers.ListField(
        child=HogFlowEdgeSerializer(),
        required=False,
        help_text="replace_action_edges only. The complete set of the action's outgoing edges; incoming edges are preserved.",
    )

    def validate(self, data):
        op = data["op"]
        missing = [field for field in _GRAPH_OPERATION_REQUIRED_FIELDS[op] if data.get(field) is None]
        if missing:
            raise serializers.ValidationError(f"op '{op}' requires: {', '.join(missing)}")
        if op == "update_action" and not isinstance(data.get("patch"), dict):
            raise serializers.ValidationError("update_action 'patch' must be an object")
        if op == "add_action" and not isinstance(data.get("action"), dict):
            raise serializers.ValidationError("add_action 'action' must be an object")
        return data


class HogFlowGraphUpdateSerializer(serializers.Serializer):
    operations = serializers.ListField(
        child=HogFlowGraphOperationSerializer(),
        allow_empty=False,
        help_text=(
            "Ordered graph edits applied atomically to a draft workflow: the stored graph is read, the ops "
            "are applied in order, the result is fully validated, and it's saved only if valid — otherwise the "
            "workflow is unchanged. Reference nodes/edges by id so you never resend the whole graph. The full "
            "updated workflow is returned."
        ),
    )


class HogFlowInvocationSerializer(serializers.Serializer):
    configuration = HogFlowSerializer(
        write_only=True, required=False, help_text="Optional override; omit to use saved definition."
    )
    globals = serializers.DictField(
        write_only=True, required=False, help_text="Test trigger payload, typically {event, person, groups}."
    )
    mock_async_functions = serializers.BooleanField(
        default=True,
        write_only=True,
        help_text="True (default) mocks HTTP/email/SMS. False fires real side effects.",
    )
    current_action_id = serializers.CharField(
        write_only=True,
        required=False,
        help_text=(
            "Start execution from this action ID instead of the trigger. Each test run executes a single node and "
            "returns the next action id."
        ),
    )


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFlowFilterSet(FilterSet):
    class Meta:
        model = HogFlow
        fields = ["id", "created_by", "created_at", "updated_at", "status"]


class HogFlowPagination(LimitOffsetPagination):
    # Bumped from the global default of 100 so the workflows list page loads all flows in one
    # request — the frontend list/search runs client-side over a single page (no pagination UI yet).
    default_limit = 200
    max_limit = 500


class StaleWorkflowUpdateError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This workflow was updated elsewhere since you loaded it. Reload to get the latest version before saving."
    )
    default_code = "stale_update"


@extend_schema(extensions={"x-product": "workflows"})
class HogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    scope_object = "hog_flow"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "logs",
        "metrics",
        "metrics_totals",
        "metrics_global",
        "user_blast_radius",
        "assets",
        "asset_content",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "invocations",
        "schedule_detail",
        "bulk_delete",
        "rerun",
        "graph",
    ]
    queryset = HogFlow.objects.all()
    pagination_class = HogFlowPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = HogFlowFilterSet
    log_source = "hog_flow"
    app_source = "hog_flow"
    function_kind = "hog_flow"

    def dangerously_get_required_scopes(self, request, view) -> Optional[list[str]]:
        # Dual-method custom actions need method-aware scopes — the action-name-based read/write
        # lists above can't distinguish GET (read) from POST (write) on the same action. Without
        # this, these actions declare no scope and reject all personal-API-key (MCP) access.
        if self.action in ("batch_jobs", "schedules"):
            return ["hog_flow:read"] if request.method in ("GET", "HEAD", "OPTIONS") else ["hog_flow:write"]
        # Sizing an audience runs a person/group count over caller-supplied filters — that's person-data
        # access, so require person:read on top of workflow read. Without it a hog_flow:read-only token
        # could use this as a person-existence oracle (e.g. "does email X exist?"). The web builder uses
        # session auth, so live sizing while editing is unaffected.
        if self.action == "user_blast_radius":
            return ["hog_flow:read", "person:read"]
        # Invocation inspection returns distinct_id / person_id and the raw triggering payload
        # (invocation_globals: event/person/groups), so it's person-data access — require person:read
        # on top of workflow read, same as user_blast_radius. A hog_flow:read-only token must not be
        # able to enumerate who a workflow ran for.
        if self.action in ("invocation_results", "invocation_result"):
            return ["hog_flow:read", "person:read"]
        # Assets expose recipient/distinct_id/person_id and the message bytes — require
        # person:read so a hog_flow:read-only token can't enumerate who got emailed.
        if self.action in ("assets", "asset_content"):
            return ["hog_flow:read", "person:read"]
        # A test invocation resolves the event's $groups into real group properties server-side, so a
        # hog_flow:write-only token could branch on group_0.properties and read the returned logs/variables
        # as a group-property oracle. Require group:read on top. The web builder uses session auth, so
        # running tests while editing is unaffected.
        if self.action == "invocations":
            return ["hog_flow:write", "group:read"]
        # Rerun re-executes stored invocations — it replays up to 30 days of
        # persisted event/person/group data through the current (possibly
        # reconfigured) workflow. A `hog_flow:write`-only token could use that to
        # route historical data it can't otherwise read to a destination it
        # controls, so gate rerun on person:read + group:read on top of write —
        # the same data-read scopes invocation inspection requires. (`hog_flow:read`
        # would be a no-op since :write already satisfies it.)
        if self.action == "rerun":
            return ["hog_flow:write", "person:read", "group:read"]
        return None

    def get_serializer_class(self) -> type[BaseSerializer]:
        return HogFlowMinimalSerializer if self.action == "list" else HogFlowSerializer

    def get_serializer_context(self) -> dict:
        # Drives draft strictness in the serializers: web-builder drafts stay lenient, programmatic
        # (MCP/API) drafts validate fully. Set here so the decision is tied to the request entry point,
        # not inferred deep in the serializer (which would also catch internal re-saves like the refresh
        # command). See _should_validate_strictly.
        context = super().get_serializer_context()
        context["event_source"] = get_event_source(self.request)
        return context

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        if self.action == "list":
            queryset = queryset.order_by("-updated_at")

        if self.request.GET.get("trigger"):
            try:
                trigger = json.loads(self.request.GET["trigger"])

                if trigger:
                    queryset = queryset.filter(trigger__contains=trigger)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"trigger": f"Invalid trigger"})

        return queryset

    def safely_get_object(self, queryset):
        # TODO(team-workflows): Somehow implement version lookups
        return super().safely_get_object(queryset)

    @staticmethod
    def _is_mcp_request(request: Request) -> bool:
        return request.headers.get("x-posthog-client") == "mcp"

    @extend_schema(
        request=HogInvocationRerunRequestSerializer,
        responses={200: HogInvocationRerunResponseSerializer, 400: HogInvocationRerunResponseSerializer},
    )
    @action(detail=True, methods=["POST"])
    def rerun(self, request: Request, *args, **kwargs) -> Response:
        """
        Rerun past invocations of this hog flow from their stored payloads.

        Same shape and semantics as the hog function rerun endpoint —
        proxies through to the CDP worker, which reads matching rows from
        ClickHouse, rehydrates from `invocation_globals`, and re-enqueues
        onto cyclotron with `is_retry=1`.

        Because rerun replays historical event/person/group data, it requires
        `person:read` and `group:read` on top of `hog_flow:write`.
        """
        hog_flow = self.get_object()

        serializer = HogInvocationRerunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # `serializer.data` runs `to_representation`, which converts the
        # `DateTimeField`s on `filter.window_start` / `filter.window_end` to
        # ISO-8601 strings — `requests.post(json=...)` can't serialize raw
        # `datetime` objects, so passing `validated_data` would 500 every
        # filter-mode rerun before the request even left Django.
        res = rerun_hog_invocations(
            team_id=self.team_id,
            function_kind="hog_flow",
            function_id=str(hog_flow.id),
            payload=serializer.data,
        )

        if res.status_code != 200:
            return Response(
                {"queued_count": 0, "skipped_count": 0, "detail": res.text},
                status=res.status_code,
            )

        return Response(res.json())

    def _emit_resource_edited(self, instance: HogFlow) -> None:
        # Realtime "edited elsewhere" signal so an open builder (or another tab) can refresh instead of
        # clobbering edits made via a different channel (UI/MCP/API). Fires for every channel; the
        # frontend dedupes its own echo by comparing updated_at. Transient — no inbox notification.
        publish_resource_edited(
            team=self.team,
            resource_type="HogFlow",
            resource_id=str(instance.id),
            updated_at=instance.updated_at.isoformat(),
            actor_user_id=getattr(self.request.user, "id", None),
            ac_resource_type=self.scope_object,
        )

    def perform_create(self, serializer):
        if self._is_mcp_request(self.request) and serializer.validated_data.get("status") == HogFlow.State.ACTIVE:
            raise exceptions.ValidationError(
                "You can't one-shot active workflows via MCP. "
                "Create as draft, test with workflows-test-run, then enable with workflows-enable."
            )

        serializer.save()
        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, detail_type="standard")
        self._emit_resource_edited(serializer.instance)

        try:
            # Count edges and actions
            edges_count = len(serializer.instance.edges) if serializer.instance.edges else 0
            actions_count = len(serializer.instance.actions) if serializer.instance.actions else 0

            posthoganalytics.capture(
                distinct_id=str(serializer.context["request"].user.distinct_id),
                event="hog_flow_created",
                properties={
                    "workflow_id": str(serializer.instance.id),
                    "workflow_name": serializer.instance.name,
                    # "trigger_type": trigger_type,
                    "edges_count": edges_count,
                    "actions_count": actions_count,
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization.id),
                },
            )
        except Exception as e:
            logger.warning("Failed to capture hog_flow_created event", error=str(e))

    def perform_update(self, serializer):
        # Guardrails for MCP/LLM callers (gated on x-posthog-client: mcp; the frontend and raw API are
        # unaffected). We check the raw request payload, not serializer.validated_data — HogFlowSerializer.validate
        # injects derived fields like 'trigger' and 'billable_action_types' which would otherwise make every
        # status-only PATCH look like a mixed edit.
        if self._is_mcp_request(self.request):
            keys = set(self.request.data.keys())
            has_status = "status" in keys
            has_non_status = bool(keys - {"status"})

            # Active workflows are read-only via MCP for now. Status-only PATCHes (lifecycle tools) pass through.
            if serializer.instance.status == HogFlow.State.ACTIVE and has_non_status:
                raise exceptions.ValidationError(MCP_ACTIVE_EDIT_REJECTION)

            # Status transitions must go through the dedicated lifecycle tools (status-only PATCHes); a mixed
            # status + field payload is rejected so MCP can't sneak a transition through a field update.
            if has_status and has_non_status:
                raise exceptions.ValidationError(
                    "Status changes via MCP must use workflows-enable / workflows-disable / "
                    "workflows-archive — they can't be combined with other field updates."
                )

        # TODO(team-workflows): Atomically increment version, insert new object instead of default update behavior
        instance_id = serializer.instance.id

        # Optimistic concurrency: a client may send the `updated_at` it last loaded as `base_updated_at`.
        # If the stored row is strictly newer, another channel (a second UI tab, MCP, or the API) wrote in
        # between, so we reject with 409 rather than silently clobbering it. Strictly-newer (not equality)
        # avoids false positives from timestamp round-tripping — equal means the client is already current.
        # Callers that omit `base_updated_at` keep the previous last-writer-wins behavior.
        base_updated_at_raw = self.request.data.get("base_updated_at")
        base_updated_at = parse_datetime(base_updated_at_raw) if base_updated_at_raw else None
        # A timezone-less timestamp parses naive; comparing it to the tz-aware stored updated_at would
        # raise TypeError (500). Assume UTC so callers can send a bare ISO string.
        if base_updated_at is not None and timezone.is_naive(base_updated_at):
            base_updated_at = timezone.make_aware(base_updated_at)

        with transaction.atomic():
            try:
                # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance; locked for the staleness check + save)
                before_update = HogFlow.objects.select_for_update().get(pk=instance_id)
            except HogFlow.DoesNotExist:
                before_update = None

            if base_updated_at and before_update and before_update.updated_at > base_updated_at:
                raise StaleWorkflowUpdateError()

            serializer.save()

        log_activity_from_viewset(self, serializer.instance, name=serializer.instance.name, previous=before_update)
        self._emit_resource_edited(serializer.instance)

        # PostHog capture for hog_flow activated (draft -> active)
        if (
            before_update
            and before_update.status == HogFlow.State.DRAFT
            and serializer.instance.status == HogFlow.State.ACTIVE
        ):
            try:
                # Count edges and actions
                edges_count = len(serializer.instance.edges) if serializer.instance.edges else 0
                actions_count = len(serializer.instance.actions) if serializer.instance.actions else 0

                posthoganalytics.capture(
                    distinct_id=str(serializer.context["request"].user.distinct_id),
                    event="hog_flow_activated",
                    properties={
                        "workflow_id": str(serializer.instance.id),
                        "workflow_name": serializer.instance.name,
                        "edges_count": edges_count,
                        "actions_count": actions_count,
                        "team_id": str(self.team_id),
                        "organization_id": str(self.organization.id),
                    },
                )
            except Exception as e:
                logger.warning("Failed to capture hog_flow_activated event", error=str(e))

    @extend_schema(request=HogFlowGraphUpdateSerializer, responses={200: HogFlowSerializer})
    @action(detail=True, methods=["PATCH"])
    def graph(self, request: Request, *args, **kwargs):
        # Surgical graph editing: apply a small, id-addressed op list to the stored graph instead of
        # re-transmitting every action and edge. Reads, applies, validates, and saves atomically so a
        # rejected batch leaves the workflow untouched (and concurrent edits can't interleave).
        op_serializer = HogFlowGraphUpdateSerializer(data=request.data)
        op_serializer.is_valid(raise_exception=True)
        operations = op_serializer.validated_data["operations"]

        # Authorize + team-scope via the normal lookup, then re-read FOR UPDATE inside the transaction.
        instance = self.get_object()

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = HogFlow.objects.select_for_update().get(pk=instance.pk)

            if self._is_mcp_request(request) and locked.status == HogFlow.State.ACTIVE:
                raise exceptions.ValidationError(MCP_ACTIVE_EDIT_REJECTION)

            new_actions, new_edges = apply_graph_operations(
                list(locked.actions or []), list(locked.edges or []), operations
            )

            serializer = self.get_serializer(locked, data={"actions": new_actions, "edges": new_edges}, partial=True)
            # The surgical endpoint is the one path where structural corruption would be newly introduced,
            # so it enforces graph validation as a hard error (unlike the lenient full-save path).
            serializer.context["enforce_graph_structure"] = True
            serializer.is_valid(raise_exception=True)

            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFlow.objects.get(pk=instance.pk)
            # save() mutates and returns `locked` in place, so it's the saved HogFlow from here on.
            serializer.save()

        log_activity_from_viewset(self, locked, name=locked.name, previous=before_update)
        self._emit_resource_edited(locked)

        return Response(self.get_serializer(locked).data)

    @extend_schema(request=HogFlowInvocationSerializer, responses={200: _FallbackSerializer})
    @action(detail=True, methods=["POST"])
    def invocations(self, request: Request, *args, **kwargs):
        try:
            hog_flow = self.get_object()
        except Exception:
            hog_flow = None

        serializer = HogFlowInvocationSerializer(
            data=request.data, context={**self.get_serializer_context(), "instance": hog_flow}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        res = create_hog_flow_invocation_test(
            team_id=self.team_id,
            hog_flow_id=str(hog_flow.id) if hog_flow else "new",
            payload=serializer.validated_data,
        )

        if res.status_code != 200:
            return Response({"status": "error", "message": res.json()["error"]}, status=res.status_code)

        return Response(res.json())

    @extend_schema(request=BlastRadiusRequestSerializer, responses=BlastRadiusSerializer)
    @action(methods=["POST"], detail=False)
    def user_blast_radius(self, request: Request, **kwargs):
        if "filters" not in request.data:
            raise exceptions.ValidationError("Missing filters for which to get blast radius")

        filters = request.data.get("filters", {})
        group_type_index = request.data.get("group_type_index", None)

        reject_flag_conditions_in_audience(self.team, filters)

        result = get_user_blast_radius(self.team, filters, group_type_index)

        return Response(
            BlastRadiusSerializer(
                {
                    "affected": result.affected,
                    "total": result.total,
                    "limit": get_hogflow_batch_trigger_limit(self.team_id),
                }
            ).data
        )

    @extend_schema(
        operation_id="hog_flows_invocation_results_retrieve",
        parameters=[HogInvocationResultsRequestSerializer],
        responses=HogInvocationResultSerializer(many=True),
    )
    @action(detail=True, methods=["GET"], pagination_class=None, filter_backends=[])
    def invocation_results(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        tag_invocation_results_query(self.function_kind)

        param_serializer = HogInvocationResultsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        after_date = None
        before_date = None
        if params.get("after"):
            after_date, _, _ = relative_date_parse_with_delta_mapping(params["after"], self.team.timezone_info)
        if params.get("before"):
            before_date, _, _ = relative_date_parse_with_delta_mapping(params["before"], self.team.timezone_info)

        data = fetch_hog_invocation_results(
            team_id=self.team_id,
            function_kind=self.function_kind,
            function_id=str(obj.id),
            limit=params["limit"],
            status=params["status"].split(",") if params.get("status") else None,
            distinct_id=params.get("distinct_id"),
            after=after_date,
            before=before_date,
        )
        return Response(HogInvocationResultSerializer(data, many=True).data)

    @extend_schema(
        operation_id="hog_flows_invocation_result_retrieve",
        parameters=[OpenApiParameter("invocation_id", str, OpenApiParameter.PATH)],
        responses=HogInvocationResultDetailSerializer,
    )
    @action(
        detail=True,
        methods=["GET"],
        url_path="invocation_results/(?P<invocation_id>[^/.]+)",
        filter_backends=[],
    )
    def invocation_result(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        tag_invocation_results_query(self.function_kind)

        data = fetch_hog_invocation_result(
            team_id=self.team_id,
            function_kind=self.function_kind,
            function_id=str(obj.id),
            invocation_id=kwargs["invocation_id"],
        )
        if data is None:
            raise exceptions.NotFound("Invocation not found.")
        return Response(HogInvocationResultDetailSerializer(data).data)

    @extend_schema(
        operation_id="hog_flows_assets_retrieve",
        parameters=[MessageAssetsRequestSerializer],
        responses=MessageAssetSerializer(many=True),
    )
    @action(detail=True, methods=["GET"], pagination_class=None, filter_backends=[])
    def assets(self, request: Request, *args, **kwargs):
        obj = self.get_object()
        tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)

        param_serializer = MessageAssetsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        after_date, _, _ = relative_date_parse_with_delta_mapping(params["after"], self.team.timezone_info)
        before_date = None
        if params.get("before"):
            before_date, _, _ = relative_date_parse_with_delta_mapping(params["before"], self.team.timezone_info)

        data = fetch_message_assets(
            team_id=self.team_id,
            function_kind=self.function_kind,
            function_id=str(obj.id),
            limit=params["limit"],
            offset=params["offset"],
            parent_run_id=params.get("parent_run_id"),
            action_id=params.get("action_id"),
            invocation_id=params.get("invocation_id"),
            distinct_id=params.get("distinct_id"),
            search=params.get("search"),
            after=after_date,
            before=before_date,
        )
        enriched = [dataclasses.replace(row, function_name=obj.name or "") for row in data]
        return Response(MessageAssetSerializer(enriched, many=True).data)

    @extend_schema(
        operation_id="hog_flows_asset_content_retrieve",
        parameters=[MessageAssetContentRequestSerializer],
        responses={(200, "text/html"): OpenApiTypes.STR},
    )
    @action(detail=True, methods=["GET"], url_path="assets/content", pagination_class=None, filter_backends=[])
    def asset_content(self, request: Request, *args, **kwargs):
        # Ownership-check the HogFlow first so other teams' assets can't be probed.
        obj = self.get_object()

        param_serializer = MessageAssetContentRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)

        html = fetch_message_asset_html(
            team_id=self.team_id,
            function_kind=self.function_kind,
            function_id=str(obj.id),
            invocation_id=params["invocation_id"],
            action_id=params.get("action_id", ""),
        )
        if html is None:
            raise exceptions.NotFound("Asset content is no longer available.")
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
        # Enforce sandboxing at the response layer so direct navigation to the asset URL
        # (bypassing the iframe with `sandbox=""` on the frontend) still can't execute
        # scripts or make same-origin requests as the viewer. `sandbox` (no allow-list)
        # is the most restrictive CSP mode; the other directives are defense-in-depth.
        response["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src https: data:; style-src 'unsafe-inline'"
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        return response

    @extend_schema(
        operation_id="hog_flows_metrics_global_retrieve",
        parameters=[WorkflowGlobalStatsRequestSerializer],
        responses=WorkflowStatsRowSerializer(many=True),
    )
    @action(detail=False, methods=["GET"], pagination_class=None, filter_backends=[], url_path="metrics/global")
    def metrics_global(self, request: Request, *args, **kwargs):
        param_serializer = WorkflowGlobalStatsRequestSerializer(data=request.query_params)
        param_serializer.is_valid(raise_exception=True)
        params = param_serializer.validated_data

        tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)

        after_date, _, _ = relative_date_parse_with_delta_mapping(params["after"], self.team.timezone_info)
        before_date = None
        if params.get("before"):
            before_date, _, _ = relative_date_parse_with_delta_mapping(params["before"], self.team.timezone_info)

        totals = fetch_app_metric_totals_by_source(
            team_id=self.team_id,
            app_source=self.app_source,
            after=after_date,
            before=before_date,
        )
        # The ClickHouse query is only team-scoped, so intersect with the workflows the caller can
        # actually see. Keeps the aggregate consistent with workflows-list/-get access control (hog
        # flows aren't an access-control resource today, so this is a no-op now but won't silently
        # become a bypass if they become one), and drops orphaned metrics for since-deleted workflows.
        accessible_ids = {
            str(pk)
            for pk in self.user_access_control.filter_queryset_by_access_level(self.get_queryset()).values_list(
                "id", flat=True
            )
        }
        rows: list[dict[str, object]] = [
            {
                "workflow_id": workflow_id,
                "succeeded": counts.get("succeeded", 0),
                "failed": counts.get("failed", 0),
            }
            for workflow_id, counts in totals.items()
            if workflow_id in accessible_ids
        ]
        # Surface the most-failing workflows first — this is the at-a-glance triage view.
        rows.sort(key=lambda row: cast(int, row["failed"]), reverse=True)
        return Response(WorkflowStatsRowSerializer(rows, many=True).data)

    @action(methods=["POST"], detail=False)
    def bulk_delete(self, request: Request, **kwargs):
        ids = request.data.get("ids", [])
        if not ids or not isinstance(ids, list):
            return Response({"error": "A non-empty list of 'ids' is required"}, status=400)

        try:
            validated_ids = [uuid_mod.UUID(str(id)) for id in ids]
        except ValueError:
            return Response({"error": "One or more IDs are not valid UUIDs"}, status=400)

        queryset = self.get_queryset().filter(id__in=validated_ids, status="archived")
        deleted_count, _ = queryset.delete()

        return Response({"deleted": deleted_count})

    @extend_schema(methods=["GET"], responses=HogFlowBatchJobSerializer(many=True))
    @extend_schema(methods=["POST"], request=HogFlowBatchJobSerializer, responses=HogFlowBatchJobSerializer)
    # GET returns a bare list (no pagination) and ignores the viewset's HogFlow filterset; disable both so the
    # generated schema matches the actual response shape.
    @action(detail=True, methods=["GET", "POST"], pagination_class=None, filter_backends=[])
    def batch_jobs(self, request: Request, *args, **kwargs):
        try:
            hog_flow = self.get_object()
        except Exception:
            raise exceptions.NotFound(f"Workflow {kwargs.get('pk')} not found")

        if request.method == "POST":
            # A batch run sends real messages, so only fire for an enabled workflow. The scheduler applies the
            # same gate (see internal_process_due_schedules) and the UI disables the manual trigger for non-active
            # workflows; enforce it here too so API/MCP callers can't start a run the consumer would only drop.
            if hog_flow.status != HogFlow.State.ACTIVE:
                raise exceptions.ValidationError("Workflow must be active to run a batch. Enable it first.")

            serializer = HogFlowBatchJobSerializer(
                data={**request.data, "hog_flow": hog_flow.id}, context={**self.get_serializer_context()}
            )
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)

            batch_job = serializer.save()
            return Response(HogFlowBatchJobSerializer(batch_job).data)
        else:
            batch_jobs = HogFlowBatchJob.objects.filter(hog_flow=hog_flow, team=self.team).order_by("-created_at")
            serializer = HogFlowBatchJobSerializer(batch_jobs, many=True)
            return Response(serializer.data)

    @extend_schema(methods=["GET"], responses=HogFlowScheduleSerializer(many=True))
    @extend_schema(methods=["POST"], request=HogFlowScheduleSerializer, responses=HogFlowScheduleSerializer)
    # GET returns a bare list (no pagination) and ignores the viewset's HogFlow filterset; disable both so the
    # generated schema matches the actual response shape.
    @action(detail=True, methods=["GET", "POST"], pagination_class=None, filter_backends=[])
    def schedules(self, request: Request, *args, **kwargs):
        hog_flow = self.get_object()

        if request.method == "POST":
            serializer = HogFlowScheduleSerializer(data=request.data, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            serializer.save(team=self.team, hog_flow=hog_flow)
            return Response(serializer.data, status=201)

        schedules = HogFlowSchedule.objects.filter(hog_flow=hog_flow, team=self.team).order_by("-created_at")
        serializer = HogFlowScheduleSerializer(schedules, many=True)
        return Response(serializer.data)

    @extend_schema(
        methods=["PATCH"],
        request=HogFlowScheduleSerializer,
        responses=HogFlowScheduleSerializer,
        parameters=[OpenApiParameter("schedule_id", str, OpenApiParameter.PATH)],
    )
    @extend_schema(
        methods=["DELETE"],
        responses={204: None},
        parameters=[OpenApiParameter("schedule_id", str, OpenApiParameter.PATH)],
    )
    @action(detail=True, methods=["PATCH", "DELETE"], url_path="schedules/(?P<schedule_id>[^/.]+)")
    def schedule_detail(self, request: Request, schedule_id=None, *args, **kwargs):
        hog_flow = self.get_object()
        try:
            schedule = HogFlowSchedule.objects.get(id=schedule_id, hog_flow=hog_flow, team=self.team)
        except HogFlowSchedule.DoesNotExist:
            raise exceptions.NotFound("Schedule not found")

        if request.method == "DELETE":
            schedule.delete()
            return Response(status=204)

        serializer = HogFlowScheduleSerializer(
            schedule, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class InternalHogFlowViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, AppMetricsMixin, viewsets.ModelViewSet):
    """
    Internal endpoints for Node.js services to query user blast radius.
    These endpoints require Bearer token authentication via INTERNAL_API_SECRET and are not exposed to Contour ingress
    """

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    authentication_classes = [InternalAPIAuthentication]

    # Internal service-to-service endpoints (authenticated with INTERNAL_API_SECRET)
    def internal_user_blast_radius(self, request: Request, team_id: str) -> Response:
        """
        Internal endpoint for Node.js services to query user blast radius.
        Requires Bearer token authentication via INTERNAL_API_SECRET.
        """

        if request.method != "POST":
            return Response({"error": "Method not allowed"}, status=405)

        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        if "filters" not in request.data:
            return Response({"error": "Missing filters for which to get blast radius"}, status=400)

        filters = request.data.get("filters", {})
        group_type_index = request.data.get("group_type_index", None)

        try:
            reject_flag_conditions_in_audience(team, filters)
            result = get_user_blast_radius(team, filters, group_type_index)
            return Response(
                BlastRadiusSerializer(
                    {
                        "affected": result.affected,
                        "total": result.total,
                        "limit": get_hogflow_batch_trigger_limit(team.id),
                    }
                ).data
            )
        except exceptions.ValidationError as e:
            return Response({"error": _validation_error_message(e)}, status=400)
        except Exception as e:
            logger.exception("Error in internal_user_blast_radius", error=str(e), team_id=team_id)
            return Response({"error": "Internal server error"}, status=500)

    def internal_user_blast_radius_persons(self, request: Request, team_id: str) -> Response:
        """
        Internal endpoint for Node.js services to query user blast radius persons with pagination.
        Requires Bearer token authentication via INTERNAL_API_SECRET.
        """
        if request.method != "POST":
            return Response({"error": "Method not allowed"}, status=405)

        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        if "filters" not in request.data:
            return Response({"error": "Missing filters for which to get blast radius"}, status=400)

        filters = request.data.get("filters", {}) or {}
        group_type_index = request.data.get("group_type_index", None)
        cursor = request.data.get("cursor", None)

        try:
            reject_flag_conditions_in_audience(team, filters)
            users_affected = get_user_blast_radius_persons(team, filters, group_type_index, cursor)
            return Response(
                {
                    "users_affected": users_affected,
                    "cursor": users_affected[-1] if users_affected else None,
                    "has_more": len(users_affected) == PERSON_BATCH_SIZE,
                }
            )
        except exceptions.ValidationError as e:
            return Response({"error": _validation_error_message(e)}, status=400)
        except Exception as e:
            logger.exception("Error in internal_user_blast_radius_persons", error=str(e), team_id=team_id)
            return Response({"error": "Internal server error"}, status=500)

    def internal_process_due_schedules(self, request: Request, **kwargs) -> Response:
        """
        Internal endpoint called by the scheduler service to process due schedules.
        Handles both executing due schedules and initializing next_run_at for new ones.
        """
        from django.db import transaction  # noqa: PLC0415

        from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob  # noqa: PLC0415
        from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule  # noqa: PLC0415
        from products.workflows.backend.utils.rrule_utils import compute_next_occurrences  # noqa: PLC0415

        def advance_next_run(schedule, after=None):
            """Compute and set next_run_at, or mark completed if RRULE is exhausted."""
            occurrences = compute_next_occurrences(
                rrule_string=schedule.rrule,
                starts_at=schedule.starts_at,
                timezone_str=schedule.timezone,
                after=after,
                count=1,
            )
            if occurrences:
                schedule.next_run_at = occurrences[0]
                schedule.save(update_fields=["next_run_at", "updated_at"])
            else:
                schedule.status = HogFlowSchedule.Status.COMPLETED
                schedule.next_run_at = None
                schedule.save(update_fields=["status", "next_run_at", "updated_at"])
            return occurrences

        def resolve_variables(hog_flow, schedule):
            """Build default variables from HogFlow schema, then merge schedule overrides."""
            variables = {}
            for var in hog_flow.variables or []:
                variables[var.get("key")] = var.get("default")
            variables.update(schedule.variables or {})
            return variables

        processed = []
        initialized = []
        failed = []

        try:
            # 1. Process due schedules (next_run_at <= now)
            # nosemgrep: idor-lookup-without-team (internal endpoint processes all teams)
            due_schedule_ids = list(
                HogFlowSchedule.objects.filter(
                    status=HogFlowSchedule.Status.ACTIVE, next_run_at__lte=timezone.now()
                ).values_list("id", flat=True)
            )

            for schedule_id in due_schedule_ids:
                try:
                    batch_job_params: dict | None = None
                    schedule_invocation_params: dict | None = None
                    with transaction.atomic():
                        # Per-schedule transaction: lock only one row at a time to minimize
                        # lock duration and allow concurrent replicas via skip_locked.
                        # Re-checks conditions since the schedule may have been processed
                        # between the ID scan and this lock.
                        schedule = (
                            # nosemgrep: idor-lookup-without-team
                            HogFlowSchedule.objects.select_for_update(skip_locked=True)
                            .select_related("hog_flow")
                            .filter(
                                id=schedule_id, status=HogFlowSchedule.Status.ACTIVE, next_run_at__lte=timezone.now()
                            )
                            .first()
                        )
                        if not schedule:
                            continue

                        hog_flow = schedule.hog_flow
                        trigger_type = (hog_flow.trigger or {}).get("type")

                        if hog_flow.status != "active" or trigger_type not in SCHEDULED_TRIGGER_TYPES:
                            schedule.next_run_at = None
                            schedule.save(update_fields=["next_run_at", "updated_at"])
                            continue

                        advance_next_run(schedule, after=schedule.next_run_at)

                        if trigger_type == "batch":
                            batch_job_params = {
                                "team_id": schedule.team_id,
                                "hog_flow": hog_flow,
                                "variables": resolve_variables(hog_flow, schedule),
                                "filters": (hog_flow.trigger or {}).get("filters", {}),
                            }
                        else:
                            schedule_invocation_params = {
                                "team_id": schedule.team_id,
                                "hog_flow_id": str(hog_flow.id),
                                "variables": resolve_variables(hog_flow, schedule),
                            }

                    # Dispatch outside the transaction so HTTP calls don't hold the row lock.
                    if batch_job_params:
                        HogFlowBatchJob.objects.create(
                            **batch_job_params,
                            status=HogFlowBatchJob.State.QUEUED,
                        )
                        processed.append(str(schedule_id))
                    elif schedule_invocation_params:
                        response = create_hog_flow_scheduled_invocation(**schedule_invocation_params)
                        response.raise_for_status()
                        processed.append(str(schedule_id))
                except Exception:
                    logger.exception("Error processing schedule", schedule_id=str(schedule_id))
                    failed.append(str(schedule_id))

            # 2. Initialize next_run_at for schedules that need it
            # nosemgrep: idor-lookup-without-team (internal endpoint processes all teams)
            uninitialized_ids = list(
                HogFlowSchedule.objects.filter(
                    status=HogFlowSchedule.Status.ACTIVE,
                    next_run_at__isnull=True,
                    hog_flow__status="active",
                    hog_flow__trigger__type__in=SCHEDULED_TRIGGER_TYPES,
                ).values_list("id", flat=True)
            )

            for schedule_id in uninitialized_ids:
                try:
                    with transaction.atomic():
                        # Per-schedule transaction: lock only one row at a time to minimize
                        # lock duration and allow concurrent replicas via skip_locked.
                        # Re-checks conditions since the schedule may have been initialized
                        # between the ID scan and this lock.
                        schedule = (
                            # nosemgrep: idor-lookup-without-team
                            HogFlowSchedule.objects.select_for_update(skip_locked=True)
                            .filter(id=schedule_id, status=HogFlowSchedule.Status.ACTIVE, next_run_at__isnull=True)
                            .first()
                        )
                        if not schedule:
                            continue

                        if advance_next_run(schedule):
                            initialized.append(str(schedule.id))
                except Exception:
                    logger.exception("Error initializing schedule", schedule_id=str(schedule_id))
                    failed.append(str(schedule_id))

            return Response(
                {
                    "processed": processed,
                    "initialized": initialized,
                    "failed": failed,
                }
            )
        except Exception as e:
            logger.exception("Error in internal_process_due_schedules", error=str(e))
            return Response({"error": "Internal server error"}, status=500)

    def internal_update_batch_job_status(self, request: Request, team_id: str, batch_job_id: str) -> Response:
        """
        Internal endpoint for the Node-side batch resolver to write the terminal
        status of a HogFlowBatchJob run. Idempotent: if the row is already in a
        terminal status, returns 200 without re-writing — the resolver retries
        this call via cyclotron retry semantics, so safe repeats are required.

        Accepts: { status: "completed" | "failed" }
        """
        from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob  # noqa: PLC0415

        if request.method != "PUT":
            return Response({"error": "Method not allowed"}, status=405)

        try:
            team = Team.objects.get(id=int(team_id))
        except (Team.DoesNotExist, ValueError):
            return Response({"error": "Team not found"}, status=404)

        new_status = request.data.get("status")
        if new_status not in (HogFlowBatchJob.State.COMPLETED, HogFlowBatchJob.State.FAILED):
            return Response(
                {"error": "status must be one of: completed, failed"},
                status=400,
            )

        try:
            batch_job = HogFlowBatchJob.objects.get(id=batch_job_id, team=team)
        except (HogFlowBatchJob.DoesNotExist, DjangoValidationError, ValueError):
            # `DjangoValidationError` fires when `batch_job_id` is not a parseable
            # UUID (UUIDField rejects it before the lookup). `ValueError` is a
            # belt-and-suspenders catch for str→int / str→UUID edge cases on
            # other backends. Either way, surface as 404, not 500.
            return Response({"error": "Batch job not found"}, status=404)

        terminal_states = {
            HogFlowBatchJob.State.COMPLETED,
            HogFlowBatchJob.State.FAILED,
            HogFlowBatchJob.State.CANCELLED,
        }
        if batch_job.status in terminal_states:
            # Idempotent no-op: already in a terminal state.
            return Response(
                {
                    "id": str(batch_job.id),
                    "status": batch_job.status,
                    "no_op": True,
                }
            )

        try:
            batch_job.status = new_status
            batch_job.save(update_fields=["status", "updated_at"])
            return Response(
                {
                    "id": str(batch_job.id),
                    "status": batch_job.status,
                    "no_op": False,
                }
            )
        except Exception as e:
            logger.exception(
                "Error in internal_update_batch_job_status",
                error=str(e),
                team_id=team_id,
                batch_job_id=batch_job_id,
            )
            return Response({"error": "Internal server error"}, status=500)
