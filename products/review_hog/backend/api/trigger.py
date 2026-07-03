import hmac
import logging

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.integration import Integration

from products.review_hog.backend.temporal.client import start_review_pr_workflow
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
    """The user the sandbox tasks run as, falling back to the team's GitHub integration creator."""
    integration = Integration.objects.filter(team_id=team_id, kind="github").order_by("id").first()
    return integration.created_by_id if integration is not None else None


class ReviewHogTriggerViewSet(viewsets.ViewSet):
    """Shared-secret-gated trigger that starts a ReviewHog review for a PR.

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
            "the PR. Authenticated with the REVIEWHOG_TRIGGER_TOKEN shared secret in the Authorization "
            "header. Non-blocking: returns the Temporal workflow id immediately while the review runs in "
            "the worker."
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

        if repo.lower() not in ALLOWED_REPOS:
            return Response({"error": f"Repository {repo} is not allowed"}, status=status.HTTP_403_FORBIDDEN)

        team_id = settings.REVIEWHOG_TEAM_ID
        if not team_id:
            return Response({"error": "ReviewHog team is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        user_id = settings.REVIEWHOG_RUN_USER_ID or _resolve_run_user_id(team_id)
        if not user_id:
            return Response(
                {"error": "No run user configured and no GitHub integration creator found for the team"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Forks are rejected server-side in the workflow's fetch activity (and by the Action gate); the
        # endpoint stays free of GitHub I/O and returns immediately.
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        workflow_id = start_review_pr_workflow(
            pr_url=pr_url, team_id=team_id, user_id=user_id, publish=publish, trigger_source=TRIGGER_LABEL
        )
        logger.info(f"ReviewHog trigger started workflow {workflow_id} for {repo}#{pr_number} (publish={publish})")
        return Response(
            ReviewHogTriggerResponseSerializer({"workflow_id": workflow_id, "status": "started"}).data,
            status=status.HTTP_202_ACCEPTED,
        )
