"""
DRF views for stamphog.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from functools import cached_property
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core import signing

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.scoping.manager import resolve_effective_team_id

from products.stamphog.backend.facade import (
    api as facade_api,
    contracts,
)
from products.stamphog.backend.facade.enums import ReviewTrigger

from ..facade.github import (
    StamphogGitHubError,
    exchange_oauth_code_for_user_token,
    list_user_installations,
    sync_installation_repositories,
    user_can_access_installation,
)
from .serializers import (
    DigestRunSerializer,
    PullRequestSerializer,
    ReviewRunSerializer,
    StamphogInstallInfoSerializer,
    StamphogRepoConfigSerializer,
    StamphogRepoConfigWriteSerializer,
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


class StamphogCanonicalTeamAccessPermission(BasePermission):
    """Authorize against the canonical (data-owning) team, not just the URL environment team.

    stamphog rows canonicalize to the parent (project-root) team on save, so a request made against a
    child environment reads and writes the PARENT's data. The default team gate only checks membership
    of the URL team, so a user with access to the child but not the parent (or the reverse) would be
    authorized against one team while touching another's rows. Re-anchor the membership check to the
    canonical team so authorization and data access target the same team. Root teams (no parent) are
    unaffected — the default checks already cover them.
    """

    message = "You don't have access to the project that owns this data."

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user.is_authenticated:
            return True  # IsAuthenticated handles the unauthenticated case first
        assert isinstance(view, _StamphogTeamScopedViewSet)  # only ever attached to the shared base
        team = view.team
        # parent_team_id is null (or equals self) for a root team; then canonical == URL team and the
        # default membership gate already authorized the right team.
        if team.parent_team_id is None or team.parent_team_id == team.id or team.parent_team is None:
            return True
        # A team-scoped token must cover the CANONICAL team too: the default scope check accepted the
        # URL (child) team, but the rows read and written belong to the parent — a PAK/OAuth token
        # scoped only to the child must not reach them through the child's URL.
        authenticator = request.successful_authenticator
        scoped_teams = None
        if isinstance(authenticator, OAuthAccessTokenAuthentication):
            scoped_teams = authenticator.access_token.scoped_teams
        elif isinstance(authenticator, PersonalAPIKeyAuthentication):
            scoped_teams = authenticator.personal_api_key.scoped_teams
        if scoped_teams and team.parent_team_id not in scoped_teams:
            return False
        # Same helper the default gate uses (effective_membership_level), just re-pointed at the parent.
        # It already accounts for a private parent team, so None means genuinely no access -> 403.
        level = view.user_permissions.team(team.parent_team).effective_membership_level
        return level is not None


class _StamphogTeamScopedViewSet(TeamAndOrgViewSetMixin):
    """Shared base that exposes the canonical (parent) team id for queryset scoping.

    ProductTeamModel.save() rewrites new rows to the canonical team id (parent when the team is a
    child environment, else itself). A request made with a child environment's project id must read
    under that same canonical id — scoping by the raw request team_id would miss rows the parent
    stored. resolve_effective_team_id is the framework helper the model uses; self.team is already
    loaded by the permission checks, so this resolves cheaply and is cached for the request.

    StamphogCanonicalTeamAccessPermission keeps authorization pointed at that same canonical team, so a
    caller can never be authorized against the child environment while reading/writing the parent's rows.
    """

    # Appended onto the default team/scope permission stack by get_permissions.
    permission_classes = [StamphogCanonicalTeamAccessPermission]

    @cached_property
    def canonical_team_id(self) -> int:
        return resolve_effective_team_id(self.team_id)

    def get_serializer_context(self) -> dict[str, Any]:
        # The mixin sets context["team_id"] to the RAW url team, but a serializer validating a
        # team-scoped lookup reads it. stamphog rows canonicalize to the parent team on save, so
        # those lookups must target the canonical team the row is stored under: a child-environment
        # request would otherwise validate against the wrong team's rows.
        context = super().get_serializer_context()
        context["team_id"] = self.canonical_team_id
        return context

    def _should_skip_parents_filter(self) -> bool:
        # safely_get_queryset already scopes every read by canonical_team_id, which resolves a child
        # environment's id to its parent. The default parent-lookup filter would re-add the RAW url
        # team_id, ANDing it with the canonical filter and hiding rows stored under the parent. Skip it
        # and let canonical_team_id be the single source of truth for team scoping.
        return True


class StamphogRepoConfigViewSet(_StamphogTeamScopedViewSet, viewsets.GenericViewSet):
    """Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides."""

    scope_object = "stamphog"
    serializer_class = StamphogRepoConfigSerializer

    def _get_or_404(self, pk: str | None) -> contracts.RepoConfigDTO:
        for config in facade_api.list_repo_configs(self.canonical_team_id):
            if str(config.id) == str(pk):
                return config
        raise NotFound()

    def list(self, request: Request, **kwargs) -> Response:
        configs = facade_api.list_repo_configs(self.canonical_team_id)
        page = self.paginate_queryset(configs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        return Response(self.get_serializer(self._get_or_404(pk)).data)

    @extend_schema(request=StamphogRepoConfigWriteSerializer, responses={201: StamphogRepoConfigSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        serializer = StamphogRepoConfigWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            config = facade_api.create_repo_config(self.canonical_team_id, **serializer.validated_data)
        except contracts.RepoAlreadyClaimedError:
            raise ValidationError(
                {"repository": "This repository is already configured under this GitHub installation by another team."}
            )
        return Response(self.get_serializer(config).data, status=201)

    @extend_schema(request=StamphogRepoConfigWriteSerializer, responses={200: StamphogRepoConfigSerializer})
    def update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        current = self._get_or_404(pk)
        serializer = StamphogRepoConfigWriteSerializer(
            data=request.data,
            partial=kwargs.get("partial", False),
            partial_update=True,
            current=current,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        config = facade_api.update_repo_config(self.canonical_team_id, str(pk), **serializer.validated_data)
        return Response(self.get_serializer(config).data)

    @extend_schema(request=StamphogRepoConfigWriteSerializer, responses={200: StamphogRepoConfigSerializer})
    def partial_update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        return self.update(request, pk=pk, partial=True, **kwargs)

    def destroy(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        self._get_or_404(pk)
        facade_api.disable_repo_config(self.canonical_team_id, str(pk))
        return Response(status=204)

    @extend_schema(responses={200: StamphogInstallInfoSerializer})
    @action(detail=False, methods=["GET"], url_path="install_info", required_scopes=["stamphog:read"])
    def install_info(self, request: Request, **kwargs) -> Response:
        # Deep link into GitHub's install page for the "Connect a repository" button. The state token
        # binds the eventual callback to THIS team and user: GitHub round-trips ?state=... back to the
        # Setup URL, and sync_installation rejects any callback whose state isn't a fresh token for the
        # current team. Without it, an attacker could send a logged-in member a callback carrying the
        # attacker's own installation and bind it to the victim's team.
        slug = settings.STAMPHOG_GITHUB_APP_SLUG
        client_id = settings.STAMPHOG_GITHUB_APP_CLIENT_ID
        install_url = ""
        authorize_url = ""
        # One state token backs both URLs — either callback (install Setup URL or authorize Callback URL)
        # round-trips it, and sync_installation binds the result to the team+user encoded here.
        state = signing.dumps({"team_id": self.team_id, "user_id": request.user.pk}, salt=_INSTALL_STATE_SALT)
        if slug:
            install_url = f"https://github.com/apps/{slug}/installations/new?state={quote(state)}"
        if client_id:
            # Authorize-first: an already-installed user gets a silent instant redirect back with an OAuth
            # code but no installation_id, so the connect button never dead-ends on GitHub's "update
            # installation" screen. Discovery then finds the installations from the code, server-side.
            authorize_url = (
                f"https://github.com/login/oauth/authorize?client_id={quote(client_id)}&state={quote(state)}"
            )
        data = StamphogInstallInfoSerializer(
            {"app_slug": slug, "install_url": install_url, "authorize_url": authorize_url}
        ).data
        return Response(data)

    @extend_schema(
        request=StamphogSyncInstallationRequestSerializer,
        responses={200: StamphogSyncInstallationResponseSerializer},
    )
    @action(detail=False, methods=["POST"], url_path="sync_installation", required_scopes=["stamphog:write"])
    def sync_installation(self, request: Request, **kwargs) -> Response:
        # Custom action names fall outside the default read/write action classification, so without
        # explicit required_scopes this write would be reachable with no scope check at all.
        #
        # Post-authorize binding. GitHub redirects the browser back with a user-to-server OAuth code and
        # our state token; installation_id is present only on the fresh-install redirect, absent on the
        # authorize-first redirect. We exchange the code for the user's token (the ownership proof) and:
        #   - explicit installation_id → verify the user can reach exactly it, then sync it.
        #   - no installation_id → discover the user's installations of THIS App from the token. Exactly
        #     one → sync it (the overwhelmingly common case). Several → bind NOTHING and return them as
        #     choices: reachability is not intent, and binding foreign orgs' installations here would
        #     misroute their webhooks (oldest-wins resolution). Zero isn't an error — the App isn't
        #     installed anywhere the user can see, signalled via app_not_installed.
        # Either way ownership is proven by the code, never the caller-supplied (forgeable) id. A repo
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
        connected_by_user_id = request.user.pk
        if connected_by_user_id is None:
            raise PermissionDenied("Log in to complete the installation.")
        # The token also binds the callback to the member who started the flow. Without this, one
        # project member could hand another the callback and complete an install under the second
        # member's session (both pass the team check). Same 403 path as the team mismatch.
        if state_payload.get("user_id") != connected_by_user_id:
            logger.warning(
                "stamphog sync_installation: state user mismatch",
                installation_id=installation_id,
                team_id=self.team_id,
            )
            raise PermissionDenied("This installation link was started by a different user.")

        # Fail closed: no proven ownership, no binding. A missing OAuth token (bad/expired code or unset
        # Stamphog OAuth creds) is a 400; a valid user who simply can't reach an installation is a 403.
        user_token = exchange_oauth_code_for_user_token(code)
        if user_token is None:
            raise ValidationError({"code": "Could not verify GitHub authorization. Reinstall the app and try again."})

        if installation_id:
            # Explicit-id path (fresh-install redirect): the id is caller-supplied, so verify the user can
            # actually reach exactly it before binding — otherwise a caller who learns another org's
            # installation_id could bind its repos and hijack its webhooks.
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
            installation_ids = [installation_id]
        else:
            # Discovery path (authorize-first redirect): GitHub returns only installations of THIS App the
            # user can reach, so the list is itself the ownership proof — no per-id verification needed.
            try:
                discovered = list_user_installations(user_token)
            except StamphogGitHubError:
                logger.warning(
                    "stamphog sync_installation: discovering user installations failed", team_id=self.team_id
                )
                raise ValidationError({"code": "Failed to discover GitHub App installations. Try again."})
            if not discovered:
                # The App isn't installed anywhere the user can see. Not an error: the frontend routes them
                # to the GitHub install page (install_url) off app_not_installed.
                data = StamphogSyncInstallationResponseSerializer(
                    {"synced": [], "skipped": [], "app_not_installed": True, "installations": []}
                ).data
                return Response(data)
            if len(discovered) > 1:
                # Reachability is not intent: a user in several orgs that all carry the App must pick which
                # installation this team binds — silently binding them all would attach foreign orgs' repos
                # here, and via the oldest-wins webhook resolution even blackhole another team's future
                # connect. Bind nothing; the frontend re-runs the flow with an explicit installation_id
                # (which the explicit path above verifies).
                data = StamphogSyncInstallationResponseSerializer(
                    {"synced": [], "skipped": [], "app_not_installed": False, "installations": discovered}
                ).data
                return Response(data)
            installation_ids = [discovered[0]["id"]]

        synced: list[contracts.RepoConfigDTO] = []
        skipped: list[str] = []
        for one_installation_id in installation_ids:
            try:
                installation_synced, installation_skipped = sync_installation_repositories(
                    self.canonical_team_id,
                    installation_id=one_installation_id,
                    user_token=user_token,
                    connected_by_user_id=connected_by_user_id,
                )
            except StamphogGitHubError:
                logger.warning(
                    "stamphog sync_installation: listing user-accessible repositories failed",
                    installation_id=one_installation_id,
                    team_id=self.team_id,
                )
                raise ValidationError({"installation_id": "Failed to list accessible repositories. Try again."})
            synced.extend(installation_synced)
            skipped.extend(installation_skipped)

        data = StamphogSyncInstallationResponseSerializer(
            {"synced": synced, "skipped": skipped, "app_not_installed": False, "installations": []}
        ).data
        return Response(data)


class ReviewRunViewSet(_StamphogTeamScopedViewSet, viewsets.GenericViewSet):
    """Read-only history of stamphog review runs, filterable by repository, PR number, and status."""

    scope_object = "stamphog"
    serializer_class = ReviewRunSerializer

    def _runs(self) -> facade_api.LazyDTOList[contracts.ReviewRunDTO] | None:
        """The team's review runs under the request's filters, or None if a filter is unparseable."""
        pr_number = self.request.query_params.get("pr_number")
        if pr_number:
            try:
                pr_number_value = int(pr_number)
            except ValueError:
                return None
        else:
            pr_number_value = None
        return facade_api.list_review_runs(
            self.canonical_team_id,
            repository=self.request.query_params.get("repository"),
            pr_number=pr_number_value,
            status=self.request.query_params.get("status"),
            trigger=self.request.query_params.get("trigger"),
        )

    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        run = facade_api.get_review_run(self.canonical_team_id, str(pk))
        if run is None:
            raise NotFound()
        return Response(self.get_serializer(run).data)

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
            OpenApiParameter(
                "trigger",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                enum=[t.value for t in ReviewTrigger],
                description="Filter by what caused the run: self_driving, label, or all.",
            ),
        ],
        responses={200: ReviewRunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        runs = self._runs()
        page = self.paginate_queryset(runs if runs is not None else [])
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class PullRequestViewSet(_StamphogTeamScopedViewSet, viewsets.GenericViewSet):
    """Read-only pull requests stamphog knows about, filterable by PR number and merge state."""

    scope_object = "stamphog"
    serializer_class = PullRequestSerializer

    def _pull_requests(self) -> facade_api.LazyDTOList[contracts.PullRequestDTO] | None:
        """The team's pull requests under the request's filters, or None if a filter is unparseable."""
        pr_number = self.request.query_params.get("pr_number")
        if pr_number:
            try:
                pr_number_value = int(pr_number)
            except ValueError:
                return None
        else:
            pr_number_value = None
        merged = self.request.query_params.get("merged")
        return facade_api.list_pull_requests(
            self.canonical_team_id,
            pr_number=pr_number_value,
            merged=None if merged is None else merged.lower() in ("true", "1"),
        )

    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        pull_request = facade_api.get_pull_request(self.canonical_team_id, str(pk))
        if pull_request is None:
            raise NotFound()
        return Response(self.get_serializer(pull_request).data)

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
        pull_requests = self._pull_requests()
        page = self.paginate_queryset(pull_requests if pull_requests is not None else [])
        return self.get_paginated_response(self.get_serializer(page, many=True).data)


class DigestRunViewSet(_StamphogTeamScopedViewSet, viewsets.GenericViewSet):
    """Read-only history of posted (or attempted) digests, filterable by Slack channel."""

    scope_object = "stamphog"
    serializer_class = DigestRunSerializer

    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        digest_run = facade_api.get_digest_run(self.canonical_team_id, str(pk))
        if digest_run is None:
            raise NotFound()
        return Response(self.get_serializer(digest_run).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "slack_channel_id",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Filter by the Slack channel the digest was posted to, e.g. 'C012AB3CD'.",
            ),
        ],
        responses={200: DigestRunSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        slack_channel_id = request.query_params.get("slack_channel_id") or None
        runs = facade_api.list_digest_runs(self.canonical_team_id, slack_channel_id=slack_channel_id)
        return self.get_paginated_response(self.get_serializer(self.paginate_queryset(runs), many=True).data)
