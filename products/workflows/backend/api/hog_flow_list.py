import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Any, Final, Optional, Protocol, cast

from django.db import models
from django.db.models import Case, F, Func, Q, QuerySet, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.http import QueryDict
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema_field
from rest_framework import exceptions, serializers

from posthog.api.app_metrics2 import fetch_app_metric_totals_by_source
from posthog.api.shared import UserBasicSerializer
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.messaging.backend.email_senders import (
    EmailSenderIntegration,
    EmailSenderPrefetchListSerializer,
    email_senders_from_context,
    resolve_email_sender,
)
from products.workflows.backend.models.hog_flow.hog_flow import MESSAGING_ACTION_TYPES, TRIGGER_TYPES, HogFlow

logger = structlog.get_logger(__name__)

# The actions a workflow listing filters on. `summaries` is the slim list the web app loads in full.
LIST_ACTIONS: Final[tuple[str, ...]] = ("list", "summaries")


class HogFlowType(models.TextChoices):
    MESSAGING = "messaging"
    AUTOMATION = "automation"
    LOOP = "loop"
    BROADCAST = "broadcast"


class HogFlowChannel(models.TextChoices):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    SLACK = "slack"
    WEBHOOK = "webhook"


# A workflow's type is what owns it, else what it does. `loop` and `broadcast` name the surfaces that
# have their own page, and the behavioural values exclude them: a flow those surfaces own is tagged
# by surface in the UI (see WorkflowTypeTag), so returning it under `messaging` would contradict the
# tag on the row. Accepting several lets a list say which surfaces it covers, which is how the
# workflows page asks for everything except the ones that moved out.
WORKFLOW_TYPES: Final[tuple[str, ...]] = tuple(HogFlowType.values)
OWNED_WORKFLOW_TYPES: Final[dict[str, str]] = {
    HogFlowType.LOOP: HogFlow.OriginProduct.LOOPS,
    HogFlowType.BROADCAST: HogFlow.OriginProduct.BROADCASTS,
}


def workflow_type_q(requested: set[str]) -> Q:
    owned = Q(origin_product__in=[OWNED_WORKFLOW_TYPES[t] for t in requested if t in OWNED_WORKFLOW_TYPES])
    behavioural = requested - set(OWNED_WORKFLOW_TYPES)
    if not behavioural:
        return owned

    messaging = Q()
    for action_type in MESSAGING_ACTION_TYPES:
        messaging |= Q(actions__contains=[{"type": action_type}])
    unowned = ~Q(origin_product__in=list(OWNED_WORKFLOW_TYPES.values()))
    if behavioural == {"messaging", "automation"}:
        return owned | unowned
    return owned | (unowned & (messaging if behavioural == {"messaging"} else ~messaging))


def workflow_type_of(origin_product: Optional[str], actions: Any) -> HogFlowType:
    """The row-side twin of workflow_type_q. Change both together, or the row and the `type` filter disagree."""
    for workflow_type, owner in OWNED_WORKFLOW_TYPES.items():
        if origin_product == owner:
            return HogFlowType(workflow_type)
    if any(action.get("type") in MESSAGING_ACTION_TYPES for action in _action_dicts(actions)):
        return HogFlowType.MESSAGING
    return HogFlowType.AUTOMATION


# How a channel shows up in the live actions. Slack and webhook steps share the generic `function`
# action type, so their template id tells them apart.
_CHANNEL_ACTION_TYPES: Final[dict[str, HogFlowChannel]] = {
    "function_email": HogFlowChannel.EMAIL,
    "function_sms": HogFlowChannel.SMS,
    "function_push": HogFlowChannel.PUSH,
}
_CHANNEL_FUNCTION_TEMPLATES: Final[dict[str, HogFlowChannel]] = {
    "template-slack": HogFlowChannel.SLACK,
    "template-webhook": HogFlowChannel.WEBHOOK,
}


