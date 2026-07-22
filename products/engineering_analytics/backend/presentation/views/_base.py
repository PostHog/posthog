"""Shared OpenAPI parameter vocabulary, query-param helpers, and the viewset base."""

from datetime import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.engineering_analytics.backend.facade.contracts import (
    ENGINEERING_ANALYTICS_FEATURE_FLAG,
    GitHubSourceNotConnectedError,
    QuarantineWriteError,
    WorkflowHealthRunScope,
)

ENGINEERING_ANALYTICS_TAG = "engineering_analytics"

_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window start: relative ('-30d', '-8w') or ISO8601. Defaults to -30d.",
)

# Workflow health defaults to a tighter window than the PR list (a CI-health "now" view), so it
# advertises its own default rather than reusing _DATE_FROM's -30d.
_WORKFLOW_DATE_FROM = OpenApiParameter(
    name="date_from",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window start: relative ('-24h', '-7d') or ISO8601. Defaults to -24h.",
)

_DATE_TO = OpenApiParameter(
    name="date_to",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Window end: relative or ISO8601. Defaults to now.",
)

_BRANCH = OpenApiParameter(
    name="branch",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Optional exact git branch (head_branch) to scope results to, e.g. 'main'. "
    "Omit or leave blank to aggregate across all branches.",
)

_RUN_SCOPE = OpenApiParameter(
    name="run_scope",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    enum=[scope.value for scope in WorkflowHealthRunScope],
    description="Run scope for workflow health: 'all' (default) includes every run; 'pull_request' includes runs "
    "attributed to pull requests, excluding default-branch (master/main) runs. Fork PRs carry no PR attribution "
    "(a GitHub limitation), so 'pull_request' covers same-repo PRs only. Any other value is a 400.",
)

_SOURCE_ID = OpenApiParameter(
    name="source_id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.QUERY,
    required=False,
    description="Connected GitHub data warehouse source to read from. Defaults to the oldest connected GitHub "
    "source when the team has more than one.",
)

_REPO = OpenApiParameter(
    name="repo",
    type=OpenApiTypes.STR,
    location=OpenApiParameter.QUERY,
    required=False,
    description="'owner/name' repository to scope to when the selected source syncs several repositories "
    "(from the `sources` list). Defaults to the source's first repository.",
)


def _bad_request(exc: ValueError, *, fallback: str) -> Response:
    return Response({"detail": str(exc) or fallback}, status=status.HTTP_400_BAD_REQUEST)


def _require_int_param(request: Request, name: str) -> int:
    """Required integer query param; raises ValueError (handled by `_bad_request`) when missing or non-int."""
    raw = request.query_params.get(name)
    if raw is None:
        raise ValueError(f"{name} is required")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _optional_int_param(request: Request, name: str) -> int | None:
    """Optional integer query param; None when absent/blank, ValueError when present but non-int."""
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _optional_datetime_param(request: Request, name: str) -> datetime | None:
    """Optional ISO8601 datetime query param; None when absent/blank, ValueError when present but unparseable."""
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return serializers.DateTimeField().to_internal_value(raw)
    except serializers.ValidationError:
        raise ValueError(f"{name} must be an ISO8601 datetime") from None


def _bool_param(request: Request, name: str, *, default: bool) -> bool:
    """Optional boolean query param; the default when absent/blank, ValueError when present but not true/false."""
    raw = request.query_params.get(name)
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ValueError(f"{name} must be true or false")


class EngineeringAnalyticsViewSetBase(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Shared config and error degradation for every engineering_analytics action mixin."""

    scope_object = "engineering_analytics"
    # Same rollout flag as the UI scene and the MCP tools, so the product is gated end to end.
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = ENGINEERING_ANALYTICS_FEATURE_FLAG

    def handle_exception(self, exc: Exception) -> Response:
        # No GitHub warehouse source connected: every read action degrades the same way.
        if isinstance(exc, GitHubSourceNotConnectedError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # A quarantine write that can't proceed (App not installed, malformed file, GitHub
        # failure): the message is user-safe and explains what to fix.
        if isinstance(exc, QuarantineWriteError):
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)
