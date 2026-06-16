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
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..marketplace import git_smart_http as git
from ..marketplace.adapters import build_team_marketplace_tree
from ..marketplace.auth import MarketplaceGitBasicAuthentication
from ..models.skills import LLMSkill

_MARKETPLACE_COMMIT_MESSAGE = "PostHog skills marketplace"
_MARKETPLACE_AUTHOR = "PostHog"


class LLMSkillMarketplaceViewSet(TeamAndOrgViewSetMixin):
    scope_object = "llm_skill"
    # Git fetch is a read even though upload-pack is a POST — force read scope for both actions.
    required_scopes = ["llm_skill:read"]
    # Default-deny: only these git actions accept a Project Secret API Key.
    psak_allowed_actions = ["marketplace_info_refs", "marketplace_upload_pack"]
    authentication_classes = [MarketplaceGitBasicAuthentication]
    # Rely on the mixin's default permission stack (IsAuthenticated + APIScopePermission, which
    # enforces psak_allowed_actions and team binding + AccessControlPermission). No feature-flag
    # gate: the minted Project Secret API Key is itself the access gate.
    permission_classes = []
    queryset = LLMSkill.objects.none()

    def safely_get_queryset(self, queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
        return LLMSkill.objects.none()

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
        repo = self._synthesize()
        return HttpResponse(
            git.build_upload_pack(request.body, repo),
            content_type=git.UPLOAD_PACK_CONTENT_TYPE,
            headers={"Cache-Control": "no-cache"},
        )
