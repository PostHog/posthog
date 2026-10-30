import uuid
import dataclasses
from collections.abc import Callable, Sequence
from typing import ClassVar, Generic, Optional, Self, TypeVar, cast

from django.db.models import QuerySet
from django.http import Http404

import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import exceptions, filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.ordering import StableOrderingFilter
from posthog.api.pagination import PrecountedLimitOffsetPagination
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import get_request_analytics_properties, groups
from posthog.exceptions import QuotaLimitExceeded
from posthog.models.user import User
from posthog.permissions import is_service_auth
from posthog.rate_limit import SubscriptionTestDeliveryThrottle
from posthog.utils import str_to_bool

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.dashboards.backend.facade import api as dashboards_api
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade import api, contracts
from products.subscriptions.backend.facade.api import (
    AI_QUERY_PLAN_STATUS_CHOICES,
    AI_REPORT_CHARTS_KEY,
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_QUERY_FAILURE_TYPE,
    AI_REPORT_QUERY_PLAN_STATUS_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    AI_WINDOW_MODE_CHOICES,
    AI_WINDOW_MODE_LAST_N_DAYS,
    AI_WINDOW_MODE_SINCE_LAST_SENT,
    DELIVERY_STATUS_CHOICES,
    FREQUENCY_CHOICES,
    MAX_AI_SUBSCRIPTION_CONTEXTS,
    MAX_INSIGHTS,
    RESOURCE_TYPE_CHOICES,
    TARGET_TYPE_CHOICES,
    TARGET_TYPE_TEAMS,
    WEEKDAY_CHOICES,
)

_AI_QUERY_PLAN_STATUS_VALUES = frozenset(value for value, _ in AI_QUERY_PLAN_STATUS_CHOICES)
_TARGET_TYPE_VALUES = [value for value, _ in TARGET_TYPE_CHOICES]
_DELIVERY_STATUS_VALUES = [value for value, _ in DELIVERY_STATUS_CHOICES]

# An agent reads one field's description in isolation, so every field repeats the scope rule.
_AI_DISPLAY_FIELD_SCOPE_NOTE = (
    "The request is rejected when the subscription sets insight or dashboard instead of prompt. "
    "It does not control the AI summary on an insight or dashboard subscription: use "
    "summary_enabled and summary_prompt_guide for that."
)

_Row = TypeVar("_Row")


def _insight_exists(insight_id: int) -> bool:
    # The facade compares the insight's team with the request's team right after this check.
    # nosemgrep: idor-lookup-without-team
    return Insight.objects.filter(pk=insight_id).exists()


@extend_schema_field(OpenApiTypes.INT)
class _RelatedIdField(serializers.Field):
    """The id of an existing insight or dashboard, accepted and rejected the way a primary key
    related field accepts and rejects it."""

    default_error_messages = serializers.PrimaryKeyRelatedField.default_error_messages

    def __init__(
        self, *, exists: Callable[[int], bool], source: str, allow_null: bool, required: bool, help_text: str
    ) -> None:
        self._exists = exists
        super().__init__(source=source, allow_null=allow_null, required=required, help_text=help_text)

    def run_validation(self, data: object = serializers.empty) -> object:
        # Relational fields read an empty string as null.
        if data == "":
            data = None
        return super().run_validation(data)

    def to_internal_value(self, data: object) -> int:
        try:
            if isinstance(data, bool):
                raise TypeError
            pk = int(cast(str, data))
        except (TypeError, ValueError):
            self.fail("incorrect_type", data_type=type(data).__name__)
        if not self._exists(pk):
            self.fail("does_not_exist", pk_value=data)
        return pk

    def to_representation(self, value: int) -> int:
        return value


@extend_schema_field({"type": "array", "items": {"type": "integer"}})
class DashboardExportInsightsField(serializers.Field):
    """Custom field to handle ManyToMany dashboard_export_insights as a list of IDs."""

    def to_representation(self, value: Sequence[int]) -> list[int]:
        return list(value)

    def to_internal_value(self, data: object) -> list[int]:
        if not isinstance(data, list):
            raise serializers.ValidationError("Expected a list of insight IDs.")
        for item in data:
            if not isinstance(item, int):
                raise serializers.ValidationError("All items must be integers.")
        return data


class AIWindowConfigSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(
        choices=AI_WINDOW_MODE_CHOICES,
        default=AI_WINDOW_MODE_SINCE_LAST_SENT,
        help_text=(
            "What the report analyzes each run:\n"
            "* `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test/manual sends don't move the anchor)\n"
            "* `last_n_days` — a fixed trailing window of start_days_ago days\n"
            "* `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago"
        ),
    )
    start_days_ago = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=365,
        help_text=(
            "Lower bound of the analysis window, in days before the run. Required for 'last_n_days' "
            "(the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365."
        ),
    )
    end_days_ago = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=365,
        help_text=(
            "Upper bound of the analysis window, in days before the run (0 = now). Required for "
            "'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365."
        ),
    )

    def to_representation(self, instance: contracts.JsonValue) -> dict:
        return api.normalize_ai_window(instance)

    def validate(self, attrs: dict) -> dict:
        mode = attrs.get("mode") or AI_WINDOW_MODE_SINCE_LAST_SENT
        start = attrs.get("start_days_ago")
        end = attrs.get("end_days_ago")

        if mode == AI_WINDOW_MODE_SINCE_LAST_SENT:
            # Day bounds are meaningless here; normalise them away so a later mode switch starts clean.
            attrs["start_days_ago"] = None
            attrs["end_days_ago"] = None
            return attrs
        if not start:
            raise ValidationError({"start_days_ago": [f"Required when mode is '{mode}'."]})
        if mode == AI_WINDOW_MODE_LAST_N_DAYS:
            attrs["end_days_ago"] = None
            return attrs
        # DAYS_AGO_RANGE
        if end is None:
            raise ValidationError({"end_days_ago": [f"Required when mode is '{mode}'."]})
        if end >= start:
            raise ValidationError(
                {"end_days_ago": ["Must be less than start_days_ago (the window must end after it starts)."]}
            )
        return attrs


class AIPromptConfigSerializer(serializers.Serializer):
    window = AIWindowConfigSerializer(
        required=False,
        help_text="Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery).",
    )


