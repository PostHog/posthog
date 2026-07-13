"""
DRF views for stamphog.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..logic.github_client import (
    StamphogGitHubClient,
    StamphogGitHubError,
    exchange_oauth_code_for_user_token,
    user_can_access_installation,
)
from ..models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from .serializers import (
    DigestChannelSerializer,
    DigestRunSerializer,
    PullRequestSerializer,
    ReviewRunSerializer,
    StamphogInstallInfoSerializer,
    StamphogRepoConfigSerializer,
    StamphogSyncInstallationRequestSerializer,
    StamphogSyncInstallationResponseSerializer,
)

logger = structlog.get_logger(__name__)


class StamphogRepoConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides."""

    scope_object = "INTERNAL"
    serializer_class = StamphogRepoConfigSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = StamphogRepoConfig.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[StamphogRepoConfig]) -> QuerySet[StamphogRepoConfig]:
        return queryset.filter(team_id=self.team_id).order_by("repository")

    def perform_create(self, serializer: BaseSerializer[StamphogRepoConfig]) -> None:
        # installation_id is read-only on this serializer, so a manual create can never claim an
        # installation the caller hasn't proven ownership of — only the verified sync_installation flow
        # sets it. A manually created config therefore carries an empty installation and won't resolve
        # webhooks until synced. The cross-team guard below still binds a (provider, installation,
        # repository) triple to the first team that claims it, closing the check-then-act race at the DB.
        provider = serializer.validated_data.get("provider", "github")
        installation_id = serializer.validated_data.get("installation_id", "")
        repository = serializer.validated_data.get("repository", "")
        already_claimed_error = ValidationError(
            {"repository": "This repository is already configured under this GitHub installation by another team."}
        )
        already_claimed = (
            StamphogRepoConfig.objects.unscoped()
            .filter(provider=provider, installation_id=installation_id, repository=repository)
            .exclude(team_id=self.team_id)
            .exists()
        )
        if already_claimed:
            raise already_claimed_error
        # unique_stamphog_installation_repo backs the check above at the DB level, so a race that slips
        # past the read still fails closed here — surface it as the same 400, not a 500.
        try:
            serializer.save(team_id=self.team_id)
        except IntegrityError:
            raise already_claimed_error

    @extend_schema(responses={200: StamphogInstallInfoSerializer})
    @action(detail=False, methods=["GET"], url_path="install_info")
    def install_info(self, request: Request, **kwargs) -> Response:
        # Lets the frontend render a "Connect a repository" button (deep link into GitHub's install
        # page) without first completing the callback. No team data involved, so no scoping needed here.
        slug = settings.STAMPHOG_GITHUB_APP_SLUG
        install_url = f"https://github.com/apps/{slug}/installations/new" if slug else ""
        data = StamphogInstallInfoSerializer({"app_slug": slug, "install_url": install_url}).data
        return Response(data)

    @extend_schema(
        request=StamphogSyncInstallationRequestSerializer,
        responses={200: StamphogSyncInstallationResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="sync_installation")
    def sync_installation(self, request: Request, **kwargs) -> Response:
        # Post-install binding: GitHub redirects the browser back with an installation_id AND a
        # user-to-server OAuth code. We verify the code proves the caller owns the installation before
        # registering a StamphogRepoConfig for every repo it covers under the CURRENT team. Without the
        # ownership check any caller could bind another org's installation and hijack its webhooks. A repo
        # already owned by another team is skipped, not fatal, so one shared repo can't block the batch.
        request_serializer = StamphogSyncInstallationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        installation_id = request_serializer.validated_data["installation_id"]
        code = request_serializer.validated_data["code"]

        # Fail closed: no proven ownership, no binding. A missing OAuth token (bad/expired code or unset
        # Stamphog OAuth creds) is a 400; a valid user who simply can't reach the installation is a 403.
        user_token = exchange_oauth_code_for_user_token(code)
        if user_token is None:
            raise ValidationError({"code": "Could not verify GitHub authorization. Reinstall the app and try again."})
        try:
            owns_installation = user_can_access_installation(installation_id, user_token)
        except StamphogGitHubError:
            logger.warning(
                "stamphog sync_installation: installation ownership check failed",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise ValidationError({"installation_id": "Failed to verify installation access. Try again."})
        if not owns_installation:
            logger.warning(
                "stamphog sync_installation: caller does not own installation",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise PermissionDenied("You do not have access to this GitHub App installation.")

        client = StamphogGitHubClient(installation_id)
        repositories = client.list_installation_repositories()

        synced: list[StamphogRepoConfig] = []
        skipped: list[str] = []
        for full_name in repositories:
            # Per-row savepoint: an IntegrityError from a cross-team conflict only rolls back that row,
            # leaving the rest of the batch (and the outer autocommit context) intact.
            try:
                with transaction.atomic():
                    config, _ = StamphogRepoConfig.objects.for_team(self.team_id).get_or_create(
                        provider="github",
                        installation_id=installation_id,
                        repository=full_name,
                        # for_team() scopes the read but not row creation, so team_id is explicit here.
                        # enabled only seeds new rows; an existing row's toggle is never flipped back on.
                        defaults={"team_id": self.team_id, "enabled": True},
                    )
            except IntegrityError:
                skipped.append(full_name)
                continue
            synced.append(config)

        response = StamphogSyncInstallationResponseSerializer({"synced": synced, "skipped": skipped})
        return Response(response.data)


class ReviewRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only history of stamphog review runs, filterable by repository, PR number, and status."""

    scope_object = "INTERNAL"
    serializer_class = ReviewRunSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = ReviewRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[ReviewRun]) -> QuerySet[ReviewRun]:
        queryset = (
            queryset.filter(team_id=self.team_id).select_related("pull_request__repo_config").order_by("-created_at")
        )

        repository = self.request.query_params.get("repository")
        if repository:
            queryset = queryset.filter(pull_request__repo_config__repository=repository)

        pr_number = self.request.query_params.get("pr_number")
        if pr_number:
            queryset = queryset.filter(pull_request__pr_number=pr_number)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "repository",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by repository full name, e.g. 'PostHog/posthog'.",
            ),
            OpenApiParameter(
                "pr_number",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by pull request number.",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by review run status.",
            ),
        ],
        responses={200: ReviewRunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        return super().list(request, **kwargs)


class PullRequestViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only pull requests stamphog knows about, filterable by PR number and merge state."""

    scope_object = "INTERNAL"
    serializer_class = PullRequestSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = PullRequest.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[PullRequest]) -> QuerySet[PullRequest]:
        queryset = queryset.filter(team_id=self.team_id).select_related("repo_config").order_by("-created_at")

        pr_number = self.request.query_params.get("pr_number")
        if pr_number:
            queryset = queryset.filter(pr_number=pr_number)

        merged = self.request.query_params.get("merged")
        if merged is not None:
            queryset = queryset.filter(merged_at__isnull=merged.lower() not in ("true", "1"))

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "pr_number",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by pull request number.",
            ),
            OpenApiParameter(
                "merged",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by merge state: true for merged pull requests, false for unmerged.",
            ),
        ],
        responses={200: PullRequestSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        return super().list(request, **kwargs)


class DigestChannelViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-audience Slack destinations for the daily merged-PR digest."""

    scope_object = "INTERNAL"
    serializer_class = DigestChannelSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = DigestChannel.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DigestChannel]) -> QuerySet[DigestChannel]:
        return queryset.filter(team_id=self.team_id).order_by("audience_key")

    def perform_create(self, serializer: BaseSerializer[DigestChannel]) -> None:
        serializer.save(team_id=self.team_id)


class DigestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only history of posted (or attempted) digests, filterable by digest channel."""

    scope_object = "INTERNAL"
    serializer_class = DigestRunSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = DigestRun.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DigestRun]) -> QuerySet[DigestRun]:
        queryset = queryset.filter(team_id=self.team_id).order_by("-created_at")

        digest_channel = self.request.query_params.get("digest_channel")
        if digest_channel:
            try:
                channel_id = UUID(digest_channel)
            except ValueError:
                return queryset.none()
            queryset = queryset.filter(digest_channel_id=channel_id)

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "digest_channel",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by digest channel ID.",
            ),
        ],
        responses={200: DigestRunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        return super().list(request, **kwargs)