_CHANNEL_Q: Final[dict[str, Q]] = {
    **{channel: Q(actions__contains=[{"type": action_type}]) for action_type, channel in _CHANNEL_ACTION_TYPES.items()},
    **{
        channel: Q(actions__contains=[{"type": "function", "config": {"template_id": template_id}}])
        for template_id, channel in _CHANNEL_FUNCTION_TEMPLATES.items()
    },
}


def channel_q(channel: str) -> Q:
    return _CHANNEL_Q[channel]


def _channel_of(action: dict[str, Any]) -> Optional[HogFlowChannel]:
    action_type = action.get("type")
    if action_type in _CHANNEL_ACTION_TYPES:
        return _CHANNEL_ACTION_TYPES[action_type]
    template_id = _config(action).get("template_id")
    if action_type == "function" and isinstance(template_id, str):
        return _CHANNEL_FUNCTION_TEMPLATES.get(template_id)
    return None


def json_path(path: str) -> models.Func:
    # A jsonpath bind parameter. Postgres types a plain parameter as text and the jsonb_path_*
    # functions take jsonpath, so the cast has to be spelled out.
    return models.Func(models.Value(path), template="%(expressions)s::jsonpath", output_field=models.TextField())


def jsonb_path_exists(column: str, path: str) -> models.Func:
    return models.Func(F(column), json_path(path), function="jsonb_path_exists", output_field=models.BooleanField())


def annotate_trigger_type(queryset: QuerySet) -> QuerySet:
    """Annotate `_trigger_type`, the SQL twin of the row's `trigger_type`. Change both together.

    The first trigger step is the source of truth, as in _trigger_type. The legacy `trigger` column only
    counts for a row with no trigger step, because rows exist where the two disagree. jsonpath runs in
    lax mode, so a row whose `actions` is not an array has no trigger step rather than an error.
    """
    return queryset.annotate(
        _trigger_action=Func(
            F("actions"),
            json_path('$[*] ? (@.type == "trigger")'),
            function="jsonb_path_query_first",
            output_field=models.JSONField(),
        )
    ).annotate(
        _trigger_type=Case(
            When(_trigger_action__isnull=True, then=KeyTextTransform("type", "trigger")),
            default=KeyTextTransform("type", KeyTransform("config", "_trigger_action")),
            output_field=models.TextField(),
        )
    )


@frozen
class EmailStepSummary:
    action_id: str
    name: str
    subject: str
    from_addresses: tuple[str, ...]
    from_name: Optional[str]
    from_integration_ids: tuple[int, ...]
    template_uuid: Optional[str]


@frozen
class DispatchSummary:
    action_type: str
    template_id: str
    count: int


@frozen
class HogFlowListSummary:
    type: HogFlowType
    trigger_type: Optional[str]
    channels: tuple[HogFlowChannel, ...]
    dispatches: tuple[DispatchSummary, ...]
    email_steps: tuple[EmailStepSummary, ...]


def _action_dicts(actions: Any) -> list[dict[str, Any]]:
    # `actions` defaults to {} on a workflow that never got a graph.
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _config(action: dict[str, Any]) -> dict[str, Any]:
    config = action.get("config")
    return config if isinstance(config, dict) else {}


def _email_value(action: dict[str, Any]) -> dict[str, Any]:
    inputs = _config(action).get("inputs")
    email_input = inputs.get("email") if isinstance(inputs, dict) else None
    value = email_input.get("value") if isinstance(email_input, dict) else None
    return value if isinstance(value, dict) else {}


def _email_actions(actions: Any) -> list[dict[str, Any]]:
    return [action for action in _action_dicts(actions) if action.get("type") == "function_email"]