class DeliveryConfigSerializer(serializers.Serializer):
    """Typed view over the Subscription.delivery_config JSON blob."""

    post_all_insights_in_main_message = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Slack insight and dashboard subscriptions only: when true, upload all insight images "
            "together in the main Slack message instead of posting the first image in the main "
            "message and the rest as threaded replies. Defaults to false. The request is rejected "
            "when target_type is not 'slack', when the subscription sets prompt instead of insight "
            "or dashboard, or when the Slack integration does not hold the files:write permission. "
            "Omit it unless the user asks for one combined message."
        ),
    )
    include_images = serializers.BooleanField(
        required=False,
        help_text="Prompt subscriptions only: include generated chart images. Defaults to true when omitted. "
        + _AI_DISPLAY_FIELD_SCOPE_NOTE,
    )
    include_feedback = serializers.BooleanField(
        required=False,
        help_text="Prompt subscriptions only: include report feedback links. Defaults to true when omitted. "
        + _AI_DISPLAY_FIELD_SCOPE_NOTE,
    )
    include_manage_link = serializers.BooleanField(
        required=False,
        help_text="Prompt subscriptions only: include a link to manage the subscription. "
        "Defaults to true when omitted. " + _AI_DISPLAY_FIELD_SCOPE_NOTE,
    )
    include_posthog_hint = serializers.BooleanField(
        required=False,
        help_text="Prompt subscriptions only: include PostHog product guidance. Defaults to true when "
        "omitted. Only a Slack report renders the guidance. Email and Microsoft Teams reports leave it "
        "out and accept the option without an error, unlike post_all_insights_in_main_message. "
        + _AI_DISPLAY_FIELD_SCOPE_NOTE,
    )


class SubscriptionContextWriteSerializer(serializers.Serializer):
    dashboard_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Dashboard ID to use as AI report context. Set either dashboard_id or insight_id, not both.",
    )
    insight_id = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Insight ID to use as AI report context. Set either insight_id or dashboard_id, not both.",
    )

    def validate(self, attrs: dict) -> dict:
        if ("dashboard_id" in attrs) == ("insight_id" in attrs):
            raise ValidationError("Set exactly one of dashboard_id or insight_id.")
        return attrs


@extend_schema_field(
    {
        "type": "array",
        "maxItems": MAX_AI_SUBSCRIPTION_CONTEXTS,
        "items": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["dashboard_id"],
                    "properties": {"dashboard_id": {"type": "integer", "minimum": 1}},
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["insight_id"],
                    "properties": {"insight_id": {"type": "integer", "minimum": 1}},
                },
            ]
        },
    }
)
class SubscriptionContextsWriteField(serializers.ListField):
    pass


class SubscriptionDashboardContextSerializer(serializers.Serializer):
    dashboard_id = serializers.IntegerField(help_text="Dashboard ID used to open the context dashboard.")
    dashboard_name = serializers.CharField(help_text="Current display name of the context dashboard.")


class SubscriptionInsightContextSerializer(serializers.Serializer):
    insight_id = serializers.IntegerField(help_text="Database ID of the context insight.")
    insight_short_id = serializers.CharField(help_text="Stable insight identifier used to open the context insight.")
    insight_name = serializers.CharField(help_text="Current display name of the context insight.")


SUBSCRIPTION_CONTEXT_READ_SCHEMA = PolymorphicProxySerializer(
    component_name="SubscriptionContext",
    serializers=[SubscriptionDashboardContextSerializer, SubscriptionInsightContextSerializer],
    resource_type_field_name=None,
    many=True,
)

# Field order of the subscription serializers, which the generated types follow.
_SUBSCRIPTION_FIELDS = (
    "id",
    "resource_type",
    "dashboard",
    "insight",
    "insight_short_id",
    "resource_name",
    "dashboard_export_insights",
    "prompt",
    "ai_prompt_config",
    "contexts",
    "ai_query_plan_status",
    "target_type",
    "target_value",
    "frequency",
    "interval",
    "byweekday",
    "bysetpos",
    "count",
    "start_date",
    "until_date",
    "created_at",
    "created_by",
    "deleted",
    "enabled",
    "title",
    "summary",
    "next_delivery_date",
    "integration_id",
    "invite_message",
    "send_test_now",
    "summary_enabled",
    "summary_prompt_guide",
    "delivery_config",
)


