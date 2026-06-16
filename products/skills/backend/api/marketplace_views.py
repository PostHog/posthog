"""Read-only Claude Code plugin-marketplace endpoints for a team's skills.

Serves the team's latest skills as a synthesized git repo over Git Smart HTTP so
``/plugin marketplace add <url>`` (which is ``git clone`` underneath) can install them.
Authenticated with a Project Secret API Key carried over HTTP Basic (the only auth
``git clone`` speaks) — never the user's personal key. Team-private: the PSAK's scope
and team binding (enforced by ``APIScopePermission``) gate access to one team's skills.

These are git-protocol endpoints, not part of the typed JSON/MCP API surface, so they
are excluded from the OpenAPI schema.
"""

from typing import Any

from django.db.models import QuerySet
from django.http import HttpResponse

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import BaseParser
from rest_framework.permissions import BasePermission
from rest_framework.renderers import BaseRenderer
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission, is_authenticated_via_project_secret_api_key

from ..marketplace import git_smart_http as git
from ..marketplace.adapters import build_team_marketplace_tree
from ..marketplace.auth import MarketplaceGitBasicAuthentication
from ..models.skills import LLMSkill

_MARKETPLACE_COMMIT_MESSAGE = "PostHog skills marketplace"
_MARKETPLACE_AUTHOR = "PostHog"


class GitProtocolParser(BaseParser):
    """Passthrough parser so DRF accepts git's request bodies (read back via ``request.data``)."""

    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None) -> bytes:
        return stream.read()


class GitProtocolRenderer(BaseRenderer):
    """Accept any media type so git's specific Accept header passes content negotiation
    (the views return raw HttpResponses, so this never actually renders)."""

    media_type = "*/*"
    format = "git"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class IsProjectSecretAPIKeyAuth(BasePermission):
    """Require Project Secret API Key auth. Deterministically rejects anonymous/session/other
    principals so the marketplace is strictly PSAK-gated (no reliance on lazy IsAuthenticated)."""

    message = "This endpoint requires a project secret API key."

    def has_permission(self, request: Request, view) -> bool:
        return is_authenticated_via_project_secret_api_key(request)


class LLMSkillMarketplaceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_skill"
    # git clients can't complete a Bearer/OAuth flow — make the 401 advertise Basic so the
    # credential helper (or token-in-URL) supplies the Project Secret API Key.
    www_authenticate_challenge = 'Basic realm="PostHog Skills Marketplace"'
    # Git fetch is a read even though upload-pack is a POST — force read scope for both actions.
    required_scopes = ["llm_skill:read"]
    # Default-deny: only these git actions accept a Project Secret API Key.
    psak_allowed_actions = ["marketplace_info_refs", "marketplace_upload_pack"]
    authentication_classes = [MarketplaceGitBasicAuthentication]
    parser_classes = [GitProtocolParser]
    renderer_classes = [GitProtocolRenderer]
    queryset = LLMSkill.objects.none()

    def safely_get_queryset(self, queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
        return LLMSkill.objects.none()

    def dangerously_get_permissions(self) -> list[BasePermission]:
        # The only principal here is a user-less Project Secret API Key, so the default
        # object-level RBAC checks (AccessControlPermission / TeamMemberAccessPermission)
        # don't apply and would crash querying membership for a synthetic user. Require PSAK
        # auth explicitly, then let APIScopePermission enforce the llm_skill:read scope,
        # psak_allowed_actions, and key.team == view.team.
        return [IsProjectSecretAPIKeyAuth(), APIScopePermission()]

    def _synthesize(self) -> git.SynthesizedRepo:
        tree = build_team_marketplace_tree(self.team)
        return git.synthesize_repo(tree, author=_MARKETPLACE_AUTHOR, message=_MARKETPLACE_COMMIT_MESSAGE)

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=False, url_path="info/refs")
    def marketplace_info_refs(self, request: Request, **kwargs: Any) -> HttpResponse:
        if request.query_params.get("service") != "git-upload-pack":
            return HttpResponse("Unsupported service", status=403)
        repo = self._synthesize()
        return HttpResponse(
            git.build_info_refs(repo.head_sha),
            content_type=git.INFO_REFS_CONTENT_TYPE,
            headers={"Cache-Control": "no-cache"},
        )

    @extend_schema(exclude=True)
    @action(methods=["POST"], detail=False, url_path="git-upload-pack")
    def marketplace_upload_pack(self, request: Request, **kwargs: Any) -> HttpResponse:
        # GitProtocolParser already consumed the stream into request.data as raw bytes,
        # so request.body is no longer readable — use the parsed bytes.
        raw_body = request.data if isinstance(request.data, bytes | bytearray) else b""
        repo = self._synthesize()
        return HttpResponse(
            git.build_upload_pack(bytes(raw_body), repo),
            content_type=git.UPLOAD_PACK_CONTENT_TYPE,
            headers={"Cache-Control": "no-cache"},
        )