def _trigger_type(actions: Any, trigger_column: Any) -> Optional[str]:
    trigger_action = next((action for action in _action_dicts(actions) if action.get("type") == "trigger"), None)
    source = _config(trigger_action) if trigger_action is not None else trigger_column
    trigger_type = source.get("type") if isinstance(source, dict) else None
    return trigger_type if isinstance(trigger_type, str) and trigger_type else None


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def summarize_hog_flow(
    *,
    actions: Any,
    trigger_column: Any,
    origin_product: Optional[str],
    integrations: Mapping[int, EmailSenderIntegration],
) -> HogFlowListSummary:
    """What a workflow list row shows, derived from the live actions only.

    The summary carries no action config beyond the email subject and sender, so it is safe to return
    anywhere a workflow's name is.
    """
    action_list = _action_dicts(actions)
    channels = {channel for channel in map(_channel_of, action_list) if channel is not None}

    dispatch_counts: Counter[str] = Counter()
    first_action_type: dict[str, str] = {}
    for action in action_list:
        action_type = action.get("type")
        template_id = _config(action).get("template_id")
        if isinstance(action_type, str) and action_type.startswith("function") and isinstance(template_id, str):
            dispatch_counts[template_id] += 1
            first_action_type.setdefault(template_id, action_type)

    email_steps = []
    for action in _email_actions(action_list):
        value = _email_value(action)
        sender = resolve_email_sender(value.get("from"), integrations)
        subject = value.get("subject")
        email_steps.append(
            EmailStepSummary(
                action_id=str(action.get("id") or ""),
                name=str(action.get("name") or ""),
                subject=subject if isinstance(subject, str) else "",
                from_addresses=sender.addresses,
                from_name=sender.name,
                from_integration_ids=sender.integration_ids,
                template_uuid=_optional_str(_config(action).get("template_uuid")),
            )
        )

    return HogFlowListSummary(
        type=workflow_type_of(origin_product, action_list),
        trigger_type=_trigger_type(action_list, trigger_column),
        channels=tuple(channel for channel in HogFlowChannel if channel in channels),
        dispatches=tuple(
            DispatchSummary(action_type=first_action_type[template_id], template_id=template_id, count=count)
            for template_id, count in dispatch_counts.items()
        ),
        email_steps=tuple(email_steps),
    )


def _comma_list(params: QueryDict, key: str, allowed: Sequence[str]) -> Optional[set[str]]:
    raw = params.get(key)
    if not raw:
        return None
    requested = {value for value in raw.split(",") if value}
    unknown = sorted(requested - set(allowed))
    # A value of only separators names nothing. Filtering on nothing would answer with an empty list,
    # so it is rejected the way any other unusable value is.
    if unknown or not requested:
        named = f"Unknown: {', '.join(unknown)}. " if unknown else ""
        raise exceptions.ValidationError({key: f"{named}Must be one of: {', '.join(allowed)}"})
    return requested


def _user_uuids(params: QueryDict, key: str) -> Optional[list[str]]:
    raw = params.get(key)
    if not raw:
        return None
    values = [value for value in raw.split(",") if value]
    try:
        # A value of only separators names no user, and is rejected like a malformed uuid.
        if not values:
            raise ValueError(raw)
        return [str(uuid.UUID(value)) for value in values]
    except ValueError:
        raise exceptions.ValidationError({key: "Must be a valid user uuid"})


STATUS_VALUES: Final[tuple[str, ...]] = tuple(HogFlow.State.values)
TRIGGER_TYPE_VALUES: Final[tuple[str, ...]] = tuple(sorted(TRIGGER_TYPES))
CHANNEL_VALUES: Final[tuple[str, ...]] = tuple(HogFlowChannel.values)