class SubscriptionWriteSerializer(serializers.Serializer):
    """Standard Subscription serializer."""

    id = serializers.IntegerField(read_only=True)
    resource_type = serializers.ChoiceField(
        choices=RESOURCE_TYPE_CHOICES,
        read_only=True,
        help_text=(
            "What the subscription delivers: 'insight' (snapshot of one insight), "
            "'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). "
            "Read-only — derived from the populated target (insight → insight, "
            "dashboard → dashboard, prompt → ai_prompt)."
        ),
    )
    dashboard = _RelatedIdField(
        exists=dashboards_api.dashboard_exists,
        source="dashboard_id",
        allow_null=True,
        required=False,
        help_text="Dashboard ID to subscribe to (mutually exclusive with insight on create).",
    )
    insight = _RelatedIdField(
        exists=_insight_exists,
        source="insight_id",
        allow_null=True,
        required=False,
        help_text="Insight ID to subscribe to (mutually exclusive with dashboard on create).",
    )
    insight_short_id = serializers.SerializerMethodField()
    resource_name = serializers.SerializerMethodField()
    dashboard_export_insights = DashboardExportInsightsField(
        source="dashboard_export_insight_ids",
        required=False,
        help_text=f"List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max {MAX_INSIGHTS}.",
    )
    prompt = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        style={"base_template": "textarea.html"},
        help_text=(
            "Free-text prompt that drives the AI-generated report. Required when "
            "resource_type is 'ai_prompt'. Max 4000 characters."
        ),
    )
    ai_prompt_config = AIPromptConfigSerializer(
        required=False,
        help_text=(
            "Configuration for AI report subscriptions (analysis window, future knobs). Only valid "
            "when resource_type is 'ai_prompt'. Replaced wholesale on writes."
        ),
    )
    contexts: serializers.Field = SubscriptionContextsWriteField(
        child=SubscriptionContextWriteSerializer(),
        required=False,
        write_only=True,
        help_text=(
            "Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty "
            f"list to clear, or pass up to {MAX_AI_SUBSCRIPTION_CONTEXTS} items to replace all contexts."
        ),
    )
    ai_query_plan_status = serializers.SerializerMethodField(
        help_text=(
            "Query plan reuse state for AI prompt subscriptions: frozen, not_frozen, or planner_updated. "
            "Null for other subscription types."
        )
    )
    target_type = serializers.ChoiceField(
        choices=TARGET_TYPE_CHOICES, help_text="Delivery channel: email, slack, or teams."
    )
    target_value = serializers.CharField(
        style={"base_template": "textarea.html"},
        help_text=(
            "Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, "
            "or a Microsoft Teams webhook URL for teams. A Teams webhook URL is only ever returned as "
            "its host, because the URL authorizes a post to the channel by itself. On update, omit the "
            "field to keep the stored URL, or send a full URL to replace it."
        ),
    )
    frequency = serializers.ChoiceField(
        choices=FREQUENCY_CHOICES, help_text="How often to deliver: daily, weekly, monthly, or yearly."
    )
    interval = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=2147483647,
        help_text=(
            "Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). "
            "Required on create; must be 1 or greater."
        ),
    )
    byweekday = serializers.ListField(
        child=serializers.ChoiceField(choices=WEEKDAY_CHOICES),
        allow_null=True,
        required=False,
        help_text="Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.",
    )
    bysetpos = serializers.IntegerField(
        allow_null=True,
        required=False,
        min_value=-2147483648,
        max_value=2147483647,
        help_text="Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).",
    )
    count = serializers.IntegerField(
        allow_null=True,
        required=False,
        min_value=-2147483648,
        max_value=2147483647,
        help_text="Total number of deliveries before the subscription stops. Null for unlimited.",
    )
    start_date = serializers.DateTimeField(
        help_text=(
            "When to start delivering (ISO 8601 datetime). The date anchors the recurrence and may be in "
            "the past. Deliveries run on half-hour cycles at :00 and :30. Other minute values are accepted "
            "for backward compatibility, but delivery happens during the next cycle instead of at that exact minute."
        )
    )
    until_date = serializers.DateTimeField(
        allow_null=True,
        required=False,
        help_text="When to stop delivering (ISO 8601 datetime). Null for indefinite.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    deleted = serializers.BooleanField(
        required=False, help_text="Set to true to soft-delete. Subscriptions cannot be hard-deleted."
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid.",
    )
    title = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
        max_length=100,
        help_text="Human-readable name for this subscription.",
    )
    summary = serializers.CharField(read_only=True, help_text="Human-readable schedule summary, e.g. 'sent daily'.")
    next_delivery_date = serializers.DateTimeField(allow_null=True, read_only=True)
    integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of a connected Slack integration. Required when target_type is slack.",
    )
    invite_message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional message included in the invitation email when adding new recipients.",
    )
    send_test_now = serializers.BooleanField(
        required=False,
        write_only=True,
        help_text=(
            "Whether to immediately deliver the subscription once on save so the editor can confirm "
            "it looks right. Defaults to true on create. When omitted on update, a delivery is sent "
            "only if the edit changed what gets delivered (recipient, channel, source) or re-enabled "
            "the subscription. The recurring schedule is unaffected."
        ),
    )
    summary_enabled = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether to attach an AI-generated summary to each delivery (insight and dashboard "
            "subscriptions only). Requires the organization to have approved AI data processing, and "
            "is subject to the org's active-summary cap and AI credit budget; otherwise the write is "
            "rejected. Not applicable to prompt subscriptions, which are themselves AI-generated."
        ),
    )
    summary_prompt_guide = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=500,
        help_text=(
            "Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics "
            "to emphasize. Only settable when AI summary context is enabled for the organization; "
            "clearing it (empty string) is always allowed."
        ),
    )
    delivery_config = DeliveryConfigSerializer(
        required=False,
        help_text=(
            "Per-delivery rendering options. Every option applies to one subscription kind or delivery "
            "target only, and each option's own description says where it applies and whether a "
            "mismatch is rejected or ignored. Omit this field unless the user asks for one of the "
            "options."
        ),
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        return {name: fields[name] for name in _SUBSCRIPTION_FIELDS}

    def get_insight_short_id(self, obj: contracts.SubscriptionRecord) -> Optional[str]:
        return obj.insight_short_id

    def get_resource_name(self, obj: contracts.SubscriptionRecord) -> Optional[str]:
        return obj.resource_name

    @extend_schema_field(
        serializers.ChoiceField(
            choices=AI_QUERY_PLAN_STATUS_CHOICES,
            allow_null=True,
        )
    )
    def get_ai_query_plan_status(self, subscription: contracts.SubscriptionRecord) -> Optional[str]:
        return subscription.ai_query_plan_status

    def to_representation(self, instance: contracts.SubscriptionRecord) -> dict:
        representation = super().to_representation(instance)
        if instance.target_type == TARGET_TYPE_TEAMS:
            representation["target_value"] = instance.recipient_label
        return representation

    def to_write(self) -> contracts.SubscriptionWrite:
        values = dict(self.validated_data)
        if "contexts" in values:
            values["contexts"] = tuple(
                contracts.SubscriptionContextTarget(kind="dashboard", id=context["dashboard_id"])
                if "dashboard_id" in context
                else contracts.SubscriptionContextTarget(kind="insight", id=context["insight_id"])
                for context in values["contexts"]
            )
        # The fields' sources name the SubscriptionWrite fields, so validated data maps onto it one to one.
        return contracts.SubscriptionWrite(**values)


class SubscriptionSerializer(SubscriptionWriteSerializer):
    contexts: serializers.Field = serializers.SerializerMethodField(
        help_text="Dashboards and insights that ground this AI report. Deleted resources are omitted."
    )

    @extend_schema_field(SUBSCRIPTION_CONTEXT_READ_SCHEMA)
    def get_contexts(self, obj: contracts.SubscriptionRecord) -> list[dict[str, str | int]]:
        contexts: list[dict[str, str | int]] = []
        for context in obj.contexts:
            if isinstance(context, contracts.SubscriptionDashboardContext):
                contexts.append({"dashboard_id": context.dashboard_id, "dashboard_name": context.dashboard_name})
            else:
                contexts.append(
                    {
                        "insight_id": context.insight_id,
                        "insight_short_id": context.insight_short_id,
                        "insight_name": context.insight_name,
                    }
                )
        return contexts


def _write_response(subscription: contracts.SubscriptionRecord, *, partial: bool) -> dict:
    # A write answers with its contexts last, after the fields the request itself can set. A partial
    # write leaves out the defaults of nested fields the stored value does not hold.
    data = dict(SubscriptionSerializer(subscription, partial=partial).data)
    data["contexts"] = data.pop("contexts")
    return data


def _parse_int_param(value: str, param: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise ValidationError({param: ["Must be an integer ID."]}) from None


def _parse_int_list_param(value: str, param: str) -> list[int]:
    # int() (not str.isdigit) so exotic digits like "²" fail as a 400 here instead of a 500,
    # and invalid tokens reject the request instead of being silently dropped.
    tokens = [token.strip() for token in value.split(",") if token.strip()]
    try:
        ids = [int(token) for token in tokens]
    except ValueError:
        ids = []
    if not ids:
        raise ValidationError({param: ["Must be a comma-separated list of integer insight IDs."]})
    return ids


class _CreatedAtCursorSource(Generic[_Row]):
    """Stands in for a queryset under `CursorPagination`, which orders by `created_at`, filters by the
    cursor position, and slices. The slice reads one window through the facade, so DRF still decodes
    the cursor and builds the links."""

    def __init__(
        self,
        read_window: Callable[[contracts.CreatedAtCursorWindow], list[_Row]],
        *,
        newest_first: bool = True,
        created_before: str | None = None,
        created_after: str | None = None,
    ) -> None:
        self._read_window = read_window
        self._newest_first = newest_first
        self._created_before = created_before
        self._created_after = created_after

    def order_by(self, *ordering: str) -> Self:
        if ordering not in (("-created_at",), ("created_at",)):
            raise ValueError(f"Unsupported ordering: {ordering}")
        return type(self)(
            self._read_window,
            newest_first=ordering == ("-created_at",),
            created_before=self._created_before,
            created_after=self._created_after,
        )

    def filter(self, *, created_at__lt: str | None = None, created_at__gt: str | None = None) -> Self:
        return type(self)(
            self._read_window,
            newest_first=self._newest_first,
            created_before=created_at__lt,
            created_after=created_at__gt,
        )

    def __getitem__(self, rows: slice) -> list[_Row]:
        offset = rows.start or 0
        return self._read_window(
            contracts.CreatedAtCursorWindow(
                newest_first=self._newest_first,
                created_before=self._created_before,
                created_after=self._created_after,
                offset=offset,
                limit=rows.stop - offset,
            )
        )


def _paginate_by_created_at(view: viewsets.GenericViewSet, source: _CreatedAtCursorSource[_Row]) -> list[_Row]:
    # CursorPagination reads the source through the three queryset operations it implements.
    page = view.paginate_queryset(cast(QuerySet, source))
    assert page is not None  # both cursor paginations set a page size
    return list(page)


def _raise_for_refusal(call: Callable[[], contracts.SubscriptionRecord]) -> contracts.SubscriptionRecord:
    """Run a subscription write, and answer each refusal the way a serializer's validate() would."""
    try:
        return call()
    except contracts.SubscriptionRequestInvalidError as refusal:
        raise ValidationError(as_serializer_error(ValidationError(refusal.detail)))
    except contracts.SubscriptionPermissionDeniedError as refusal:
        raise exceptions.PermissionDenied(refusal.message)
    except contracts.SubscriptionQuotaExceededError as refusal:
        raise QuotaLimitExceeded(refusal.message)


class SubscriptionSummariesQuerySerializer(serializers.Serializer):
    insight = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Insight ID. Returns summaries from the subscriptions on this insight. Set either insight or dashboard.",
    )
    dashboard = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Dashboard ID. Returns summaries from the subscriptions on this dashboard. Set either dashboard or insight.",
    )

    def validate(self, attrs: dict) -> dict:
        if ("insight" in attrs) == ("dashboard" in attrs):
            raise ValidationError("Set exactly one of insight or dashboard.")
        return attrs


class SubscriptionSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="ID of the delivery that included this summary.")
    subscription = serializers.IntegerField(
        source="subscription_id", read_only=True, help_text="ID of the subscription that generated this summary."
    )
    subscription_title = serializers.CharField(
        allow_null=True,
        read_only=True,
        help_text="Title of the subscription that generated this summary. Null when the subscription has no title.",
    )
    target_type = serializers.CharField(
        read_only=True, help_text="Channel the summary was sent to: email, slack, or teams."
    )
    change_summary = serializers.CharField(
        allow_null=True, read_only=True, help_text="AI-generated summary text included in the delivery."
    )
    period_start = serializers.DateTimeField(
        allow_null=True,
        read_only=True,
        help_text=(
            "Start of the period this summary covers: the time of the previous completed delivery of the same "
            "subscription. Null for the first delivery, which has no earlier data to compare with."
        ),
    )
    created_at = serializers.DateTimeField(
        read_only=True, help_text="When the delivery started. This is also the end of the covered period."
    )


class SubscriptionSummaryCursorPagination(CursorPagination):
    page_size = 20
    ordering = "-created_at"


_SUBSCRIPTION_ID_PARAMETER = OpenApiParameter(
    "id",
    OpenApiTypes.INT,
    OpenApiParameter.PATH,
    description="A unique integer value identifying this subscription.",
)


