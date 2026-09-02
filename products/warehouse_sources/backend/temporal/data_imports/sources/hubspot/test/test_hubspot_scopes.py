from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hubspot import (
    HubspotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers import raise_for_hubspot_status
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.scopes import (
    HubspotForbiddenError,
    HubspotMissingScopeError,
    ScopeGatedObject,
    missing_scope_for_endpoint,
    missing_scope_message,
    scope_gated_object_for_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import LEADS_SCOPE
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source import HubspotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.test.test_source_routing import (
    _make_inputs,
)


def _response(status: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.raise_for_status.side_effect = (
        None if 200 <= status < 300 else HTTPError(f"{status} Client Error", response=response)
    )
    return response


def _integration(config: dict[str, Any]) -> MagicMock:
    integration = MagicMock()
    integration.config = config
    integration.access_token = "access"
    integration.refresh_token = "refresh"
    return integration


class TestMissingScopeForEndpoint:
    @parameterized.expand(
        [
            ("granted", {"scopes": ["tickets", LEADS_SCOPE]}, None),
            ("not_granted", {"scopes": ["tickets", "crm.objects.deals.read"]}, LEADS_SCOPE),
            ("space_separated_string", {"scopes": f"tickets {LEADS_SCOPE}"}, None),
            ("comma_separated_string", {"scopes": "tickets,crm.objects.deals.read"}, LEADS_SCOPE),
            # Connections authorized before we stored scopes say nothing about the grant, so the
            # table must stay available rather than being hidden from a portal that can read it.
            ("field_absent", {"hub_id": 1}, None),
            ("field_empty", {"scopes": []}, None),
        ]
    )
    def test_leads_scope_verdict(self, _name: str, integration_config: dict[str, Any], expected: str | None) -> None:
        assert missing_scope_for_endpoint("leads", integration_config) == expected

    def test_endpoint_without_optional_scope_is_never_gated(self) -> None:
        assert missing_scope_for_endpoint("deals", {"scopes": []}) is None


_GATED_LEADS = ScopeGatedObject(endpoint="leads", scope=LEADS_SCOPE)


class TestScopeGatedObjectForUrl:
    @parameterized.expand(
        [
            ("properties_v3", "https://api.hubapi.com/crm/v3/properties/leads", _GATED_LEADS),
            ("properties_dated", "https://api.hubapi.com/crm/properties/2026-03/leads", _GATED_LEADS),
            ("objects_dated", "https://api.hubapi.com/crm/objects/2026-03/leads?limit=100", _GATED_LEADS),
            ("search", "https://api.hubapi.com/crm/v3/objects/leads/search", _GATED_LEADS),
            ("other_object", "https://api.hubapi.com/crm/v3/properties/deals", None),
            # "leads" only counts as a whole path segment, not as part of another object's name.
            ("substring_only", "https://api.hubapi.com/crm/v3/objects/leadsources", None),
        ]
    )
    def test_url_attribution(self, _name: str, url: str, expected: ScopeGatedObject | None) -> None:
        assert scope_gated_object_for_url(url) == expected


class TestRaiseForHubspotStatus:
    def test_forbidden_on_scope_gated_object_names_the_scope(self) -> None:
        url = "https://api.hubapi.com/crm/properties/2026-03/leads"
        with pytest.raises(HubspotMissingScopeError) as exc:
            raise_for_hubspot_status(_response(403), url)

        assert str(exc.value) == missing_scope_message("leads", LEADS_SCOPE)
        assert str(exc.value) in HubspotSource().get_non_retryable_errors()

    def test_forbidden_elsewhere_keeps_the_message_the_error_policy_matches(self) -> None:
        url = "https://api.hubapi.com/crm/v3/objects/deals"
        with pytest.raises(HubspotForbiddenError) as exc:
            raise_for_hubspot_status(_response(403), url)

        assert "403 Client Error: Forbidden for url: https://api.hubapi.com" in str(exc.value)

    @parameterized.expand(
        [("missing_scope", "/crm/properties/2026-03/leads"), ("other_object", "/crm/v3/objects/deals")]
    )
    def test_forbidden_stays_out_of_error_tracking(self, _name: str, path: str) -> None:
        # A 403 is a permission problem on the customer's portal, so it must not read as a crash.
        with pytest.raises(NonReportableError):
            raise_for_hubspot_status(_response(403), f"https://api.hubapi.com{path}")

    def test_other_client_errors_still_raise_http_error(self) -> None:
        with pytest.raises(HTTPError):
            raise_for_hubspot_status(_response(404), "https://api.hubapi.com/crm/v3/objects/deals")


class TestScopeGatingInSource:
    def _config(self) -> HubspotSourceConfig:
        return HubspotSourceConfig.from_dict({"hubspot_integration_id": "1"})

    @parameterized.expand(
        [
            ("granted", {"scopes": [LEADS_SCOPE]}, True),
            ("not_granted", {"scopes": ["tickets"]}, False),
            ("unknown", {}, True),
        ]
    )
    def test_leads_offered_only_when_the_scope_is_not_provably_missing(
        self, _name: str, integration_config: dict[str, Any], expected: bool
    ) -> None:
        source = HubspotSource()
        with patch.object(source, "get_oauth_integration", return_value=_integration(integration_config)):
            names = {schema.name for schema in source.get_schemas(self._config(), team_id=1)}

        assert ("leads" in names) is expected
        assert "deals" in names

    def test_sync_fails_with_an_actionable_error_when_the_scope_is_missing(self) -> None:
        source = HubspotSource()
        inputs = _make_inputs(schema_name="leads")

        with (
            patch.object(source, "get_oauth_integration", return_value=_integration({"scopes": ["tickets"]})),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source.hubspot_source"
            ) as hubspot_source_mock,
            pytest.raises(HubspotMissingScopeError) as exc,
        ):
            source.source_for_pipeline(self._config(), MagicMock(), inputs)

        hubspot_source_mock.assert_not_called()
        friendly = HubspotSource().get_non_retryable_errors()[str(exc.value)]
        assert friendly is not None
        assert LEADS_SCOPE in friendly