def apply_list_filters(queryset: QuerySet, params: QueryDict) -> QuerySet:
    """The server filters shared by the workflow list and its slim summaries.

    Values within one param are OR, params are AND, and an `exclude_*` param drops rows that have any of
    its values. Every value that reaches SQL is either checked against a fixed set or parsed as a uuid.
    """
    for key, negate in (("status", False), ("exclude_status", True)):
        statuses = _comma_list(params, key, STATUS_VALUES)
        if statuses:
            condition = Q(status__in=sorted(statuses))
            queryset = queryset.filter(~condition if negate else condition)

    for key, negate in (("type", False), ("exclude_type", True)):
        workflow_types = _comma_list(params, key, WORKFLOW_TYPES)
        if workflow_types:
            condition = workflow_type_q(workflow_types)
            queryset = queryset.filter(~condition if negate else condition)

    trigger_type_filters = [
        (trigger_types, negate)
        for key, negate in (("trigger_type", False), ("exclude_trigger_type", True))
        if (trigger_types := _comma_list(params, key, TRIGGER_TYPE_VALUES))
    ]
    if trigger_type_filters:
        queryset = annotate_trigger_type(queryset)
    for trigger_types, negate in trigger_type_filters:
        condition = Q(_trigger_type__in=sorted(trigger_types))
        queryset = queryset.filter(~condition if negate else condition)

    for key, negate in (("channel", False), ("exclude_channel", True)):
        channels = _comma_list(params, key, CHANNEL_VALUES)
        if channels:
            condition = Q()
            for channel in sorted(channels):
                condition |= channel_q(channel)
            queryset = queryset.filter(~condition if negate else condition)

    for key, negate in (("created_by", False), ("exclude_created_by", True)):
        user_uuids = _user_uuids(params, key)
        if user_uuids:
            condition = Q(created_by__uuid__in=user_uuids)
            queryset = queryset.filter(~condition if negate else condition)

    return queryset


# Seconds. The totals are a column on a list, so a slow metrics store costs the column, not the page.
TOTALS_MAX_EXECUTION_TIME: Final = 5


def fetch_last_7_days_totals(team_id: int, workflow_ids: Sequence[str]) -> Optional[dict[str, dict[str, int]]]:
    """Succeeded and failed totals for the last 7 days of the given workflows, or None when ClickHouse fails.

    A metrics outage or timeout must not take the list down with it, so the caller renders every row
    without totals.
    """
    if not workflow_ids:
        return {}
    try:
        return fetch_app_metric_totals_by_source(
            team_id=team_id,
            app_source="hog_flow",
            after=timezone.now() - timedelta(days=7),
            app_source_ids=list(workflow_ids),
            max_execution_time=TOTALS_MAX_EXECUTION_TIME,
        )
    except Exception as error:
        logger.exception("hog_flow_summaries_totals_failed", team_id=team_id)
        capture_exception(error)
        return None


# Everything a summary row never reads. Loading these for a full page of workflows costs more than the
# rows themselves, and the encrypted columns cost a decrypt each.
SUMMARY_DEFERRED_FIELDS: Final[tuple[str, ...]] = (
    "draft",
    "draft_encrypted_inputs",
    "encrypted_inputs",
    "edges",
    "conversion",
    "variables",
    "action_redirects",
    "trigger_masking",
)

# Serializer context keys: the derived summary per row, and the page's totals from the summaries action.
_SUMMARY_CACHE_CONTEXT_KEY: Final = "_hog_flow_list_summaries"
RUN_TOTALS_CONTEXT_KEY: Final = "last_7_days_totals"


class EmailStepSummarySerializer(serializers.Serializer):
    action_id = serializers.CharField(help_text="Id of the email step in the workflow's actions.")
    name = serializers.CharField(help_text="Name of the email step.")
    subject = serializers.CharField(
        help_text="Subject line as written, Liquid tags included. Empty when the step has no subject."
    )
    from_addresses = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Every address the step can send from: the override address when set, otherwise the address of "
            "each sender integration a send can pick. Integrations that no longer exist are skipped."
        ),
    )
    from_name = serializers.CharField(
        allow_null=True,
        help_text="Display name of the sender: the override name, else the first resolved sender integration's name.",
    )
    from_integration_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text=(
            "Sender integration ids a send can pick: the `integrationIds` rotation when it is set, "
            "otherwise the single `integrationId`."
        ),
    )
    template_uuid = serializers.CharField(
        allow_null=True, help_text="Id of the email template this step was based on, or null when it has no link."
    )


class DispatchSummarySerializer(serializers.Serializer):
    action_type = serializers.CharField(help_text="Action type of the first step using this template, e.g. `function`.")
    template_id = serializers.CharField(help_text="Function template id the steps dispatch through.")
    count = serializers.IntegerField(help_text="Number of steps in the workflow that use this template.")


class WorkflowRunTotalsSerializer(serializers.Serializer):
    succeeded = serializers.IntegerField(help_text="Succeeded metric count in the last 7 days.")
    failed = serializers.IntegerField(help_text="Failed metric count in the last 7 days.")