@extend_schema_view(
    list=extend_schema(
        extensions={"x-product": "subscriptions"},
        parameters=[
            OpenApiParameter(
                name="created_by",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by creator user UUID.",
            ),
            OpenApiParameter(
                name="resource_type",
                type=str,
                enum=["insight", "dashboard", "ai_prompt"],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by subscription resource: insight, dashboard export, or AI report.",
            ),
            OpenApiParameter(
                name="target_type",
                type=str,
                enum=_TARGET_TYPE_VALUES,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by delivery channel: email, Slack, or Microsoft Teams.",
            ),
            OpenApiParameter(
                name="insight",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by insight ID.",
            ),
            OpenApiParameter(
                name="insights",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by a comma-separated list of insight IDs.",
            ),
            OpenApiParameter(
                name="dashboard",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by dashboard ID.",
            ),
            OpenApiParameter(
                name="dashboard_tiles",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter to subscriptions on insights that are tiles of the given dashboard ID.",
            ),
        ],
    ),
    create=extend_schema(
        request=SubscriptionWriteSerializer,
        responses={201: SubscriptionSerializer},
        extensions={"x-product": "subscriptions"},
    ),
    retrieve=extend_schema(parameters=[_SUBSCRIPTION_ID_PARAMETER], extensions={"x-product": "subscriptions"}),
    update=extend_schema(
        parameters=[_SUBSCRIPTION_ID_PARAMETER],
        request=SubscriptionWriteSerializer,
        responses={200: SubscriptionSerializer},
        extensions={"x-product": "subscriptions"},
    ),
    partial_update=extend_schema(
        parameters=[_SUBSCRIPTION_ID_PARAMETER],
        request=SubscriptionWriteSerializer,
        responses={200: SubscriptionSerializer},
        extensions={"x-product": "subscriptions"},
    ),
    destroy=extend_schema(parameters=[_SUBSCRIPTION_ID_PARAMETER], extensions={"x-product": "subscriptions"}),
)
@extend_schema(tags=["subscriptions"], extensions={"x-product": "subscriptions"})
class SubscriptionViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "subscription"
    serializer_class = SubscriptionSerializer
    pagination_class = PrecountedLimitOffsetPagination
    filter_backends = [filters.SearchFilter, StableOrderingFilter]
    ordering_fields = [
        "created_at",
        "next_delivery_date",
        "title",
        "created_by__email",
    ]
    ordering = ["-created_at"]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.action in ("create", "update", "partial_update"):
            return SubscriptionWriteSerializer
        return SubscriptionSerializer

    # Writing an AI prompt subscription also requires query-read access: it runs LLM-generated
    # HogQL and delivers the results, so subscription:write alone could exfiltrate analytics.
    # Two layers gate this off _write_touches_ai_subscription: a required query:read scope keeps a
    # token least-privileged, and the RBAC check in check_permissions enforces actual query access
    # for every write — a scope is only a capability flag, not proof of RBAC (personal keys can
    # carry query:read without it), and session auth has no scopes at all.
    def dangerously_get_required_scopes(self, request: Request, view: APIView) -> list[str] | None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        scopes = [f"{self.scope_object}:write"]
        if self._write_touches_ai_subscription(request, view):
            scopes.append("query:read")
        return scopes

    def check_permissions(self, request: Request) -> None:
        super().check_permissions(request)
        # Enforce query-viewer RBAC for every AI-prompt write, regardless of auth: the query:read
        # scope above gates tokens but does not prove the owner has query access, and session auth
        # bypasses scopes entirely.
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and self._write_touches_ai_subscription(request, self)
            and not self.user_access_control.check_access_level_for_resource("query", "viewer")
        ):
            raise exceptions.PermissionDenied("You need query access to create or deliver AI prompt subscriptions.")

    def _write_touches_ai_subscription(self, request: Request, view: APIView) -> bool:
        if request.data.get("prompt"):  # create (or a body that sets a prompt)
            return True
        # Existing subscription (update / test-delivery): resolve its kind by pk, team-scoped.
        pk = view.kwargs.get("pk")
        return bool(pk) and api.is_ai_prompt_subscription(team_id=self.team_id, subscription_id=pk)

    def get_throttles(self) -> list[BaseThrottle]:
        throttles = super().get_throttles()
        # An update that requests send_test_now enqueues a real email/Slack delivery — the same
        # blast radius as the test-delivery action — so it shares that team-wide throttle.
        data = self.request.data
        if self.action in ("update", "partial_update") and isinstance(data, dict) and data.get("send_test_now"):
            throttles.append(SubscriptionTestDeliveryThrottle())
        return throttles

    def _dashboard_tile_insight_ids(self, value: str) -> tuple[int, ...]:
        # Subscriptions on insights that are live tiles of the given dashboard, resolved server-side
        # so the overview's "Insights" tab never depends on which tiles the client happens to have
        # loaded into memory. Deleted tiles, dashboards and insights do not count, matching the tile
        # set the sibling dashboard-export validation resolves.
        dashboard_id = _parse_int_param(value, "dashboard_tiles")
        # Require view access to the dashboard itself: without it a project member could pass any
        # dashboard ID and enumerate which subscribed insights are tiles on a dashboard they can't see.
        try:
            dashboards_api.viewable_dashboard_id(
                team_id=self.team_id, dashboard_id=dashboard_id, user_access_control=self.user_access_control
            )
        except dashboards_api.DashboardNotFound:
            raise ValidationError({"dashboard_tiles": ["Dashboard not found."]})
        except dashboards_api.DashboardNotViewable:
            raise exceptions.PermissionDenied("You do not have access to this dashboard.")
        return tuple(dashboards_api.live_tile_insight_ids(dashboard_id))

    def _subscription_filters(self) -> contracts.SubscriptionFilters:
        """The query parameters every subscription route narrows by, the list and single rows alike."""
        request_params = self.request.GET.dict()
        insight_ids: tuple[int, ...] | None = None
        any_of_insight_ids: tuple[int, ...] | None = None
        tile_insight_ids: tuple[int, ...] | None = None
        dashboard_id: int | None = None
        deleted: bool | None = False if self.action == "list" and "deleted" not in request_params else None
        for key in request_params:
            if key == "insight":
                # `insight` (single ID) and `insights` (comma-separated IDs) share one parser, so
                # behavior and validation stay identical.
                insight_ids = tuple(_parse_int_list_param(request_params[key], key))
            elif key == "insights":
                any_of_insight_ids = tuple(_parse_int_list_param(request_params[key], key))
            elif key == "dashboard_tiles":
                tile_insight_ids = self._dashboard_tile_insight_ids(request_params[key])
            elif key == "dashboard":
                dashboard_id = _parse_int_param(request_params["dashboard"], "dashboard")
            elif key == "deleted":
                deleted = str_to_bool(request_params["deleted"])
        return contracts.SubscriptionFilters(
            insight_ids=insight_ids,
            any_of_insight_ids=any_of_insight_ids,
            tile_insight_ids=tile_insight_ids,
            dashboard_id=dashboard_id,
            deleted=deleted,
            search_terms=tuple(filters.SearchFilter().get_search_terms(self.request)),
        )

    def _get_subscription(self) -> contracts.SubscriptionRef:
        try:
            subscription = api.get_subscription_ref(
                team_id=self.team_id,
                subscription_id=self.kwargs["pk"],
                filters=self._subscription_filters(),
                viewer=self.user_access_control,
            )
        except contracts.SubscriptionNotFoundError:
            raise Http404("No Subscription matches the given query.")
        except contracts.SubscriptionPermissionDeniedError as denied:
            raise exceptions.PermissionDenied(denied.message)
        self.check_object_permissions(
            self.request,
            ObjectAccessRef(
                resource="subscription",
                id=str(subscription.id),
                team_id=subscription.team_id,
                created_by_id=subscription.created_by_id,
            ),
        )
        return subscription

    def list(self, request: Request, **kwargs: object) -> Response:
        request_params = request.GET.dict()
        created_by = request_params.get("created_by")
        if created_by:
            try:
                uuid.UUID(created_by)
            except ValueError:
                raise ValidationError({"created_by": ["Not a valid UUID."]}) from None
        target_type = request_params.get("target_type")
        if target_type and target_type not in _TARGET_TYPE_VALUES:
            raise ValidationError({"target_type": [f"Must be one of: {', '.join(sorted(_TARGET_TYPE_VALUES))}."]})

        query = contracts.SubscriptionListQuery(
            filters=self._subscription_filters(),
            created_by_uuid=created_by or None,
            resource_type=request_params.get("resource_type"),
            target_type=target_type or None,
            ordering=tuple(StableOrderingFilter().get_ordering(request, None, self) or ()),
            filter_by_object_access=not is_service_auth(request),
            include_all_if_admin=request.GET.get("admin_include_all") == "true",
        )
        paginator = cast(PrecountedLimitOffsetPagination, self.paginator)
        limit = paginator.get_limit(request)
        # A missing or invalid limit falls back to the PAGE_SIZE setting, so there is always one.
        assert limit is not None
        page = api.list_subscriptions(
            team_id=self.team_id,
            query=query,
            viewer=self.user_access_control,
            offset=paginator.get_offset(request),
            limit=limit,
        )
        paginator.set_count(page.count)
        results = self.paginate_queryset(list(page.results))
        return self.get_paginated_response(self.get_serializer(results, many=True).data)

    def retrieve(self, request: Request, **kwargs: object) -> Response:
        subscription = self._get_subscription()
        return Response(
            self.get_serializer(api.get_subscription(team_id=self.team_id, subscription_id=subscription.id)).data
        )

    def create(self, request: Request, **kwargs: object) -> Response:
        serializer = cast(SubscriptionWriteSerializer, self.get_serializer(data=request.data))
        serializer.is_valid(raise_exception=True)
        subscription = _raise_for_refusal(
            lambda: api.create_subscription(
                team=self.team,
                organization=self.organization,
                user=cast(User, request.user),
                viewer=self.user_access_control,
                write=serializer.to_write(),
                analytics_props=get_request_analytics_properties(request),
            )
        )
        return Response(_write_response(subscription, partial=False), status=status.HTTP_201_CREATED)

    def update(self, request: Request, partial: bool = False, **kwargs: object) -> Response:
        subscription = self._get_subscription()
        serializer = cast(SubscriptionWriteSerializer, self.get_serializer(data=request.data, partial=partial))
        serializer.is_valid(raise_exception=True)
        updated = _raise_for_refusal(
            lambda: api.update_subscription(
                team=self.team,
                organization=self.organization,
                user=cast(User, request.user),
                viewer=self.user_access_control,
                subscription_id=subscription.id,
                write=serializer.to_write(),
                partial=partial,
                analytics_props=get_request_analytics_properties(request),
            )
        )
        return Response(_write_response(updated, partial=partial))

    def partial_update(self, request: Request, **kwargs: object) -> Response:
        return self.update(request, partial=True, **kwargs)

    @extend_schema(
        extensions={"x-product": "subscriptions"},
        request=None,
        responses={
            200: OpenApiResponse(
                description=(
                    "Org-wide AI summary quota: count of currently-active summaries and the limit "
                    "for the org's plan tier. `limit` is null when no cap is configured."
                ),
                response={
                    "type": "object",
                    "properties": {
                        "active_count": {"type": "integer"},
                        "limit": {"type": "integer", "nullable": True},
                        "at_limit": {"type": "boolean"},
                    },
                    "required": ["active_count", "limit", "at_limit"],
                },
            )
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="summary_quota",
        required_scopes=["subscription:read"],
    )
    def summary_quota(self, request: Request, **kwargs: object) -> Response:
        return Response(dataclasses.asdict(api.get_summary_quota(self.organization)))

    @extend_schema(
        extensions={"x-product": "subscriptions"},
        summary="List AI summaries for an insight or dashboard",
        description=(
            "Completed deliveries that include an AI summary, across every active subscription on one insight or "
            "dashboard, newest first. Requires viewer access to the insight or dashboard."
        ),
        parameters=[SubscriptionSummariesQuerySerializer],
        responses={200: SubscriptionSummarySerializer(many=True)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="summaries",
        required_scopes=["subscription:read"],
        pagination_class=SubscriptionSummaryCursorPagination,
        filter_backends=[],
    )
    def summaries(self, request: Request, **kwargs: object) -> Response:
        query = SubscriptionSummariesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        insight_id: int | None = None
        dashboard_id: int | None = None
        if "insight" in query.validated_data:
            try:
                insight_id = api.viewable_live_insight_id(
                    team_id=self.team_id, insight_id=query.validated_data["insight"], viewer=self.user_access_control
                )
            except contracts.SubscriptionNotFoundError:
                raise exceptions.NotFound()
            except contracts.SubscriptionPermissionDeniedError as denied:
                raise exceptions.PermissionDenied(denied.message)
        else:
            try:
                dashboard_id = dashboards_api.viewable_dashboard_id(
                    team_id=self.team_id,
                    dashboard_id=query.validated_data["dashboard"],
                    user_access_control=self.user_access_control,
                )
            except dashboards_api.DashboardNotFound:
                raise Http404("No Dashboard matches the given query.")
            except dashboards_api.DashboardNotViewable:
                raise exceptions.PermissionDenied("You do not have access to this resource.")

        page = _paginate_by_created_at(
            self,
            _CreatedAtCursorSource(
                lambda window: api.list_subscription_summaries(
                    team_id=self.team_id,
                    insight_id=insight_id,
                    dashboard_id=dashboard_id,
                    viewer=self.user_access_control,
                    window=window,
                )
            ),
        )
        return self.get_paginated_response(SubscriptionSummarySerializer(page, many=True).data)

    @extend_schema(
        extensions={"x-product": "subscriptions"},
        parameters=[_SUBSCRIPTION_ID_PARAMETER],
        request=None,
        responses={202: OpenApiResponse(description="Test delivery workflow started")},
    )
    # nosemgrep: api-path-underscore -- shipped public API path, a rename breaks clients
    @action(
        methods=["POST"],
        detail=True,
        url_path="test-delivery",
        throttle_classes=[SubscriptionTestDeliveryThrottle],
        # Scope is resolved dynamically in dangerously_get_required_scopes so AI subscriptions
        # also require query:read (test-delivery runs the AI HogQL pipeline). A static
        # required_scopes here would short-circuit that check.
    )
    def test_delivery(self, request: Request, **kwargs: object) -> Response:
        subscription = self._get_subscription()
        if subscription.deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not subscription.enabled:
            return Response(
                {"detail": "Subscription is disabled. Re-enable it before sending a test delivery."},
                status=status.HTTP_409_CONFLICT,
            )

        result = api.start_test_delivery(team_id=self.team_id, subscription_id=subscription.id)
        if result.outcome == contracts.ManualDeliveryOutcome.ALREADY_RUNNING:
            return Response(
                {"detail": "Delivery already in progress"},
                status=status.HTTP_409_CONFLICT,
            )
        if result.outcome == contracts.ManualDeliveryOutcome.FAILED:
            return Response(
                {"detail": "Failed to schedule delivery"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        posthoganalytics.capture(
            distinct_id=str(cast(User, request.user).distinct_id),
            event="subscription_test_delivery_scheduled",
            properties={
                **get_request_analytics_properties(request),
                "subscription_id": subscription.id,
                "team_id": subscription.team_id,
                "target_type": subscription.target_type,
                "insight_id": subscription.insight_id,
                "dashboard_id": subscription.dashboard_id,
                "temporal_workflow_id": result.workflow_id,
            },
            groups=groups(None, self.team),
        )

        return Response(status=status.HTTP_202_ACCEPTED)


class AIReportChartSerializer(serializers.Serializer):
    export_asset_id = serializers.IntegerField(help_text="Id of the rendered PNG export backing this chart.")
    title = serializers.CharField(help_text="Chart caption, taken from the plan step it illustrates.")
    step_index = serializers.IntegerField(help_text="Index of the plan step this chart came from.")


class AIReportQueryDiagnosticSerializer(serializers.Serializer):
    # Per-step query diagnostics persisted alongside the report markdown. Query-derived (the generated
    # HogQL is here), so it is scrubbed for callers without query access — never shipped to recipients.
    description = serializers.CharField(help_text="What this query step was meant to compute.")
    hogql = serializers.CharField(help_text="The HogQL the assistant generated for this step.")
    ok = serializers.BooleanField(help_text="Whether the query ran successfully.")
    error_type = serializers.CharField(
        allow_null=True, help_text="Exception class name when the query failed; null on success."
    )
    error_code = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Stable query API error code when available; null on success and for unclassified errors.",
    )
    human_readable_error = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Human-readable failure reason, present only for query errors safe to surface to the "
        "subscription owner (e.g. an unresolved field name); null on success and for internal errors, "
        "which expose error_type only.",
    )


class SubscriptionDeliverySerializer(serializers.Serializer):
    AI_REPORT_SCRUBBED_ERROR = {
        "type": AI_REPORT_QUERY_FAILURE_TYPE,
        "message": "The report could not be computed.",
    }
    # Delivery fields that embed the query-derived AI report, mapped to the value each returns when
    # scrubbed for a caller without query access (content_snapshot is a non-null object, the rest
    # nullable). Single source of truth — keep in sync when adding AI-derived delivery fields.
    # ai_report_prompt is user-authored (not query-derived) and already readable on the parent
    # subscription, so it is intentionally not scrubbed.
    # ai_query_plan_status is harmless execution metadata, so it also stays visible without query access.
    # recipient_results is also intentionally not scrubbed: its human_readable_error values are
    # audience-independent delivery failure reasons (auto-disable causes, prompt rejections, Slack
    # thread-failure counts) that carry no query-derived data. New producers of
    # recipient_results[].human_readable_error must keep that invariant — never route a
    # query/executor-derived message through it, since query-restricted viewers can read it.
    AI_REPORT_SCRUBBED: ClassVar[dict[str, object | None]] = {
        "content_snapshot": {},
        "change_summary": None,
        "ai_report": None,
        "ai_report_diagnostics": None,
        "ai_report_charts": None,
    }

    id = serializers.UUIDField(read_only=True, help_text="Primary key for this delivery row.")
    subscription = serializers.IntegerField(
        source="subscription_id", read_only=True, help_text="Parent subscription id."
    )
    temporal_workflow_id = serializers.CharField(
        read_only=True, help_text="Temporal workflow id for this delivery run."
    )
    idempotency_key = serializers.CharField(
        read_only=True, help_text="Dedupes activity retries for the same logical run."
    )
    trigger_type = serializers.CharField(
        read_only=True, help_text="Why the run started (e.g. scheduled, manual, subscription update)."
    )
    scheduled_at = serializers.DateTimeField(
        allow_null=True, read_only=True, help_text="Planned send time when applicable."
    )
    target_type = serializers.CharField(
        read_only=True, help_text="Channel snapshot at send time: email, slack, or teams."
    )
    target_value = serializers.CharField(
        read_only=True,
        help_text=(
            "Destination snapshot at send time: the email list, the Slack channel id, or the "
            "host of the Microsoft Teams webhook. The webhook URL itself is never returned."
        ),
    )
    exported_asset_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=-2147483648, max_value=2147483647),
        allow_empty=False,
        read_only=True,
        help_text="ExportedAsset ids generated for this send.",
    )
    content_snapshot = serializers.JSONField(
        read_only=True,
        help_text=(
            "Snapshot at send time: dashboard metadata, total_insight_count, and per-exported-insight "
            "entries (id, short_id, name, query_hash, cache_key, query_results, optional query_error)."
        ),
    )
    recipient_results = serializers.JSONField(
        read_only=True, help_text="Per-destination outcomes; items use status success, failed, or partial."
    )
    status = serializers.ChoiceField(
        choices=DELIVERY_STATUS_CHOICES,
        read_only=True,
        help_text="Overall run status: starting, completed, failed, or skipped.",
    )
    error = serializers.JSONField(
        allow_null=True, read_only=True, help_text="Top-level failure payload when status is failed, if any."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the delivery row was created.")
    last_updated_at = serializers.DateTimeField(read_only=True, help_text="Last ORM update to this row.")
    finished_at = serializers.DateTimeField(
        allow_null=True, read_only=True, help_text="When the run finished, if applicable."
    )
    change_summary = serializers.CharField(
        allow_null=True,
        read_only=True,
        help_text="AI-generated summary included in this delivery, when one was produced.",
    )
    ai_report = serializers.SerializerMethodField(
        help_text="AI-generated report markdown delivered by this run. Null for non-AI deliveries or runs without a persisted report."
    )
    ai_report_diagnostics = serializers.SerializerMethodField(
        help_text="Per-step query diagnostics (generated HogQL + failure type) for this report. Null for non-AI deliveries or runs without persisted diagnostics."
    )
    ai_report_charts = serializers.SerializerMethodField(
        help_text="Charts rendered for this report, in the order they were delivered. Empty when the report had no charts. Null for non-AI deliveries and for deliveries recorded before charts existed."
    )
    ai_report_prompt = serializers.SerializerMethodField(
        help_text="The subscription's prompt as it was when this report was generated. Null for older deliveries and non-AI deliveries."
    )
    ai_query_plan_status = serializers.SerializerMethodField(
        help_text=(
            "Query plan state recorded for this delivery: frozen, not_frozen, or planner_updated. "
            "Null for older deliveries and non-AI deliveries."
        )
    )

    def _content_snapshot_text(self, delivery: contracts.SubscriptionDeliveryRecord, key: str) -> Optional[str]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get(key)
        return value if isinstance(value, str) and value else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_ai_report(self, delivery: contracts.SubscriptionDeliveryRecord) -> Optional[str]:
        return self._content_snapshot_text(delivery, AI_REPORT_SNAPSHOT_KEY)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_ai_report_prompt(self, delivery: contracts.SubscriptionDeliveryRecord) -> Optional[str]:
        return self._content_snapshot_text(delivery, AI_REPORT_PROMPT_SNAPSHOT_KEY)

    @extend_schema_field(AIReportQueryDiagnosticSerializer(many=True, allow_null=True))
    def get_ai_report_diagnostics(self, delivery: contracts.SubscriptionDeliveryRecord) -> Optional[list[dict]]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        diagnostics = snapshot.get(AI_REPORT_DIAGNOSTICS_KEY)
        return diagnostics if isinstance(diagnostics, list) else None

    @extend_schema_field(AIReportChartSerializer(many=True, allow_null=True))
    def get_ai_report_charts(self, delivery: contracts.SubscriptionDeliveryRecord) -> Optional[list[dict]]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        charts = snapshot.get(AI_REPORT_CHARTS_KEY)
        return charts if isinstance(charts, list) else None

    @extend_schema_field(serializers.ChoiceField(choices=AI_QUERY_PLAN_STATUS_CHOICES, allow_null=True))
    def get_ai_query_plan_status(self, delivery: contracts.SubscriptionDeliveryRecord) -> Optional[str]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        status = snapshot.get(AI_REPORT_QUERY_PLAN_STATUS_KEY)
        return status if isinstance(status, str) and status in _AI_QUERY_PLAN_STATUS_VALUES else None

    def to_representation(self, instance: contracts.SubscriptionDeliveryRecord) -> dict:
        data = super().to_representation(instance)
        # The viewset sets this flag when an AI prompt delivery is read by a caller without query
        # access; scrub the query-derived report so subscription:read (or a self-granted query:read
        # scope) can't read analytics the user isn't allowed to run themselves. ai_report_prompt is
        # user-authored and already readable on the subscription, so it is deliberately not scrubbed.
        if self.context.get("hide_ai_report"):
            data.update(self.AI_REPORT_SCRUBBED)
            if isinstance(data.get("error"), dict) and data["error"].get("type") == AI_REPORT_QUERY_FAILURE_TYPE:
                data["error"] = self.AI_REPORT_SCRUBBED_ERROR
            return data
        # The AI report now ships via the typed ai_report / ai_report_diagnostics / ai_report_prompt
        # fields, so drop the same keys from content_snapshot to avoid shipping the report twice.
        # The non-AI scaffold (insights, dashboard, total_insight_count) stays intact.
        snapshot = data.get("content_snapshot")
        if isinstance(snapshot, dict) and (
            AI_REPORT_SNAPSHOT_KEY in snapshot
            or AI_REPORT_PROMPT_SNAPSHOT_KEY in snapshot
            or AI_REPORT_DIAGNOSTICS_KEY in snapshot
            or AI_REPORT_CHARTS_KEY in snapshot
            or AI_REPORT_QUERY_PLAN_STATUS_KEY in snapshot
        ):
            data["content_snapshot"] = {
                key: value
                for key, value in snapshot.items()
                if key
                not in (
                    AI_REPORT_SNAPSHOT_KEY,
                    AI_REPORT_PROMPT_SNAPSHOT_KEY,
                    AI_REPORT_DIAGNOSTICS_KEY,
                    AI_REPORT_CHARTS_KEY,
                    AI_REPORT_QUERY_PLAN_STATUS_KEY,
                )
            }
        return data


class SubscriptionDeliveryCursorPagination(CursorPagination):
    page_size = 50
    ordering = "-created_at"


_PARENT_SUBSCRIPTION_ID_PARAMETER = OpenApiParameter("subscription_id", OpenApiTypes.INT, OpenApiParameter.PATH)


@extend_schema_view(
    list=extend_schema(
        extensions={"x-product": "subscriptions"},
        summary="List subscription deliveries",
        description="Paginated delivery history for a subscription. Requires premium subscriptions.",
        parameters=[
            _PARENT_SUBSCRIPTION_ID_PARAMETER,
            OpenApiParameter(
                name="status",
                type=str,
                enum=_DELIVERY_STATUS_VALUES,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Return only deliveries in this run status (starting, completed, failed, or skipped).",
            ),
        ],
        responses={200: OpenApiResponse(response=SubscriptionDeliverySerializer(many=True))},
    ),
    retrieve=extend_schema(
        extensions={"x-product": "subscriptions"},
        summary="Retrieve subscription delivery",
        description="Fetch one delivery row by id.",
        parameters=[
            _PARENT_SUBSCRIPTION_ID_PARAMETER,
            OpenApiParameter(
                "id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="A UUID string identifying this subscription delivery.",
            ),
        ],
        responses={200: SubscriptionDeliverySerializer},
    ),
)
@extend_schema(tags=["subscriptions"], extensions={"x-product": "subscriptions"})
class SubscriptionDeliveryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "subscription"
    serializer_class = SubscriptionDeliverySerializer
    pagination_class = SubscriptionDeliveryCursorPagination

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["hide_ai_report"] = self._should_hide_ai_report()
        return context

    def _should_hide_ai_report(self) -> bool:
        # An AI prompt subscription's delivered report is query-derived, so reading it requires query
        # access — mirroring the create/test-delivery gate. Non-AI deliveries are unaffected.
        subscription_id = self.kwargs.get("parent_lookup_subscription_id")
        if not subscription_id:
            return True  # nested route always supplies this; fail closed (scrub) if it ever doesn't
        if not api.is_ai_prompt_subscription(team_id=self.team_id, subscription_id=subscription_id):
            return False
        return not self.user_access_control.check_access_level_for_resource("query", "viewer")

    def list(self, request: Request, **kwargs: object) -> Response:
        status_param = request.query_params.get("status")
        if status_param and status_param not in _DELIVERY_STATUS_VALUES:
            raise ValidationError(
                {"status": [f"Must be one of: {', '.join(sorted(_DELIVERY_STATUS_VALUES))}."]},
            )
        page = _paginate_by_created_at(
            self,
            _CreatedAtCursorSource(
                lambda window: api.list_subscription_deliveries(
                    team_id=self.team_id,
                    subscription_id=self.kwargs.get("parent_lookup_subscription_id"),
                    status=status_param or None,
                    viewer=self.user_access_control,
                    window=window,
                    filter_by_object_access=not is_service_auth(request),
                    include_all_if_admin=request.GET.get("admin_include_all") == "true",
                )
            ),
        )
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request: Request, **kwargs: object) -> Response:
        try:
            delivery = api.get_subscription_delivery(
                team_id=self.team_id,
                subscription_id=self.kwargs.get("parent_lookup_subscription_id"),
                delivery_id=self.kwargs["pk"],
                viewer=self.user_access_control,
            )
        except contracts.MalformedIdError:
            raise Http404
        except contracts.SubscriptionNotFoundError:
            raise Http404("No SubscriptionDelivery matches the given query.")
        # A delivery has no access rules of its own, so the object checks pass it as they pass the row.
        self.check_object_permissions(request, delivery)
        return Response(self.get_serializer(delivery).data)
