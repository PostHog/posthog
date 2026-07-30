"""Test-health reads plus the quarantine sidecar (the product's one write)."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.facade.contracts import FLAKY_TEST_SIGNAL_CAVEAT, QuarantineRequest
from products.engineering_analytics.backend.presentation.serializers.suite_health import (
    BrokenTestsResultSerializer,
    FlakyTestListSerializer,
    QuarantineFileSerializer,
    QuarantineRequestResultSerializer,
    QuarantineRequestSerializer,
)
from products.engineering_analytics.backend.presentation.views._base import (
    _DATE_TO,
    _REPO,
    _SOURCE_ID,
    EngineeringAnalyticsViewSetBase,
    _bad_request,
    _optional_int_param,
)


class SuiteHealthActionsMixin(EngineeringAnalyticsViewSetBase):
    READ_ACTIONS = ["flaky_tests", "broken_tests", "quarantine"]
    WRITE_ACTIONS = ["quarantine_request"]

    @extend_schema(
        operation_id="engineering_analytics_flaky_tests",
        parameters=[
            OpenApiParameter(
                name="date_from",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Window start: relative ('-7d', '-30d') or ISO8601. Defaults to -7d; the window "
                "may span at most 30 days.",
            ),
            _DATE_TO,
            OpenApiParameter(
                name="min_failed_prs",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="A test with no recorded recovery qualifies once it failed on at least this many "
                "distinct pull requests in the window. Minimum 1. Defaults to 3.",
            ),
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of tests to return (1-200). Defaults to 50.",
            ),
            _SOURCE_ID,
            _REPO,
        ],
        responses={
            200: FlakyTestListSerializer,
            400: OpenApiResponse(
                description="Invalid date, threshold, limit, or source_id, or a window longer than 30 days."
            ),
        },
        description=(
            "The active test-health queue: pytest and Jest tests worth acting on now, from the per-test CI spans, "
            "over a "
            "window (default -7d, maximum 30 days). Evidence is counted per CI run, never per span or run "
            "attempt. A test is a 'confirmed_flake' when one commit both failed and passed it (a 'Re-run failed "
            "jobs' attempt went green, or an in-job retry recovered it); 'quarantined' when a tolerated failure "
            "is recorded while it is masked; otherwise 'suspected_regression'. It qualifies on any same-commit "
            "recovery, any master/main failure, a quarantined failure, or failures on at least min_failed_prs "
            "distinct PRs. " + FLAKY_TEST_SIGNAL_CAVEAT
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def flaky_tests(self, request: Request, **kwargs) -> Response:
        try:
            result = api.list_flaky_tests(
                team=self.team,
                date_from=request.query_params.get("date_from") or None,
                date_to=request.query_params.get("date_to") or None,
                min_failed_prs=_optional_int_param(request, "min_failed_prs"),
                limit=_optional_int_param(request, "limit"),
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid date, threshold, limit, or source_id")
        return Response(FlakyTestListSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_broken_tests",
        parameters=[_SOURCE_ID, _REPO],
        responses={
            200: BrokenTestsResultSerializer,
            400: OpenApiResponse(description="Invalid source_id."),
        },
        description=(
            "The broken-tests triage panel: live CI failures over the last 2 days grouped into distinct "
            "failures (by test id + normalized error signature) and classified by how each is behaving right "
            "now — breaking trunk, a new failure spreading across branches, probably-resolved, flaky, or one "
            "PR's own problem — ranked with the most urgent first. Also returns breaking_master_jobs, the "
            "default-branch jobs whose latest run is red. Reach for this to answer 'what CI failures should I "
            "care about right now'; expand a row's latest_run_id via run_failure_logs for the failing lines. "
            "Fingerprinting is pytest-only for now (jest/playwright/cargo failures aren't grouped yet), and "
            "the breaking/resolved distinction needs the job-level source synced — without it those failures "
            "fall through to flaky/pr_only rather than being misreported."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def broken_tests(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_broken_tests(
                team=self.team,
                source_id=request.query_params.get("source_id") or None,
                repo=request.query_params.get("repo") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid source_id")
        return Response(BrokenTestsResultSerializer(instance=result).data)

    @extend_schema(
        operation_id="engineering_analytics_quarantine",
        summary="Flaky-test quarantine file",
        parameters=[
            OpenApiParameter(
                name="repo",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Optional 'owner/name' repository to read the quarantine file from. Defaults to the "
                "connected GitHub source's most active repo over the last 30 days.",
            ),
            _SOURCE_ID,
        ],
        responses={
            200: QuarantineFileSerializer,
            400: OpenApiResponse(description="Invalid repo or source_id."),
        },
        description=(
            "The repository's checked-in .test_quarantine.json: flaky tests temporarily quarantined with a hard "
            "expiry, classified by urgency (overdue, in grace, expiring soon, active). `available` is false when "
            "the repo has no quarantine file — that is not an error. Parsing is fail-open: malformed entries are "
            "reported in parse_errors while well-formed ones are kept."
        ),
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def quarantine(self, request: Request, **kwargs) -> Response:
        try:
            result = api.get_quarantine(
                team=self.team,
                repo=request.query_params.get("repo") or None,
                source_id=request.query_params.get("source_id") or None,
                user_access_control=self.user_access_control,
            )
        except ValueError as exc:
            return _bad_request(exc, fallback="Invalid repo or source_id")
        return Response(QuarantineFileSerializer(instance=result).data)

    @validated_request(
        request_serializer=QuarantineRequestSerializer,
        operation_id="engineering_analytics_quarantine_request",
        responses={
            201: OpenApiResponse(
                response=QuarantineRequestResultSerializer,
                description="The opened pull request, plus the tracking issue for a new quarantine.",
            ),
            400: OpenApiResponse(
                description="Invalid input, or the write could not be completed (no GitHub App installed on the "
                "repo's org, a malformed quarantine file, or a GitHub failure). The detail message is safe to show."
            ),
        },
        summary="Quarantine, extend, or unquarantine a flaky test",
        description=(
            "Opens a pull request that edits the repository's checked-in .test_quarantine.json — and, for a new "
            "quarantine, a tracking issue the PR links but does not close. The file stays the source of truth that "
            "CI enforces; this never bypasses it. A quarantine only affects CI runs that start after the PR merges."
        ),
    )
    @action(detail=False, methods=["post"], url_path="quarantine/request", pagination_class=None)
    def quarantine_request(self, request: TypedRequest[QuarantineRequest], **kwargs) -> Response:
        result = api.request_quarantine(
            team=self.team,
            request=request.validated_data,
            user_access_control=self.user_access_control,
        )
        return Response(QuarantineRequestResultSerializer(instance=result).data, status=status.HTTP_201_CREATED)