class HogFlowSummaryListSerializer(EmailSenderPrefetchListSerializer):
    def sender_from_values(self, row: HogFlow) -> Iterable[Any]:
        return [_email_value(action).get("from") for action in _email_actions(row.actions)]


class _ListedHogFlow(Protocol):
    # Annotated by HogFlowViewSet.safely_get_queryset for the list actions.
    has_draft: bool


class HogFlowSummaryFieldsMixin(serializers.Serializer):
    """The derived fields a workflow listing shows, shared by the slim summaries and the MCP list."""

    type = serializers.SerializerMethodField(
        help_text=(
            "`loop` and `broadcast` for workflows those surfaces own. Otherwise `messaging` when a live step "
            "sends email, SMS or push, else `automation`. Matches the `type` filter."
        )
    )
    trigger_type = serializers.SerializerMethodField(
        help_text="Trigger type from the live trigger step, e.g. `event` or `schedule`. Null when there is none."
    )
    has_draft = serializers.SerializerMethodField(help_text="Whether staged changes are waiting to be published.")
    channels = serializers.SerializerMethodField(
        help_text="Channels the live steps send on, without duplicates, in the order email, sms, push, slack, webhook."
    )
    email_steps = serializers.SerializerMethodField(
        help_text="One entry per live email step, in step order, with its subject and sender. Never the email body."
    )

    def _summary(self, instance: HogFlow) -> HogFlowListSummary:
        cache: dict[uuid.UUID, HogFlowListSummary] = self.context.setdefault(_SUMMARY_CACHE_CONTEXT_KEY, {})
        if instance.id not in cache:
            cache[instance.id] = summarize_hog_flow(
                actions=instance.actions,
                trigger_column=instance.trigger,
                origin_product=instance.origin_product,
                integrations=email_senders_from_context(self.context),
            )
        return cache[instance.id]

    @extend_schema_field(serializers.ChoiceField(choices=HogFlowType.choices))
    def get_type(self, instance: HogFlow) -> str:
        return self._summary(instance).type.value

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_trigger_type(self, instance: HogFlow) -> Optional[str]:
        return self._summary(instance).trigger_type

    @extend_schema_field(serializers.BooleanField())
    def get_has_draft(self, instance: HogFlow) -> bool:
        # Read from the annotation so a listing never loads the draft JSON.
        return bool(cast(_ListedHogFlow, instance).has_draft)

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=HogFlowChannel.choices)))
    def get_channels(self, instance: HogFlow) -> list[str]:
        return [channel.value for channel in self._summary(instance).channels]

    @extend_schema_field(EmailStepSummarySerializer(many=True))
    def get_email_steps(self, instance: HogFlow) -> Any:
        return EmailStepSummarySerializer(self._summary(instance).email_steps, many=True).data


class HogFlowListRowSerializer(
    HogFlowSummaryFieldsMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
):
    # Deliberately not a HogFlowMinimalSerializer: its to_representation reads the encrypted input columns
    # on every row, which the summaries queryset defers, so each row would lazy-load them. The row has no
    # secret-bearing field, so it needs no masking.
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the workflow.")
    dispatches = serializers.SerializerMethodField(
        help_text="One entry per function template the live steps dispatch through, in first-seen order."
    )
    last_7_days = serializers.SerializerMethodField(
        help_text=(
            "Succeeded and failed metric totals over the last 7 days, as returned by `metrics/global`. "
            "Null on every row when the metrics store is unavailable."
        )
    )

    class Meta:
        model = HogFlow
        list_serializer_class = HogFlowSummaryListSerializer
        fields = [
            "id",
            "name",
            "description",
            "status",
            "type",
            "origin_product",
            "trigger_type",
            "has_draft",
            "channels",
            "dispatches",
            "email_steps",
            "created_by",
            "created_at",
            "updated_at",
            "user_access_level",
            "last_7_days",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Workflow id."},
            "name": {"help_text": "Workflow name."},
            "description": {"help_text": "Workflow description."},
            "status": {"help_text": "Lifecycle status: `draft`, `active` or `archived`."},
            "origin_product": {"help_text": "Product surface that owns the workflow, or null for the workflows UI."},
            "created_at": {"help_text": "When the workflow was created."},
            "updated_at": {"help_text": "When the workflow was last changed."},
        }

    @extend_schema_field(DispatchSummarySerializer(many=True))
    def get_dispatches(self, instance: HogFlow) -> Any:
        return DispatchSummarySerializer(self._summary(instance).dispatches, many=True).data

    @extend_schema_field(WorkflowRunTotalsSerializer(allow_null=True))
    def get_last_7_days(self, instance: HogFlow) -> Optional[dict[str, int]]:
        totals: Optional[dict[str, dict[str, int]]] = self.context.get(RUN_TOTALS_CONTEXT_KEY)
        if totals is None:
            return None
        counts = totals.get(str(instance.id), {})
        return {"succeeded": counts.get("succeeded", 0), "failed": counts.get("failed", 0)}


