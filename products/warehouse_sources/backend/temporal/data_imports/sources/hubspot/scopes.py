"""Scope gating for HubSpot objects behind an optional OAuth scope.

Some CRM objects need a scope that only exists on certain HubSpot plans, so we request it as an
`optional_scope` (see `OauthIntegration.oauth_config_for_kind`). HubSpot grants optional scopes
silently: the connection authorizes fine without them and the gap only shows up as a 403 once the
table is synced. These helpers let the source check the scopes HubSpot reported at connect time
before offering or syncing such a table, and turn a 403 that slips through into an actionable,
non-crash failure.
"""

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import HUBSPOT_ENDPOINTS

# Objects whose read scope is optional, mapped to the scope they need.
SCOPE_GATED_OBJECTS: dict[str, str] = {
    name: endpoint.required_scope for name, endpoint in HUBSPOT_ENDPOINTS.items() if endpoint.required_scope
}


class HubspotForbiddenError(NonReportableError):
    """HubSpot answered 403.

    The grant can't read the requested object: a permission or plan problem on the connected
    portal, never a PostHog defect. Subclasses NonReportableError so the job still fails with the
    message (`get_non_retryable_errors` maps it to a friendly one) without minting an
    error-tracking issue per sync.
    """


class HubspotMissingScopeError(HubspotForbiddenError):
    """A selected object needs an optional scope this connection wasn't granted."""


def missing_scope_message(endpoint: str, scope: str) -> str:
    """Internal error message for `endpoint` being unreadable without `scope`.

    `HubspotSource.get_non_retryable_errors` matches on this text, so both must be built from the
    same helper.
    """
    return f"Hubspot {endpoint} sync needs the {scope} scope, which this connection was not granted"


def missing_scope_error(endpoint: str, scope: str) -> HubspotMissingScopeError:
    return HubspotMissingScopeError(missing_scope_message(endpoint, scope))


def granted_scopes(integration_config: Mapping[str, Any] | None) -> frozenset[str] | None:
    """Scopes HubSpot reported when the connection was authorized.

    None when the connection carries no scope list (it predates us storing one), which is not
    evidence of a missing grant: callers must treat it as unknown and let the sync find out.
    """
    raw = (integration_config or {}).get("scopes")
    if isinstance(raw, str):
        # HubSpot's token-info endpoint returns a list, but tolerate the delimited-string shape
        # other providers persist so an odd row reads as scopes rather than as unknown.
        parts = raw.replace(",", " ").split()
    elif isinstance(raw, list):
        parts = [str(scope).strip() for scope in raw]
    else:
        return None

    scopes = frozenset(scope for scope in parts if scope)
    return scopes or None


def missing_scope_for_endpoint(endpoint: str, integration_config: Mapping[str, Any] | None) -> str | None:
    """The scope `endpoint` needs and this connection provably lacks, else None."""
    scope = SCOPE_GATED_OBJECTS.get(endpoint)
    if scope is None:
        return None

    scopes = granted_scopes(integration_config)
    if scopes is None:
        return None

    return None if scope in scopes else scope


@frozen
class ScopeGatedObject:
    endpoint: str
    scope: str


def scope_gated_object_for_url(url: str) -> ScopeGatedObject | None:
    """The scope-gated object `url` targets, else None.

    Matches on a whole path segment so both the object endpoints (`/crm/objects/2026-03/leads`)
    and the property-discovery endpoint (`/crm/properties/2026-03/leads`) resolve, across API
    version layouts.
    """
    segments = urlsplit(url).path.strip("/").split("/")
    for name, scope in SCOPE_GATED_OBJECTS.items():
        if name in segments:
            return ScopeGatedObject(endpoint=name, scope=scope)
    return None
