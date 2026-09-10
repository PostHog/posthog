"""The per-user credential a client needs to install this team's skills marketplace."""

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.models import User

from products.ai_observability.backend.api.metrics import llma_track_latency

from ..marketplace.adapters import MARKETPLACE_NAME, PLUGIN_NAME
from ..marketplace.credentials import (
    build_codex_install_command,
    build_install_command,
    get_marketplace_credential,
    issue_marketplace_credential,
    marketplace_credential_label,
    marketplace_repo_url,
)
from .skill_analytics import record_skill_event
from .skill_serializers import LLMSkillMarketplaceCommandSerializer, LLMSkillMarketplaceIssueSerializer
from .skill_view_access import SkillAccessMixin


# Report or mint the caller's marketplace credential.
class SkillMarketplaceActionsMixin(SkillAccessMixin):
    def _marketplace_command_payload(self, key, token: str | None, status_str: str) -> dict[str, Any]:
        """Shape the marketplace-command response from a credential (or absence of one)."""
        team_id = self.team.id

        def claude(tok: str | None) -> str:
            return build_install_command(team_id, tok, plugin_name=PLUGIN_NAME, marketplace_name=MARKETPLACE_NAME)

        def codex(tok: str | None) -> str:
            return build_codex_install_command(team_id, tok, plugin_name=PLUGIN_NAME, marketplace_name=MARKETPLACE_NAME)

        return {
            "status": status_str,
            "connected": key is not None,
            "plugin_name": PLUGIN_NAME,
            "marketplace_name": MARKETPLACE_NAME,
            "label": marketplace_credential_label(team_id),
            "repo_url": marketplace_repo_url(team_id),
            "command": claude(token) if token else None,
            "command_template": claude(None),
            "codex_command": codex(token) if token else None,
            "codex_command_template": codex(None),
            "token": token,
            "mask_value": key.mask_value if key is not None else None,
            "created_at": key.created_at if key is not None else None,
            "last_rolled_at": key.last_rolled_at if key is not None else None,
        }

    @extend_schema(responses={200: LLMSkillMarketplaceCommandSerializer})
    @action(methods=["GET"], detail=False, url_path="marketplace/install-command")
    @llma_track_latency("llma_skills_marketplace_command")
    @monitor(feature=None, endpoint="llma_skills_marketplace_command", method="GET")
    def marketplace_command(self, request: Request, **kwargs) -> Response:
        """Report whether the user already has a marketplace credential, without minting one.

        The token is unrecoverable, so an existing credential returns its mask only — the UI shows
        "already connected, existing setups keep working" and offers an explicit rotate.
        """
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        key = get_marketplace_credential(self.team, cast(User, request.user))
        payload = self._marketplace_command_payload(key, None, "exists" if key is not None else "absent")
        return Response(LLMSkillMarketplaceCommandSerializer(payload).data)

    @extend_schema(request=LLMSkillMarketplaceIssueSerializer, responses={200: LLMSkillMarketplaceCommandSerializer})
    @marketplace_command.mapping.post
    @llma_track_latency("llma_skills_marketplace_issue")
    @monitor(feature=None, endpoint="llma_skills_marketplace_issue", method="POST")
    def issue_marketplace_command(self, request: Request, **kwargs) -> Response:
        """Mint the user's read-only marketplace credential (or rotate it) and return the install command.

        Per-user: rotating only ever invalidates this user's own credential, never a teammate's.
        """
        auth_error = self._ensure_web_authenticated(request)
        if auth_error is not None:
            return auth_error

        payload = LLMSkillMarketplaceIssueSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        issued = issue_marketplace_credential(
            self.team, cast(User, request.user), rotate=payload.validated_data["rotate"]
        )

        if issued.status in ("created", "rotated"):
            props = {"status": issued.status, "plugin_name": PLUGIN_NAME}
            record_skill_event(
                log_event="llma_skill_marketplace_credential_issued",
                action="llma skill marketplace credential issued",
                user=cast(User, request.user),
                team=self.team,
                request=request,
                props=props,
            )

        result = self._marketplace_command_payload(issued.key, issued.token, issued.status)
        return Response(LLMSkillMarketplaceCommandSerializer(result).data)
