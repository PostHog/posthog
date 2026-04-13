from __future__ import annotations

import json
import hashlib
import logging

from django.utils import timezone

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.rate_limit import PersonalApiKeyRateThrottle

from products.streamlit_apps.backend.services.bridge import execute_bridge_query

logger = logging.getLogger(__name__)

# Defense-in-depth body cap. The in-sandbox shim only sends small JSON
# {"query": "..."} bodies, so 16 KB is well above legitimate use.
BRIDGE_REQUEST_MAX_BYTES = 16 * 1024


class StreamlitBridgeThrottle(PersonalApiKeyRateThrottle):
    """Rate limit Streamlit bridge requests by bearer token hash.

    Each sandbox is issued its own OAuth token, so bucketing by token hash
    gives per-sandbox rate limits. We don't bucket by team_id (would punish
    teams running many concurrent apps) or by IP (Modal sandbox IPs are
    shared across tenants).

    We inherit from PersonalApiKeyRateThrottle to reuse its enable check and
    allow-list behavior, but override `allow_request` to skip the
    personal-API-key guard (the bridge uses bearer tokens, not PAKs).
    """

    scope = "streamlit_bridge"
    rate = "120/hour"

    def allow_request(self, request, view):
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request, view):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :]
            ident = hashlib.sha256(token.encode()).hexdigest()[:32]
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _authenticate_bearer(auth_header: str) -> tuple[int | None, str | None]:
    """Validate a Bearer OAuth access token bound to the Streamlit OAuth app.

    Returns (team_id, error_message). team_id is None on failure.

    The legacy TimestampSigner bridge token path was deleted; OAuth is the
    only accepted credential. Tokens minted against any other OAuth
    application (e.g. an MCP integration) are rejected even if they have
    `query:read` scope. Bridge tokens must also be scoped to exactly one
    team — we don't try to pick "the right" team from a multi-team token
    because there's no well-defined answer, and silently picking the first
    entry would let a token minted for team A run queries against team B.
    """
    from posthog.models.oauth import find_oauth_access_token

    from products.streamlit_apps.backend.services.oauth import get_streamlit_oauth_app

    token = auth_header[len("Bearer ") :]

    access_token = find_oauth_access_token(token)
    if access_token is None:
        return None, "Invalid token."
    if access_token.expires and access_token.expires < timezone.now():
        return None, "Token expired."
    if not access_token.scoped_teams:
        return None, "Token has no team scope."
    scopes = (access_token.scope or "").split()
    if "query:read" not in scopes:
        return None, "Insufficient scope."
    # Require the bridge-specific scope suffix — iframe tokens (which carry
    # streamlit:iframe) must not be reusable as bridge credentials even if
    # they leak via Referer / browser history.
    if "streamlit:bridge" not in scopes:
        return None, "Token is not a bridge token."
    if access_token.application_id != get_streamlit_oauth_app().id:
        return None, "Invalid token application."
    if len(access_token.scoped_teams) != 1:
        return None, "Token must be scoped to exactly one team."
    return access_token.scoped_teams[0], None


class StreamlitBridgeView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [StreamlitBridgeThrottle]
    http_method_names = ["post"]

    def post(self, request) -> Response:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return Response({"error": "Missing or invalid Authorization header."}, status=401)

        team_id, error = _authenticate_bearer(auth_header)
        if team_id is None:
            return Response({"error": error}, status=401)

        if len(request.body) > BRIDGE_REQUEST_MAX_BYTES:
            return Response({"error": "Request body too large."}, status=413)

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return Response({"error": "Invalid JSON body."}, status=400)

        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            return Response({"error": "Missing or empty 'query' field."}, status=400)

        try:
            result = execute_bridge_query(query=query, team_id=team_id)
            return Response(result)
        except Exception:
            logger.exception(
                "streamlit_bridge_query_failed",
                extra={"team_id": team_id},
            )
            return Response({"error": "Query execution failed."}, status=400)
