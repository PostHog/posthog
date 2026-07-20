import hmac
import logging

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.review_hog.backend.temporal.client import start_resolution_workflow, start_review_pr_workflow
from products.review_hog.backend.temporal.types import TRIGGER_LABEL

logger = logging.getLogger(__name__)

# v1 scope: ReviewHog only runs against the main PostHog monorepo. Matched case-insensitively.
ALLOWED_REPOS = {"posthog/posthog"}


class ReviewHogTriggerRequestSerializer(serializers.Serializer):
    repo = serializers.CharField(
        help_text="GitHub repository to review, in 'owner/name' form; must be on the allowlist (e.g. 'PostHog/posthog').",
    )
    pr_number = serializers.IntegerField(
        min_value=1,
        help_text="Pull request number to review.",
    )
    publish = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to post the review back to the PR. Defaults true (the label trigger publishes).",
    )


class ReviewHogResolveRequestSerializer(serializers.Serializer):
    repo = serializers.CharField(
        help_text="GitHub repository, in 'owner/name' form; must be on the allowlist (e.g. 'PostHog/posthog').",
    )
    pr_number = serializers.IntegerField(
        min_value=1,
        help_text="Pull request whose unresolved review threads to settle.",
    )


class ReviewHogTriggerResponseSerializer(serializers.Serializer):
    workflow_id = serializers.CharField(help_text="Temporal workflow id for the started review run.")
    status = serializers.CharField(help_text="Run lifecycle marker; 'started' when the review was queued.")


class ReviewHogTriggerErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Human-readable explanation of why the trigger was rejected.")


