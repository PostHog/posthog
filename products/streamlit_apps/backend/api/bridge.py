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

BRIDGE_REQUEST_MAX_BYTES = 16 * 1024


class StreamlitBridgeThrottle(PersonalApiKeyRateThrottle):
    """Per-sandbox rate limit, bucketing by bearer-token hash (one OAuth token per sandbox)."""

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
    """Validate a bearer OAuth token bound to the Streamlit OAuth app.

    Returns (team_id, error_message). Rejects tokens from other OAuth apps
    and tokens scoped to != 1 team (no "pick the first entry" shortcut).
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
    # Iframe tokens carry streamlit:iframe and must not be reusable here.
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
        except json.JSONDecodeError:
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
