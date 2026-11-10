from __future__ import annotations

import json
import hashlib
import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.dataclasses import frozen
from posthog.ip_restrictions import enforce_ip_restrictions
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.rate_limit import PersonalApiKeyRateThrottle

from products.streamlit_apps.backend.facade.api import execute_bridge_query, get_streamlit_oauth_app
from products.streamlit_apps.backend.presentation.serializers import streamlit_apps_flag_enabled

if TYPE_CHECKING:
    from posthog.models.user import User

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


class StreamlitBridgeIPThrottle(PersonalApiKeyRateThrottle):
    """IP-keyed companion to StreamlitBridgeThrottle.

    The per-token throttle is bucketed by the (unvalidated) bearer value, so an
    unauthenticated caller could rotate a fresh random token per request and dodge
    it while still forcing OAuth token lookups. This throttle caps total attempts
    per source IP regardless of token, closing that bypass. Kept higher than the
    per-token rate because legitimate sandboxes may share an egress IP.
    """

    scope = "streamlit_bridge_ip"
    rate = "600/hour"

    def allow_request(self, request: Request, view: APIView) -> bool:
        return self._allow_request_internal(request, view, personal_api_key_only=False)

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


@frozen
class _BridgeAuthentication:
    team_id: int | None = None
    user: User | None = None
    error: str | None = None


def _authenticate_bearer(auth_header: str, request: Request) -> _BridgeAuthentication:
    """Validate a bridge bearer token and retain its user for query authorization.

    Kept as an in-view helper rather than a DRF BaseAuthentication class on purpose:
    this is a single first-party endpoint with bespoke checks (single-team scope,
    iframe-vs-bridge discriminator, org-membership re-check), so a shared auth class
    would be premature. If another product (e.g. Notebooks) grows the same
    sandbox→bridge shape, extract a shared authenticator then.
    """
    from posthog.models.oauth import find_oauth_access_token

    token = auth_header[len("Bearer ") :]

    access_token = find_oauth_access_token(token)
    if access_token is None:
        return _BridgeAuthentication(error="Invalid token.")
    if access_token.expires and access_token.expires < timezone.now():
        return _BridgeAuthentication(error="Token expired.")
    if not access_token.scoped_teams:
        return _BridgeAuthentication(error="Token has no team scope.")
    scopes = (access_token.scope or "").split()
    if "query:read" not in scopes:
        return _BridgeAuthentication(error="Insufficient scope.")
    if "streamlit:bridge" not in scopes:
        return _BridgeAuthentication(error="Token is not a bridge token.")
    if access_token.application_id != get_streamlit_oauth_app().id:
        return _BridgeAuthentication(error="Invalid token application.")
    if len(access_token.scoped_teams) != 1:
        return _BridgeAuthentication(error="Token must be scoped to exactly one team.")

    team_id = access_token.scoped_teams[0]

    # The token outlives membership changes, so re-validate the minting user
    # against the scoped team rather than trusting the embedded scope. A
    # deactivated user, or one removed from the org, must lose bridge access.
    user = access_token.user
    if user is None or not user.is_active:
        return _BridgeAuthentication(error="Token user is inactive.")

    team = Team.objects.filter(id=team_id).only("organization_id").first()
    if team is None:
        return _BridgeAuthentication(error="Token team not found.")
    if not OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).exists():
        return _BridgeAuthentication(error="Token user is not a member of the team's organization.")

    authenticator = OAuthAccessTokenAuthentication()
    authenticator.access_token = access_token
    enforce_ip_restrictions(request, user, authenticator, organization_id=str(team.organization_id))
    return _BridgeAuthentication(team_id=team_id, user=user)


def _streamlit_apps_enabled_for_team(team_id: int, user_distinct_id: str | None) -> bool:
    team = Team.objects.filter(id=team_id).only("organization_id").first()
    if team is None:
        return False
    org_id = str(team.organization_id)
    return streamlit_apps_flag_enabled(user_distinct_id or org_id, org_id)


class StreamlitBridgeView(APIView):
    # The bearer helper checks the scoped team's policy after token validation.
    _ip_restrictions_use_view_scope = True

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [StreamlitBridgeThrottle, StreamlitBridgeIPThrottle]
    http_method_names = ["post"]

    def post(self, request: Request) -> Response:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return Response({"error": "Missing or invalid Authorization header."}, status=401)

        try:
            authentication = _authenticate_bearer(auth_header, request)
        except PermissionDenied as denial:
            return Response({"error": str(denial.detail)}, status=403)
        if authentication.team_id is None:
            return Response({"error": authentication.error}, status=401)
        team_id = authentication.team_id
        token_user = authentication.user

        # Same gate as the viewset: a bridge token outlives a flag rollback,
        # so the flag must be re-checked here, not just at token mint time.
        if not _streamlit_apps_enabled_for_team(team_id, token_user.distinct_id if token_user else None):
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
            result = execute_bridge_query(query=query, team_id=team_id, user=token_user)
            return Response(result)
        except Exception:
            logger.exception(
                "streamlit_bridge_query_failed",
                extra={"team_id": team_id},
            )
            return Response({"error": "Query execution failed."}, status=400)
