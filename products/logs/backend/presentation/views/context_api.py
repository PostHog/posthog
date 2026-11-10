from typing import TYPE_CHECKING, Literal

from django.db import models

from rest_framework import exceptions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.permissions import get_authenticator_scopes
from posthog.scopes import scopes_not_covered

from products.logs.backend.facade.queries import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    LogsContextError,
    LogsContextParams,
    LogsContextRunner,
    normalize_trace_id,
    parse_padding,
)
from products.logs.backend.presentation.views.agent_fields import LogsAgentNextCallSerializer, LogsAgentWindowSerializer

if TYPE_CHECKING:
    from posthog.models import Team


class LogsContextInclude(models.TextChoices):
    SPANS = "spans"


class LogsSeverityLevel(models.TextChoices):
    TRACE = "trace", "trace"
    DEBUG = "debug", "debug"
    INFO = "info", "info"
    WARN = "warn", "warn"
    ERROR = "error", "error"
    FATAL = "fatal", "fatal"


class LogsContextAnchorType(models.TextChoices):
    TRACE = "trace"
    LOG = "log"
    ATTRIBUTE = "attribute"


class _LogsContextAttributeAnchorSerializer(serializers.Serializer):
    key = serializers.CharField(help_text='Log attribute key, e.g. "workflow_run_id".')
    value = serializers.CharField(help_text="Exact attribute value to follow.")


class _LogsContextAnchorSerializer(serializers.Serializer):
    logUuid = serializers.CharField(required=False, help_text="uuid of one log line. Needs `timestamp`.")
    timestamp = serializers.DateTimeField(required=False, help_text="ISO 8601 timestamp of the `logUuid` log line.")
    traceId = serializers.CharField(required=False, help_text="Trace id, 32 hex characters or base64.")
    attribute = _LogsContextAttributeAnchorSerializer(
        required=False, help_text="Follow every log with this attribute value."
    )
    around = serializers.DateTimeField(
        required=False,
        help_text="ISO 8601 time hint. Required with `attribute`, used with `traceId` only when the trace has no spans.",
    )

    def validate(self, attrs: dict) -> dict:
        if sum(1 for name in ("logUuid", "traceId", "attribute") if attrs.get(name)) != 1:
            raise serializers.ValidationError("anchor needs exactly one of logUuid, traceId, or attribute.")
        if attrs.get("logUuid") and not attrs.get("timestamp"):
            raise serializers.ValidationError({"timestamp": "anchor.timestamp is required with logUuid."})
        if attrs.get("attribute") and not attrs.get("around"):
            raise serializers.ValidationError({"around": "anchor.around is required with attribute."})
        if attrs.get("traceId"):
            try:
                attrs["traceId"] = normalize_trace_id(attrs["traceId"])
            except ValueError as error:
                raise serializers.ValidationError({"traceId": str(error)})
        return attrs


class _LogsContextBodySerializer(serializers.Serializer):
    anchor = _LogsContextAnchorSerializer(help_text="Exactly one anchor: a log line, a trace, or an attribute value.")
    padding = serializers.CharField(
        required=False,
        help_text='Time on each side of the anchor: "30s", "5m", "1h" (max 6h). Default 30s for a trace, 5m otherwise.',
    )
    severityLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=LogsSeverityLevel.choices),
        required=False,
        default=list,
        help_text="Keep only these severities in the timeline.",
    )
    serviceNames = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
        help_text="Restrict the timeline to these services. Default: the trace's services, the log's service, or all.",
    )
    include = serializers.ListField(
        child=serializers.ChoiceField(choices=LogsContextInclude.choices),
        required=False,
        default=list,
        help_text='"spans" adds spans_summary for a trace anchor.',
    )
    limit = serializers.IntegerField(
        required=False, default=DEFAULT_LIMIT, min_value=1, max_value=MAX_LIMIT, help_text="Maximum timeline rows."
    )
    after = serializers.CharField(required=False, help_text="`next_cursor` of a previous call with the same anchor.")

    def validate_padding(self, value: str) -> str:
        try:
            parse_padding(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error))
        return value


class LogsContextRequestSerializer(serializers.Serializer):
    query = _LogsContextBodySerializer(help_text="The context query.")


class _LogsContextAnchorSummarySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=LogsContextAnchorType.choices, help_text="The anchor kind.")
    trace_id = serializers.CharField(allow_null=True, help_text="Trace id (hex) of the anchor, when there is one.")
    timestamp = serializers.CharField(help_text="Reference time (UTC) that `t_offset_ms` counts from.")
    start = serializers.CharField(allow_null=True, help_text="Trace start or first matching log (UTC).")
    end = serializers.CharField(allow_null=True, help_text="Trace end or last matching log (UTC).")
    duration_ms = serializers.FloatField(allow_null=True, help_text="end - start in milliseconds.")
    services = serializers.ListField(child=serializers.CharField(), help_text="Services of the anchor.")


class _LogsContextCorrelationKeySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Id-like attribute of the anchor log.")
    value = serializers.CharField(help_text="Its value on the anchor log.")
    log_count = serializers.IntegerField(help_text="Logs in the window, any service, with this value.")


