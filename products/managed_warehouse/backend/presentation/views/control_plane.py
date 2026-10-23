"""Transport to the duckgres provisioning API, gated on the organization's feature flag."""

from collections.abc import Callable
from functools import partial
from typing import Literal
from uuid import UUID

from django.conf import settings

import requests as http_requests
import structlog
import posthoganalytics
from rest_framework import status
from rest_framework.response import Response

from posthog.security.outbound_proxy import internal_requests

from products.managed_warehouse.backend.facade.feature_flags import DATA_WAREHOUSE_SCENE_FLAG, MANAGED_TRINO_QUERY_FLAG
from products.managed_warehouse.backend.presentation import hogtower

logger = structlog.get_logger(__name__)

DataOpsVariant = Literal["trino", "duckdb"]


def _organization_flag_enabled(flag: str, organization_id: UUID | str) -> bool:
    """Evaluate one managed-warehouse flag for the organization.

    Identity is the organization so every team in the org resolves the same value.
    """
    org_id = str(organization_id)
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                org_id,
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("Failed to evaluate managed warehouse feature flag", organization_id=org_id, flag=flag)
        return False


def data_ops_variant(organization_id: UUID | str) -> DataOpsVariant | None:
    """Which Data ops variant the organization gets, or None when it has neither flag.

    The Trino flag wins when both are on, so an organization never moves between variants
    because of Trino's state.
    """
    if _organization_flag_enabled(MANAGED_TRINO_QUERY_FLAG, organization_id):
        return "trino"
    if _organization_flag_enabled(DATA_WAREHOUSE_SCENE_FLAG, organization_id):
        return "duckdb"
    return None


def is_enabled(organization_id: UUID | str) -> bool:
    """Whether the organization has the managed warehouse through either flag."""
    return data_ops_variant(organization_id) is not None


def _request(
    method: str,
    organization_id: UUID | str,
    path: str,
    json_body: dict | None = None,
    params: dict | None = None,
    timeout: int = 30,
    require_enabled: bool = True,
) -> Response:
    """Proxy a request to the managed-warehouse control plane, gated on the org's feature flag.

    The control plane is duckgres (`DUCKGRES_API_URL`, /api/v1) unless `HOGTOWER_API_URL`
    is set, in which case the same call is served by hogtower's /api/v2 through
    `products.managed_warehouse.backend.presentation.hogtower`, which returns the duckgres v1 body.

    An empty path targets the org resource itself (`/api/v1/orgs/{org}`, e.g. to delete it);
    paths starting with "/" are org-scoped (`/api/v1/orgs/{org}{path}`); others are global
    API paths (`/api/v1/{path}`).

    `require_enabled` gates on the user-facing managed warehouse flags and is the right
    default for UI-driven calls. Backend/background callers (e.g. the Dagster duckling
    backfill) must pass `require_enabled=False`: the flag is evaluated only-locally and a
    worker without the flag definition loaded would otherwise get a spurious 403 even when
    the control plane can answer.
    """
    if require_enabled and not is_enabled(organization_id):
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_403_FORBIDDEN)

    org_id = str(organization_id)
    send: Callable[[], http_requests.Response | hogtower.TranslatedResponse]
    if hogtower.is_configured():
        # hogtower serves the same calls from its /api/v2 routes, translated back to the
        # duckgres v1 bodies below.
        send = partial(hogtower.request, method, org_id, path, json_body=json_body, params=params, timeout=timeout)
    else:
        base_url = getattr(settings, "DUCKGRES_API_URL", None)
        token = getattr(settings, "DUCKGRES_INTERNAL_SECRET", None)

        if not base_url:
            logger.warning("Provisioning request rejected: DUCKGRES_API_URL not configured", organization_id=org_id)
            return Response(
                {"error": "Managed warehouse provisioning is not configured"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        if path == "":
            url = f"{base_url.rstrip('/')}/api/v1/orgs/{org_id}"
        elif path.startswith("/"):
            url = f"{base_url.rstrip('/')}/api/v1/orgs/{org_id}{path}"
        else:
            url = f"{base_url.rstrip('/')}/api/v1/{path}"

        headers = {}
        if token:
            headers["X-Duckgres-Internal-Secret"] = token

        send = partial(
            internal_requests.request, method, url, json=json_body, params=params, headers=headers, timeout=timeout
        )

    try:
        resp = send()
    except http_requests.Timeout:
        logger.warning("Provisioning API timeout", method=method, path=path, organization_id=org_id)
        return Response({"error": "Provisioning service timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT)
    except http_requests.ConnectionError:
        logger.warning("Provisioning API connection refused", method=method, path=path, organization_id=org_id)
        return Response({"error": "Provisioning service is unreachable"}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        logger.exception("Provisioning API unexpected error", method=method, path=path, organization_id=org_id)
        return Response(
            {"error": "An error occurred contacting the provisioning service"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if resp.status_code >= 400:
        logger.warning(
            "Provisioning API returned error",
            method=method,
            path=path,
            organization_id=org_id,
            status_code=resp.status_code,
            response_body=resp.text[:500],
        )
    else:
        logger.info("Provisioning API request succeeded", method=method, path=path, organization_id=org_id)

    try:
        body = resp.json()
    except ValueError:
        body = {"error": resp.text[:500]}
    return Response(body, status=resp.status_code)
