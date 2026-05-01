import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

# TODO: Centralize billing proxy through BillingManager (ee/billing/) to avoid
# duplicating auth header construction and keep all billing communication in one place
from ee.billing.billing_manager import build_billing_token
from ee.settings import BILLING_SERVICE_URL

# Duplicated in services/llm-gateway/src/llm_gateway/services/plan_resolver.py
PRO_PLAN_PREFIXES = ("posthog-code-200", "posthog-code-pro-")


def _seat_priority(seat: dict[str, Any]) -> tuple[bool, int, float]:
    # Tuple comparison: active (True > False) first, then tier, then
    # earliest created_at wins ties (oldest seat is the stable pick).
    active = seat.get("status") == "active"
    plan_key = seat.get("plan_key") or ""
    created_at = seat.get("created_at") or ""
    try:
        ts = datetime.fromisoformat(created_at).timestamp()
    except (ValueError, TypeError):
        ts = float("inf")
    if any(plan_key.startswith(p) for p in PRO_PLAN_PREFIXES):
        return (active, 2, -ts)
    if plan_key:
        return (active, 1, -ts)
    return (active, 0, -ts)


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
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_billing_headers(self, request: Request) -> dict[str, str] | None:
        user = cast(User, request.user)
        org = user.organization
        if not org:
            return None
        return self._get_billing_headers_for_org(user, org)

    def _get_billing_headers_for_org(self, user: User, org: Organization) -> dict[str, str] | None:
        license = get_cached_instance_license()
        if not license:
            return None
        try:
            token = build_billing_token(license, org, user)
        except NotAuthenticated:
            logger.warning("User not a member of organization", user_id=user.id, org_id=str(org.id))
            return None
        except Exception:
            logger.exception("Failed to build billing token", user_id=user.id, org_id=str(org.id))
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

    def _require_org_member(self, request: Request, distinct_id: str) -> None:
        org = cast(User, request.user).organization
        if (
            not org
            or not OrganizationMembership.objects.filter(
                user__distinct_id=distinct_id,
                organization=org,
            ).exists()
        ):
            raise PermissionDenied("Target user is not a member of this organization.")

    def _resolve_and_check_membership(self, request: Request, pk: str | None) -> str:
        distinct_id = self._resolve_distinct_id(pk, request)
        if pk != "me":
            self._require_org_member(request, distinct_id)
        return distinct_id

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
        self._require_org_member(request, str(body_distinct_id))

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        resp = self._billing_request("POST", "/api/v2/seats/", headers, json_body=request.data)
        return self._forward_response(resp)

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        """GET /api/seats/me/ -> GET /api/v2/seats/{distinct_id}/?product_key=

        Pass ``?best=true`` to resolve the highest-tier seat across all
        the user's organizations (only supported for ``pk=me``).
        """
        if pk != "me":
            self._require_admin(request)

        use_best = request.query_params.get("best", "").lower() == "true"
        if use_best and pk == "me":
            return self._retrieve_best_seat(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_and_check_membership(request, pk)
        resp = self._billing_request(
            "GET",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            query_params=self._filtered_query_params(request),
        )
        return self._forward_response(resp)

    def _retrieve_best_seat(self, request: Request) -> Response:
        """Return the highest-tier seat across all the user's orgs.

        For single-org users this is a direct pass-through. For multi-org
        users, billing requests fan out in parallel via ThreadPoolExecutor
        (capped at 5 workers) and the best seat is selected by
        ``_seat_priority``.
        """
        user = cast(User, request.user)
        distinct_id = str(user.distinct_id)
        query_params = self._filtered_query_params(request)

        memberships = OrganizationMembership.objects.filter(user=user).select_related("organization")
        orgs = [m.organization for m in memberships if m.organization is not None]

        if not orgs:
            return Response({"detail": "No organization found"}, status=status.HTTP_400_BAD_REQUEST)

        if len(orgs) == 1:
            org = orgs[0]
            headers = self._get_billing_headers_for_org(user, org)
            if not headers:
                return Response({"detail": "No license found"}, status=status.HTTP_400_BAD_REQUEST)
            resp = self._billing_request("GET", f"/api/v2/seats/{distinct_id}/", headers, query_params=query_params)
            drf_resp = self._forward_response(resp)
            if not 200 <= drf_resp.status_code < 300 or not isinstance(drf_resp.data, dict):
                return drf_resp
            data = {**drf_resp.data, "organization_id": str(org.id), "organization_name": org.name}
            return Response(data)

        def fetch_seat(org: Organization) -> tuple[Organization, dict[str, Any]] | None:
            headers = self._get_billing_headers_for_org(user, org)
            if not headers:
                return None
            resp = self._billing_request("GET", f"/api/v2/seats/{distinct_id}/", headers, query_params=query_params)
            drf_resp = self._forward_response(resp)
            if not 200 <= drf_resp.status_code < 300 or not isinstance(drf_resp.data, dict):
                return None
            return (org, drf_resp.data)

        results: list[tuple[Organization, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=min(len(orgs), 5)) as pool:
            futures = {pool.submit(fetch_seat, org): org for org in orgs}
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception:
                    logger.warning("fetch_seat_failed", org_id=str(futures[future].id))
                    continue
                if result:
                    results.append(result)

        if not results:
            return Response(status=status.HTTP_404_NOT_FOUND)

        best_org, best = max(results, key=lambda r: _seat_priority(r[1]))
        best["organization_id"] = str(best_org.id)
        best["organization_name"] = best_org.name
        return Response(best)

    def partial_update(self, request: Request, pk: str | None = None) -> Response:
        """PATCH /api/seats/me/ -> PATCH /api/v2/seats/{distinct_id}/"""
        if pk != "me":
            self._require_admin(request)

        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_and_check_membership(request, pk)
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

        distinct_id = self._resolve_and_check_membership(request, pk)
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

        distinct_id = self._resolve_and_check_membership(request, pk)
        resp = self._billing_request(
            "POST",
            f"/api/v2/seats/{distinct_id}/reactivate/",
            headers,
            json_body=request.data,
        )
        return self._forward_response(resp)
