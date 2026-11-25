from dataclasses import asdict

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import APIScopePermission, is_service_auth

from products.signals.backend.facade import api as signals_facade

# Built from `BriefingReportRelation`, so the API enum cannot drift from the relations the inbox derives.
InboxDigestRelation = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "InboxDigestRelation", [(relation.name, relation.value) for relation in signals_facade.BriefingReportRelation]
)


class InboxDigestQuerySerializer(serializers.Serializer):
    since = serializers.DateTimeField(
        required=False,
        help_text=(
            "ISO 8601 datetime. `new_for_you` and `outcomes` count from this time. Defaults to one day before the "
            "request. A time more than 30 days back counts from 30 days back."
        ),
    )


class InboxDigestReportSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The report id. Pass it to inbox-reports-retrieve for the full report.")
    title = serializers.CharField(allow_null=True, help_text="The report title.")
    priority = serializers.ChoiceField(
        choices=signals_facade.REPORT_PRIORITY_CHOICES,
        allow_null=True,
        help_text="The report priority, P0 to P4, or null when it has none.",
    )
    status = serializers.ChoiceField(
        choices=signals_facade.REPORT_STATUS_CHOICES,
        help_text="The report status: `ready`, or `pending_input` when the report waits on a person's input.",
    )
    relation = serializers.ChoiceField(
        choices=InboxDigestRelation.choices,
        help_text=(
            "How the report relates to you, strongest first: `waiting_for_you` (it names you and waits on input), "
            "`claimed` (you claimed it), `suggested_reviewer` (it names you as a suggested reviewer)."
        ),
    )
    summary_lead = serializers.CharField(
        help_text="The opening of the report summary as plain text, at most 200 characters."
    )
    implementation_pr_url = serializers.URLField(
        allow_null=True, help_text="The report's implementation pull request, or null when it has none."
    )
    implementation_pr_state = serializers.ChoiceField(
        choices=signals_facade.IMPLEMENTATION_PR_STATE_CHOICES,
        allow_null=True,
        help_text="The state of the implementation pull request, or null when it has none or its state is unknown.",
    )
    url = serializers.URLField(help_text="The report in the PostHog inbox.")


class InboxDigestSectionSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="How many reports the section holds.")
    reports = InboxDigestReportSerializer(
        many=True, help_text="At most 3 of the reports, in the inbox's priority order."
    )


class InboxDigestMonitoringOutcomeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=signals_facade.MONITORING_OUTCOME_CHOICES,
        help_text=(
            "How Monitoring ended. `resolved`: every check passed. `resolved_by_assessment`: a report-level "
            "assessment established the fix worked. `resolved_manually`: a person resolved it. `resolved_unverified`: "
            "every check was cancelled. `closed`: the fix was not shown to work."
        ),
    )
    count = serializers.IntegerField(help_text="How many Monitoring periods ended this way.")


class InboxDigestOutcomesSerializer(serializers.Serializer):
    pull_requests_opened = serializers.IntegerField(
        help_text=(
            "Pull requests linked to your reports since `since`, counted by the time PostHog first linked each one to "
            "a report, not the time GitHub opened it."
        )
    )
    pull_requests_merged = serializers.IntegerField(
        help_text="Pull requests linked to your reports that GitHub merged since `since`."
    )
    monitoring_periods_ended = InboxDigestMonitoringOutcomeSerializer(
        many=True,
        allow_null=True,
        help_text=(
            "Monitoring periods of your reports that ended since `since`, one entry per outcome that occurred. Null "
            "when the organization does not have Monitoring."
        ),
    )


class InboxDigestProjectSerializer(serializers.Serializer):
    actionable_unclaimed_count = serializers.IntegerField(
        help_text=(
            "Reports in the whole project that are actionable now and that nobody claimed: the reports "
            "inbox-reports-list returns for `view=actionable` with `unclaimed=true`."
        )
    )


@extend_schema_serializer(many=False)
class InboxDigestSerializer(serializers.Serializer):
    since = serializers.DateTimeField(help_text="The start of the window that `new_for_you` and `outcomes` count.")
    generated_at = serializers.DateTimeField(help_text="When the digest was read.")
    needs_you = InboxDigestSectionSerializer(
        help_text=(
            "Your open reports now, whatever `since` is: the reports that wait on your input, that you claimed, or "
            "that name you as a suggested reviewer."
        )
    )
    new_for_you = InboxDigestSectionSerializer(
        help_text=(
            "The reports in `needs_you` that first reached the inbox since `since`. A report that reached the inbox "
            "earlier and became yours later, for example when you claimed it, does not count."
        )
    )
    outcomes = InboxDigestOutcomesSerializer(
        help_text=(
            "What happened since `since` to your reports in any status: the reports that name you as a suggested "
            "reviewer, or that you or your agents claimed."
        )
    )
    project = InboxDigestProjectSerializer(
        help_text="The open work in the whole project, for when `needs_you` is empty."
    )


class InboxDigestViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = InboxDigestSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "inbox"
    requires_resource_level_access = True
    pagination_class = None

    @validated_request(
        query_serializer=InboxDigestQuerySerializer,
        responses={
            200: OpenApiResponse(response=InboxDigestSerializer),
            403: OpenApiResponse(description="The credentials do not belong to the person the digest describes."),
        },
        summary="Get your inbox digest",
        description=(
            "What in the inbox needs you now, what is new for you, and what happened to your reports since `since`, "
            "with at most 3 compact reports per section. Only the person the digest describes can read it."
        ),
    )
    def list(self, request: ValidatedRequest, **kwargs: object) -> Response:
        user = request.user
        # A digest describes one person, so only that person's own credentials can read it.
        if is_service_auth(request) or not isinstance(user, User):
            raise PermissionDenied(
                "The inbox digest describes one person. Use that person's own credentials, such as their personal API key."
            )
        authenticator = request.successful_authenticator
        if isinstance(authenticator, OAuthAccessTokenAuthentication) and signals_facade.is_scout_trial_token(
            team_id=self.team_id,
            sandbox_task_id=authenticator.access_token.sandbox_task_id,
            scope=authenticator.access_token.scope,
            token_id=authenticator.access_token.pk,
        ):
            raise PermissionDenied("Private scout trials cannot read the inbox digest.")
        via_mcp = is_mcp_request(request)
        digest = signals_facade.get_inbox_digest(
            team=self.team,
            user=user,
            since=request.validated_query_data.get("since"),
            link_source=signals_facade.ReportLinkSource.MCP if via_mcp else None,
        )
        report_user_action(
            user,
            "inbox digest read",
            properties={
                "via_mcp": via_mcp,
                "lookback_hours": round((digest.generated_at - digest.since).total_seconds() / 3600, 1),
                "needs_you_count": digest.needs_you.count,
                "new_for_you_count": digest.new_for_you.count,
                "pull_requests_opened": digest.outcomes.pull_requests_opened,
                "pull_requests_merged": digest.outcomes.pull_requests_merged,
                "actionable_unclaimed_count": digest.project.actionable_unclaimed_count,
            },
            team=self.team,
            request=request,
        )
        return Response(InboxDigestSerializer(asdict(digest)).data)