class _LogsContextTimelineRowSerializer(serializers.Serializer):
    t_offset_ms = serializers.FloatField(help_text="Milliseconds from the anchor reference time.")
    timestamp = serializers.CharField(help_text="Log timestamp (UTC).")
    service = serializers.CharField(help_text="Service that emitted the line.")
    severity = serializers.CharField(help_text="Severity of the line.")
    body = serializers.CharField(help_text="Log body, cut to 300 characters.")
    attrs = serializers.CharField(help_text="k=v attributes that differ from the anchor log, without noise keys.")
    uuid = serializers.CharField(help_text="Log uuid, usable with `timestamp` as a log anchor.")


class _LogsContextSpanSerializer(serializers.Serializer):
    span_id = serializers.CharField(help_text="Span id (hex).")
    name = serializers.CharField(help_text="Span name.")
    service = serializers.CharField(help_text="Service of the span.")
    start_offset_ms = serializers.FloatField(help_text="Milliseconds from the trace start.")
    duration_ms = serializers.FloatField(help_text="Span duration in milliseconds.")
    self_time_ms = serializers.FloatField(help_text="Duration not covered by child spans.")
    status = serializers.CharField(help_text='"error" or "ok".')


class _LogsContextSpansSummarySerializer(serializers.Serializer):
    span_count = serializers.IntegerField(help_text="Spans read.")
    truncated = serializers.BooleanField(help_text="True when the trace has more spans than were read.")
    services = serializers.ListField(child=serializers.CharField(), help_text="Services with spans in the trace.")
    root = _LogsContextSpanSerializer(allow_null=True, help_text="The root span, null when it never arrived.")
    error_spans = _LogsContextSpanSerializer(many=True, help_text="Up to 10 spans with an error status.")
    slowest = _LogsContextSpanSerializer(many=True, help_text="The 5 longest spans.")


class LogsContextResponseSerializer(serializers.Serializer):
    window = LogsAgentWindowSerializer(help_text="Absolute UTC bounds the logs were read from.")
    anchor = _LogsContextAnchorSummarySerializer(help_text="The resolved anchor.")
    correlation_keys = _LogsContextCorrelationKeySerializer(
        many=True, help_text="Id-like attributes of the anchor log, with counts."
    )
    timeline = _LogsContextTimelineRowSerializer(many=True, help_text="Log lines, earliest first.")
    spans_summary = _LogsContextSpansSummarySerializer(
        allow_null=True, help_text='Set for a trace anchor with include ["spans"].'
    )
    truncated = serializers.BooleanField(help_text="True when more rows exist past `limit`.")
    next_cursor = serializers.CharField(allow_null=True, help_text="Pass as `after` for the next page.")
    next = LogsAgentNextCallSerializer(many=True, help_text="Prefilled follow-up calls.")
    notes = serializers.ListField(child=serializers.CharField(), help_text="Caveats about the window.")


def logs_context_response(team: "Team", request: Request, *, tracing_access: bool) -> Response:
    tag_queries(product=Product.LOGS, feature=Feature.QUERY)
    serializer = LogsContextRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data["query"]
    anchor = data["anchor"]
    kind: Literal["trace", "log", "attribute"] = (
        "trace" if anchor.get("traceId") else "log" if anchor.get("logUuid") else "attribute"
    )
    held = get_authenticator_scopes(request.successful_authenticator)
    scoped = held is None or "*" in held or not scopes_not_covered(held, ["tracing:read"])
    read_spans = tracing_access and scoped
    if LogsContextInclude.SPANS in data["include"] and not read_spans:
        raise exceptions.PermissionDenied('include "spans" needs the tracing:read scope and tracing viewer access.')
    params = LogsContextParams(
        kind=kind,
        trace_id=anchor.get("traceId"),
        log_uuid=anchor.get("logUuid"),
        attribute=(anchor["attribute"]["key"], anchor["attribute"]["value"]) if kind == "attribute" else None,
        time_hint=anchor.get("timestamp") if kind == "log" else anchor.get("around"),
        padding=parse_padding(data["padding"]) if data.get("padding") else None,
        severity_levels=tuple(data["severityLevels"]),
        service_names=tuple(data["serviceNames"]),
        include_spans=LogsContextInclude.SPANS in data["include"],
        read_spans=read_spans,
        limit=data["limit"],
        after=data.get("after"),
    )
    try:
        result = LogsContextRunner(team, params).run()
    except OverflowError:
        raise exceptions.ValidationError("The anchor time is out of range.")
    except LogsContextError as error:
        if error.status == status.HTTP_404_NOT_FOUND:
            raise exceptions.NotFound(str(error))
        raise exceptions.ValidationError(str(error))
    if result["next_cursor"]:
        page = {**request.data["query"], "after": result["next_cursor"]}
        result["next"] = [{"tool": "logs-context", "why": "next page of the timeline", "query": page}, *result["next"]][
            :3
        ]

    analytics = {"anchor_type": kind, "include_spans": params.include_spans, "truncated": result["truncated"]}
    report_user_action(request.user, "logs context queried", analytics, team=team, request=request)
    return Response(result, status=status.HTTP_200_OK)