def _comma_list_parameter(name: str, values: Sequence[str], description: str) -> OpenApiParameter:
    return OpenApiParameter(name, OpenApiTypes.STR, description=f"{description} One of: {', '.join(values)}.")


LIST_FILTER_PARAMETERS: Final[list[OpenApiParameter]] = [
    OpenApiParameter(
        "search",
        OpenApiTypes.STR,
        description="Case-insensitive search. Matches workflow name and description first; only when nothing matches those, it matches step names and the subject line, preheader and body text of email steps, in both the live workflow and its pending draft.",
    ),
    _comma_list_parameter("status", STATUS_VALUES, "Comma-separated statuses. Returns workflows in any of them."),
    _comma_list_parameter(
        "exclude_status", STATUS_VALUES, "Comma-separated statuses. Leaves out workflows in any of them."
    ),
    OpenApiParameter(
        "created_by",
        OpenApiTypes.STR,
        description="Comma-separated user uuids. Returns workflows created by any of these users.",
    ),
    OpenApiParameter(
        "exclude_created_by",
        OpenApiTypes.STR,
        description="Comma-separated user uuids. Leaves out workflows created by any of these users. Workflows with no creator stay.",
    ),
    OpenApiParameter(
        "type",
        OpenApiTypes.STR,
        description="Comma-separated workflow types. `loop` and `broadcast` return the workflows those surfaces own; `messaging` returns the remaining workflows with an email, SMS, or push action, and `automation` the rest.",
    ),
    _comma_list_parameter(
        "exclude_type", WORKFLOW_TYPES, "Comma-separated workflow types. Leaves out workflows of any of them."
    ),
    _comma_list_parameter(
        "trigger_type",
        TRIGGER_TYPE_VALUES,
        "Comma-separated trigger types. Returns workflows whose trigger step has any of them.",
    ),
    _comma_list_parameter(
        "exclude_trigger_type",
        TRIGGER_TYPE_VALUES,
        "Comma-separated trigger types. Leaves out workflows whose trigger step has any of them.",
    ),
    _comma_list_parameter(
        "channel", CHANNEL_VALUES, "Comma-separated channels. Returns workflows with a step sending on any of them."
    ),
    _comma_list_parameter(
        "exclude_channel",
        CHANNEL_VALUES,
        "Comma-separated channels. Leaves out workflows with a step sending on any of them.",
    ),
    OpenApiParameter(
        "origin_product",
        OpenApiTypes.STR,
        enum=HogFlow.OriginProduct.values,
        description="Filter to workflows owned by a product surface, e.g. `loops` for Desktop loops.",
    ),
    OpenApiParameter(
        "trigger",
        OpenApiTypes.STR,
        description='Filter by trigger config as a JSON object. Returns workflows whose trigger contains the given object, e.g. {"type": "event"}.',
    ),
    OpenApiParameter(
        "broadcast_eligible",
        OpenApiTypes.BOOL,
        description="Pass `true` to return broadcasts plus the ordinary workflows the broadcasts UI can render: a batch trigger and a single email step.",
    ),
]
