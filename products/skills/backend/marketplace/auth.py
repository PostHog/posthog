"""HTTP Basic -> Project Secret API Key bridge for the git marketplace endpoints.

``git clone`` (and therefore Claude Code's ``/plugin marketplace add``) only speaks HTTP
Basic auth via git credential helpers — it never sends a Bearer header. PSAK auth is
Bearer-only, so this authenticator pulls the ``phs_`` token out of the Basic credential
and validates it exactly like ``ProjectSecretAPIKeyAuthentication`` does, returning the
same synthetic ``ProjectSecretAPIKeyUser`` so ``APIScopePermission`` enforces scopes and
team binding (``view.team == key.team``) unchanged.

The token may arrive in either Basic field — git credential helpers vary in whether they
put it in the username or password — so both are tried.
"""

import base64
import binascii
from datetime import timedelta
from typing import Optional, Union

from django.http import HttpRequest
from django.utils import timezone

from rest_framework import authentication
from rest_framework.request import Request

from posthog.auth import ProjectSecretAPIKeyAuthentication, ProjectSecretAPIKeyUser
from posthog.clickhouse.query_tagging import AccessMethod, tag_authentication
from posthog.models.project_secret_api_key import ProjectSecretAPIKey, find_project_secret_api_key


class MarketplaceGitBasicAuthentication(ProjectSecretAPIKeyAuthentication):
    # Subclasses ProjectSecretAPIKeyAuthentication so APIScopePermission's
    # isinstance(...) check treats it as PSAK auth and enforces scope, team binding,
    # and psak_allowed_actions — we only swap the transport from Bearer to Basic.
    keyword = "Basic"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[object, None]]:
        token = self._extract_basic_token(request)
        if not token:
            return None

        psak = find_project_secret_api_key(token)
        if psak is None:
            # Return None rather than raising so the 401 carries a Basic challenge and the
            # git credential helper is prompted to supply (different) credentials.
            return None

        now = timezone.now()
        if psak.last_used_at is None or (now - psak.last_used_at > timedelta(hours=1)):
            ProjectSecretAPIKey.objects.filter(pk=psak.pk).update(last_used_at=now)

        self.project_secret_api_key = psak

        tag_authentication(
            user_id=None,
            team_id=psak.team_id,
            access_method=AccessMethod.PROJECT_SECRET_API_KEY,
            api_key_mask=psak.mask_value,
            api_key_label=psak.label,
        )

        return (ProjectSecretAPIKeyUser(psak), None)

    @staticmethod
    def _extract_basic_token(request: Union[HttpRequest, Request]) -> Optional[str]:
        header = authentication.get_authorization_header(request).decode("latin1")
        if not header.lower().startswith("basic "):
            return None
        try:
            decoded = base64.b64decode(header[len("basic ") :].strip()).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
        username, _, password = decoded.partition(":")
        # Prefer the password field (the credential-helper convention), fall back to username.
        return password or username or None

    def authenticate_header(self, request: Union[HttpRequest, Request]) -> str:
        # A Basic challenge makes git retry through its credential helper instead of failing hard.
        return 'Basic realm="PostHog Skills Marketplace"'
