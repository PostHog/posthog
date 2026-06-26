"""HTTP Basic -> Personal API Key bridge for the git marketplace endpoints.

``git clone`` (and therefore Claude Code's ``/plugin marketplace add`` / Codex's ``codex plugin
marketplace add``) only speaks HTTP Basic auth via git credential helpers — it never sends a
Bearer header. Personal API Key auth normally reads a Bearer header / body / query param, so this
authenticator pulls the ``phx_`` token out of the Basic credential and otherwise reuses the whole
standard Personal API Key flow.

Because it's a real Personal API Key, the credential is tied to the user: the standard permission
stack on the viewset (``APIScopePermission`` + ``TeamMemberAccessPermission``) re-checks the user's
``llm_skill:read`` scope, team scoping, and current membership on every request — so the credential
stops working automatically when the user is offboarded or loses team access. No manual revocation.

The token may arrive in either Basic field — git credential helpers vary in whether they put it in
the username or password — so both are tried.
"""

import base64
import binascii
from typing import Optional, Union

from django.http import HttpRequest

from rest_framework.request import Request

from posthog.auth import PersonalAPIKeyAuthentication


class MarketplaceGitBasicAuthentication(PersonalAPIKeyAuthentication):
    # Subclasses PersonalAPIKeyAuthentication so APIScopePermission treats it as PAK auth (reads
    # the key's scopes + team scoping) — we only swap the transport from Bearer to Basic by
    # overriding where the token is read from. Everything else (hash lookup, user__is_active check,
    # last_used bookkeeping, returning the real user) is inherited unchanged.
    keyword = "Basic"

    @classmethod
    def find_key_with_source(cls, request, request_data=None, extra_data=None) -> Optional[tuple[str, str]]:
        token = cls._extract_basic_token(request)
        if token is None:
            return None
        return token, cls.SOURCE_HEADER

    @staticmethod
    def _extract_basic_token(request: Union[HttpRequest, Request]) -> Optional[str]:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if isinstance(header, bytes):
            header = header.decode("latin1")
        if not header.lower().startswith("basic "):
            return None
        try:
            decoded = base64.b64decode(header[len("basic ") :].strip()).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
        username, _, password = decoded.partition(":")
        # Prefer the password field (the credential-helper convention), fall back to username.
        token = password or username
        # Only treat phx_-shaped values as a candidate, so arbitrary Basic creds aren't hashed/looked up.
        if token and token.startswith("phx_"):
            return token
        return None

    @classmethod
    def authenticate_header(cls, request) -> str:
        # A Basic challenge makes git retry through its credential helper instead of failing hard.
        return 'Basic realm="PostHog Skills Marketplace"'
