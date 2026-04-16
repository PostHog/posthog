import re
from typing import Any, cast

import requests
import structlog
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, ParseError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.cloud_utils import get_cached_instance_license
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.permissions import APIScopePermission

# TODO: Centralize billing proxy through BillingManager (ee/billing/) to avoid
# duplicating auth header construction and keep all billing communication in one place
from ee.billing.billing_manager import build_billing_token
from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 30
_SAFE_PK_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _is_org_admin(user: Any) -> bool:
    org = user.organization
    if not org:
        return False
    return OrganizationMembership.objects.filter(
        user=user, organization=org, level__gte=OrganizationMembership.Level.ADMIN
    ).exists()


class SeatViewSet(viewsets.ViewSet):
    """
    Proxy for seat management through the billing service.

    All endpoints resolve ``me`` in the URL to the requesting user's
    ``distinct_id``, build a billing JWT and forward the request to the
    billing service's ``/api/v2/seats/`` endpoints.

    Successful responses that contain seat data are unwrapped so the
    client receives the seat object directly (not the billing envelope).
    Error responses are forwarded as-is.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_billing_headers(self, request: Request) -> dict[str, str] | None:
        user = cast(User, request.user)
        license = get_cached_instance_license()
        org = user.organization
        if not org or not license:
            return None
        try:
            token = build_billing_token(license, org, user)
        except NotAuthenticated:
            logger.warning("User not a member of their current organization", user_id=user.id)
            return None
        except Exception:
            logger.exception("Failed to build billing token", user_id=user.id)
            return None
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    def _resolve_distinct_id(pk: str | None, request: Request) -> str:
        if pk is None:
            raise ParseError("pk is required")
        if pk == "me":
            return str(cast(User, request.user).distinct_id)
        if not _SAFE_PK_PATTERN.match(pk):
            raise ParseError("Invalid identifier format")
        return pk

    def _forward_response(self, billing_response: requests.Response | None, extract_seat: bool = True) -> Response:
        """Convert a billing service response to a DRF Response.

        For successful responses that contain a ``seat`` key the seat
        object is returned directly so the client doesn't need to know
        about the billing envelope.  Error responses pass through as-is.
        """
        if billing_response is None:
            return Response({"detail": "Billing service unavailable"}, status=status.HTTP_502_BAD_GATEWAY)

        if billing_response.status_code == 204:
            return Response(status=status.HTTP_204_NO_CONTENT)

        try:
            data = billing_response.json()
        except ValueError:
            return Response({"detail": "Invalid response from billing service"}, status=status.HTTP_502_BAD_GATEWAY)

        if billing_response.ok and extract_seat and isinstance(data, dict) and "seat" in data:
            return Response(data["seat"], status=billing_response.status_code)

        return Response(data, status=billing_response.status_code)

    def _billing_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: Any = None,
        query_params: dict[str, str] | None = None,
    ) -> requests.Response | None:
        url = f"{BILLING_SERVICE_URL}{path}"
        try:
            return requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=query_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            logger.exception("Billing service request failed", path=path, method=method)
            return None

    def _require_admin(self, request: Request) -> None:
        if not _is_org_admin(request.user):
            raise PermissionDenied("Only organization admins can perform this action.")

    @staticmethod
    def _filtered_query_params(request: Request) -> dict[str, str]:
        product_key = request.query_params.get("product_key", "")
        if product_key:
            return {"product_key": product_key}
        return {}

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def list(self, request: Request) -> Response:
        """GET /api/seats/?product_key= -> GET /api/v2/seats/"""
        self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        resp = self._billing_request(
            "GET",
            "/api/v2/seats/",
            headers,
            query_params=self._filtered_query_params(request),
        )
        return self._forward_response(resp, extract_seat=False)

    def create(self, request: Request) -> Response:
        """POST /api/seats/ -> POST /api/v2/seats/"""
        body_distinct_id = request.data.get("user_distinct_id")
        if not body_distinct_id:
            return Response({"detail": "user_distinct_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not _SAFE_PK_PATTERN.match(str(body_distinct_id)):
            return Response({"detail": "Invalid user_distinct_id format"}, status=status.HTTP_400_BAD_REQUEST)
        if str(body_distinct_id) != str(cast(User, request.user).distinct_id):
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        resp = self._billing_request("POST", "/api/v2/seats/", headers, json_body=request.data)
        return self._forward_response(resp)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """GET /api/seats/me/ -> GET /api/v2/seats/{distinct_id}/?product_key="""
        if pk != "me":
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "GET",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            query_params=self._filtered_query_params(request),
        )
        return self._forward_response(resp)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        """PATCH /api/seats/me/ -> PATCH /api/v2/seats/{distinct_id}/"""
        if pk != "me":
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "PATCH",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            json_body=request.data,
        )
        return self._forward_response(resp)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        """DELETE /api/seats/me/?product_key= -> DELETE /api/v2/seats/{distinct_id}/?product_key="""
        if pk != "me":
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "DELETE",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            query_params=self._filtered_query_params(request),
        )
        return self._forward_response(resp, extract_seat=False)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request: Request, pk: str | None = None) -> Response:
        """POST /api/seats/me/reactivate/ -> POST /api/v2/seats/{distinct_id}/reactivate/"""
        if pk != "me":
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "POST",
            f"/api/v2/seats/{distinct_id}/reactivate/",
            headers,
            json_body=request.data,
        )
        return self._forward_response(resp)