def _bearer_token(request: Request) -> str:
    """Extract the bearer token from the Authorization header (accepts a bare token too)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    return auth.strip()


def _resolve_run_user_id(team_id: int) -> int | None:
    """The user the sandbox tasks run as: the GitHub integration creator if still an active org
    member, else the oldest active org member (same semantics as signals' resolve_user_id_for_team).

    A disabled run user is worse than none: every user-scoped sandbox credential 403s and the agent
    hangs silently until the poll budget expires, so never return an inactive user here.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    integration = Integration.objects.filter(team_id=team_id, kind="github").order_by("id").first()
    if integration is not None and integration.created_by_id:
        creator_is_active = OrganizationMembership.objects.filter(
            organization=team.organization,
            user_id=integration.created_by_id,
            user__is_active=True,
        ).exists()
        if creator_is_active:
            return integration.created_by_id
        logger.warning(
            "ReviewHog run-user fallback: integration creator %s is not an active org member",
            integration.created_by_id,
        )
    membership = (
        OrganizationMembership.objects.select_related("user")
        .filter(organization=team.organization, user__is_active=True)
        .order_by("id")
        .first()
    )
    return membership.user_id if membership else None


class ReviewHogTriggerViewSet(viewsets.ViewSet):
    """Shared-secret-gated triggers that start ReviewHog runs for a PR: `trigger` (a review, which
    can chain the resolution stage) and `resolve` (a standalone resolution run).

    Unscoped (no team in the URL): the team and run user are resolved server-side from settings, and CI
    authenticates with the `REVIEWHOG_TRIGGER_TOKEN` shared secret — no session or API key. The first
    client is the `reviewhog` label GitHub Action, but the endpoint is the durable reusable interface.
    """

    authentication_classes = ()
    permission_classes = ()

    def _authenticate(self, request: Request) -> Response | None:
        """Return an error Response if the shared-secret check fails, else None."""
        expected = settings.REVIEWHOG_TRIGGER_TOKEN
        if not expected:
            # Fail closed in real deployments; allow locally so the endpoint is testable without a secret.
            if settings.DEBUG or settings.TEST:
                return None
            return Response(
                {"error": "ReviewHog trigger token is not configured"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not hmac.compare_digest(_bearer_token(request), expected):
            return Response({"error": "Invalid trigger token"}, status=status.HTTP_403_FORBIDDEN)
        return None

    def _run_gates(self, repo: str) -> tuple[int, int] | Response:
        """The shared trigger gates: repo allowlist → configured team → authorized run user.

        Returns `(team_id, user_id)` when every gate passes, else the error `Response` to return.
        (Shared-secret auth runs before body validation in each action, so it is not part of this.)
        """
        if repo.lower() not in ALLOWED_REPOS:
            return Response({"error": f"Repository {repo} is not allowed"}, status=status.HTTP_403_FORBIDDEN)

        # First configured team = the one label-triggered runs execute and publish under.
        team_id = settings.REVIEWHOG_TEAM_IDS[0] if settings.REVIEWHOG_TEAM_IDS else None
        if not team_id:
            return Response({"error": "ReviewHog team is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        user_id = settings.REVIEWHOG_RUN_USER_ID or _resolve_run_user_id(team_id)
        if not user_id:
            return Response(
                {"error": "No active run user found for the team (no GitHub integration creator or org member)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Fail loud here rather than silently downstream: sandbox credentials are authorized against
        # active org membership, so an unauthorized run user hangs the review until its poll budget expires.
        run_user_is_authorized = OrganizationMembership.objects.filter(
            organization__team__id=team_id,
            user_id=user_id,
            user__is_active=True,
        ).exists()
        if not run_user_is_authorized:
            # The Action echoes error bodies into public CI logs, so the id stays server-side.
            logger.warning("ReviewHog trigger: run user %s is not an active member of the team's organization", user_id)
            return Response(
                {"error": "Configured run user is not an active member of the team's organization"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return team_id, user_id

    @extend_schema(
        request=ReviewHogTriggerRequestSerializer,
        responses={
            202: OpenApiResponse(response=ReviewHogTriggerResponseSerializer, description="Review run started"),
            400: OpenApiResponse(
                response=ReviewHogTriggerErrorSerializer, description="Invalid body or unresolved run user"
            ),
            403: OpenApiResponse(
                response=ReviewHogTriggerErrorSerializer, description="Missing/invalid token or disallowed repo"
            ),
            503: OpenApiResponse(response=ReviewHogTriggerErrorSerializer, description="Trigger team not configured"),
        },
        summary="Trigger a ReviewHog PR review",
        description=(
            "Start a single-turn ReviewHog review for a pull request and (by default) publish it back to "
            "the PR. A published review chains into the resolution stage when the PR author's "
            "resolve_comments setting is on (the default). Authenticated with the REVIEWHOG_TRIGGER_TOKEN "
            "shared secret in the Authorization header. Non-blocking: returns the Temporal workflow id "
            "immediately while the review runs in the worker."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="trigger")
    def trigger(self, request: Request) -> Response:
        auth_error = self._authenticate(request)
        if auth_error is not None:
            return auth_error

        serializer = ReviewHogTriggerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo: str = serializer.validated_data["repo"]
        pr_number: int = serializer.validated_data["pr_number"]
        publish: bool = serializer.validated_data["publish"]

        gates = self._run_gates(repo)
        if isinstance(gates, Response):
            return gates
        team_id, user_id = gates

        # Forks are rejected server-side in the workflow's fetch activity (and by the Action gate); the
        # endpoint stays free of GitHub I/O and returns immediately. Reviewing includes resolving:
        # whether the run chains the resolution stage is the PR author's `resolve_comments` setting
        # (default on), not a caller flag.
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        workflow_id = start_review_pr_workflow(
            pr_url=pr_url,
            team_id=team_id,
            user_id=user_id,
            publish=publish,
            trigger_source=TRIGGER_LABEL,
        )
        logger.info(f"ReviewHog trigger started workflow {workflow_id} for {repo}#{pr_number} (publish={publish})")
        return Response(
            ReviewHogTriggerResponseSerializer({"workflow_id": workflow_id, "status": "started"}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=ReviewHogResolveRequestSerializer,
        responses={
            202: OpenApiResponse(response=ReviewHogTriggerResponseSerializer, description="Resolution run started"),
            400: OpenApiResponse(
                response=ReviewHogTriggerErrorSerializer, description="Invalid body or unresolved run user"
            ),
            403: OpenApiResponse(
                response=ReviewHogTriggerErrorSerializer, description="Missing/invalid token or disallowed repo"
            ),
            503: OpenApiResponse(response=ReviewHogTriggerErrorSerializer, description="Trigger team not configured"),
        },
        summary="Trigger the ReviewHog resolution stage on a PR",
        description=(
            "Start a standalone resolution run for a pull request: triage every unresolved review thread "
            "(human- or bot-authored), implement the worth-and-safe asks directly on the PR branch, reply "
            "on each thread, and resolve settled bot threads. Works on PRs that never had a ReviewHog "
            "review. Same shared-secret auth as the review trigger; non-blocking."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="resolve")
    def resolve(self, request: Request) -> Response:
        auth_error = self._authenticate(request)
        if auth_error is not None:
            return auth_error

        serializer = ReviewHogResolveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo: str = serializer.validated_data["repo"]
        pr_number: int = serializer.validated_data["pr_number"]

        gates = self._run_gates(repo)
        if isinstance(gates, Response):
            return gates
        team_id, user_id = gates

        # Fork/closed gates run server-side in the workflow's prepare step (they need GitHub I/O).
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        workflow_id = start_resolution_workflow(
            pr_url=pr_url, team_id=team_id, user_id=user_id, trigger_source=TRIGGER_LABEL
        )
        logger.info(f"ReviewHog resolve trigger started workflow {workflow_id} for {repo}#{pr_number}")
        return Response(
            ReviewHogTriggerResponseSerializer({"workflow_id": workflow_id, "status": "started"}).data,
            status=status.HTTP_202_ACCEPTED,
        )
