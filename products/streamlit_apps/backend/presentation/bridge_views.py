from __future__ import annotations

import json
import hashlib
import logging

from django.utils import timezone

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.team import Team
from posthog.rate_limit import PersonalApiKeyRateThrottle

from products.streamlit_apps.backend.logic.bridge import execute_bridge_query
from products.streamlit_apps.backend.presentation.serializers import streamlit_apps_flag_enabled

logger = logging.getLogger(__name__)

BRIDGE_REQUEST_MAX_BYTES = 16 * 1024


class StreamlitBridgeThrottle(PersonalApiKeyRateThrottle):
    scope = "streamlit_bridge"
    rate = "120/hour"

    def allow_request(self, request: Request, view: APIView) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request: Request, view: APIView) -> str:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :]
            ident = hashlib.sha256(token.encode()).hexdigest()[:32]
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _authenticate_bearer(auth_header: str) -> tuple[int | None, str | None, str | None]:
    """Returns (team_id, user_distinct_id, error)."""
    from posthog.models.oauth import find_oauth_access_token

    from products.streamlit_apps.backend.logic.oauth import get_streamlit_oauth_app

    token = auth_header[len("Bearer ") :]

    access_token = find_oauth_access_token(token)
    if access_token is None:
        return None, None, "Invalid token."
    if access_token.expires and access_token.expires < timezone.now():
        return None, None, "Token expired."
    if not access_token.scoped_teams:
        return None, None, "Token has no team scope."
    scopes = (access_token.scope or "").split()
    if "query:read" not in scopes:
        return None, None, "Insufficient scope."
    if "streamlit:bridge" not in scopes:
        return None, None, "Token is not a bridge token."
    if access_token.application_id != get_streamlit_oauth_app().id:
        return None, None, "Invalid token application."
    if len(access_token.scoped_teams) != 1:
        return None, None, "Token must be scoped to exactly one team."
    user_distinct_id = access_token.user.distinct_id if access_token.user else None
    return access_token.scoped_teams[0], user_distinct_id, None


def _streamlit_apps_enabled_for_team(team_id: int, user_distinct_id: str | None) -> bool:
    team = Team.objects.filter(id=team_id).only("organization_id").first()
    if team is None:
        return False
    org_id = str(team.organization_id)
    return streamlit_apps_flag_enabled(user_distinct_id or org_id, org_id)


class StreamlitBridgeView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [StreamlitBridgeThrottle]
    http_method_names = ["post"]

    def post(self, request: Request) -> Response:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return Response({"error": "Missing or invalid Authorization header."}, status=401)

        team_id, user_distinct_id, error = _authenticate_bearer(auth_header)
        if team_id is None:
            return Response({"error": error}, status=401)

        # Same gate as the viewset: a bridge token outlives a flag rollback,
        # so the flag must be re-checked here, not just at token mint time.
        if not _streamlit_apps_enabled_for_team(team_id, user_distinct_id):
            return Response({"error": "Streamlit apps is not available."}, status=403)

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
