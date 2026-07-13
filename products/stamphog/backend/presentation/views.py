"""
DRF views for stamphog.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..logic.github_client import StamphogGitHubClient
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


class StamphogRepoConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides."""

    scope_object = "INTERNAL"
    serializer_class = StamphogRepoConfigSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = StamphogRepoConfig.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[StamphogRepoConfig]) -> QuerySet[StamphogRepoConfig]:
        return queryset.filter(team_id=self.team_id).order_by("repository")

    def perform_create(self, serializer: StamphogRepoConfigSerializer) -> None:
        # Bind a (provider, installation, repository) triple to the first team that claims it. Without
        # this, any team could register another team's installation id + repo, and the webhook path
        # would then resolve the review under the wrong team (cross-tenant policy control + data exposure).
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
        # Post-install binding: GitHub redirects the browser back with an installation_id, the frontend
        # POSTs it here, and we register a StamphogRepoConfig for every repo the installation covers under
        # the CURRENT team. A repo already owned by another team is skipped, not fatal, so one shared repo
        # can't block the rest of the batch.
        request_serializer = StamphogSyncInstallationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        installation_id = request_serializer.validated_data["installation_id"]

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

    def perform_create(self, serializer: DigestChannelSerializer) -> None:
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
            queryset = queryset.filter(digest_channel=digest_channel)

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
