"""
DRF views for stamphog.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, router, transaction
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
    StamphogGitHubError,
    exchange_oauth_code_for_user_token,
    list_user_accessible_repositories,
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

# The install-flow state token binds a GitHub App install callback to the team + user that started it.
# GitHub round-trips ?state=... through the install redirect; sync_installation only accepts a fresh,
# validly-signed token for the current team, so a stolen installation_id + code can't be replayed
# against another team's session.
_INSTALL_STATE_SALT = "stamphog-install-state"
_INSTALL_STATE_MAX_AGE_SECONDS = 60 * 60


def _adopt_preexisting_config(team_id: int, repository: str, installation_id: str) -> StamphogRepoConfig | None:
    """Bind a manually-created (installation-less) config to a now-verified installation.

    Reached when the installation sync hits the unique (team, repository) constraint: a row for this
    repo already exists on the team, created through the plain API/MCP path with a blank installation_id.
    Stamp the verified installation onto it so it starts resolving webhooks, rather than reporting it
    skipped and leaving it unbound forever. Returns None (caller skips) when the existing row is already
    bound to a different installation — a genuine conflict we must not silently rebind.
    """
    existing = StamphogRepoConfig.objects.for_team(team_id).filter(provider="github", repository=repository).first()
    if existing is None:
        return None
    if existing.installation_id and existing.installation_id != installation_id:
        return None
    if existing.installation_id != installation_id:
        existing.installation_id = installation_id
        try:
            existing.save(update_fields=["installation_id", "updated_at"])
        except IntegrityError:
            return None
    return existing


class StamphogRepoConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides."""

    scope_object = "stamphog"
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
        # A blank installation proves no ownership, so a manual placeholder never claims a repo across
        # teams (the DB constraint is likewise restricted to non-empty installation_id). Only a real,
        # synced installation can already be owned elsewhere.
        already_claimed = bool(installation_id) and (
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
        # Deep link into GitHub's install page for the "Connect a repository" button. The state token
        # binds the eventual callback to THIS team and user: GitHub round-trips ?state=... back to the
        # Setup URL, and sync_installation rejects any callback whose state isn't a fresh token for the
        # current team. Without it, an attacker could send a logged-in member a callback carrying the
        # attacker's own installation and bind it to the victim's team.
        slug = settings.STAMPHOG_GITHUB_APP_SLUG
        install_url = ""
        if slug:
            state = signing.dumps({"team_id": self.team_id, "user_id": request.user.pk}, salt=_INSTALL_STATE_SALT)
            install_url = f"https://github.com/apps/{slug}/installations/new?state={quote(state)}"
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
        state = request_serializer.validated_data["state"]

        # First gate: the state token must be a fresh, validly-signed token minted for THIS team by
        # install_info. This binds the callback to the team that started the flow, so a stolen
        # installation_id + code can't be replayed against another logged-in member's session.
        try:
            state_payload = signing.loads(state, salt=_INSTALL_STATE_SALT, max_age=_INSTALL_STATE_MAX_AGE_SECONDS)
        except signing.BadSignature:
            raise ValidationError(
                {"state": "Invalid or expired install session. Restart the installation from PostHog."}
            )
        if state_payload.get("team_id") != self.team_id:
            logger.warning(
                "stamphog sync_installation: state team mismatch",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise PermissionDenied("This installation link was started for a different project.")
        # The token also binds the callback to the member who started the flow. Without this, one
        # project member could hand another the callback and complete an install under the second
        # member's session (both pass the team check). Same 403 path as the team mismatch.
        if state_payload.get("user_id") != request.user.pk:
            logger.warning(
                "stamphog sync_installation: state user mismatch",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise PermissionDenied("This installation link was started by a different user.")

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

        # Enumerate with the USER token, not the app installation token: bind only the repos this user can
        # actually reach in the installation, so proving access to one repo can't attach repos they can't
        # see. The app-token list would return every repo the installer selected regardless of this user.
        try:
            repositories = list_user_accessible_repositories(installation_id, user_token)
        except StamphogGitHubError:
            logger.warning(
                "stamphog sync_installation: listing user-accessible repositories failed",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise ValidationError({"installation_id": "Failed to list accessible repositories. Try again."})

        synced: list[StamphogRepoConfig] = []
        skipped: list[str] = []
        # Bind the per-row savepoint to the model's routed DB (stamphog_db_writer when the product DB is
        # configured, else default) — a bare atomic() opens on the default connection, so the get_or_create
        # would run outside any transaction on the product DB.
        write_db = router.db_for_write(StamphogRepoConfig)
        for full_name in repositories:
            # Per-row savepoint: an IntegrityError only rolls back that row, leaving the rest of the
            # batch (and the outer autocommit context) intact.
            try:
                with transaction.atomic(using=write_db):
                    config, _ = StamphogRepoConfig.objects.for_team(self.team_id).get_or_create(
                        provider="github",
                        installation_id=installation_id,
                        repository=full_name,
                        # for_team() scopes the read but not row creation, so team_id is explicit here.
                        # Bind disabled: an installation can surface hundreds of repos, so connect them
                        # but don't start reviewing until a human toggles each on. enabled only seeds new
                        # rows; an existing row's toggle is never flipped.
                        defaults={"team_id": self.team_id, "enabled": False},
                    )
            except IntegrityError:
                # The unique (team, repository) constraint tripped: a same-team row for this repo already
                # exists under a different installation_id — the manually-created config (blank
                # installation) finally being bound. Adopt it instead of skipping; only a real conflict
                # (already bound to another installation) stays skipped.
                adopted = _adopt_preexisting_config(self.team_id, full_name, installation_id)
                if adopted is None:
                    skipped.append(full_name)
                else:
                    synced.append(adopted)
                continue
            synced.append(config)

        response = StamphogSyncInstallationResponseSerializer({"synced": synced, "skipped": skipped})
        return Response(response.data)


class ReviewRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only history of stamphog review runs, filterable by repository, PR number, and status."""

    scope_object = "stamphog"
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
            try:
                queryset = queryset.filter(pull_request__pr_number=int(pr_number))
            except ValueError:
                return queryset.none()

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

    scope_object = "stamphog"
    serializer_class = PullRequestSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = PullRequest.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[PullRequest]) -> QuerySet[PullRequest]:
        queryset = queryset.filter(team_id=self.team_id).select_related("repo_config").order_by("-created_at")

        pr_number = self.request.query_params.get("pr_number")
        if pr_number:
            try:
                queryset = queryset.filter(pr_number=int(pr_number))
            except ValueError:
                return queryset.none()

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

    scope_object = "stamphog"
    serializer_class = DigestChannelSerializer
    # Unscoped base: the fail-closed manager raises at class-body eval if scoped here.
    # safely_get_queryset re-applies the team filter per request.
    queryset = DigestChannel.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[DigestChannel]) -> QuerySet[DigestChannel]:
        return queryset.filter(team_id=self.team_id).order_by("audience_key")

    def perform_create(self, serializer: BaseSerializer[DigestChannel]) -> None:
        serializer.save(team_id=self.team_id)

    def perform_destroy(self, instance: DigestChannel) -> None:
        # Soft-disable rather than removing the row. The (team_id, audience_key) row is the tombstone
        # that stops auto_provision_channel from recreating and re-posting a digest someone opted out of
        # (see logic/channel_resolution.py — auto-provisioning skips any existing row, disabled included).
        # A hard delete would let the next daily beat resurrect the channel and re-send the digest.
        instance.enabled = False
        instance.save(update_fields=["enabled", "updated_at"])


class DigestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only history of posted (or attempted) digests, filterable by digest channel."""

    scope_object = "stamphog"
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
