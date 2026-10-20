from typing import Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)


class TestAppLovinSource:
    def setup_method(self) -> None:
        self.source = AppLovinSource()
        self.team_id = 123
        self.config = AppLovinSourceConfig(api_key="report-key")

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` is a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppLovin Report Key"),
        ],
    )
    def test_validate_credentials(
        self,
        probe_result: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        responses = (
            [ScriptedResponse(json={"code": 200, "results": []})]
            if probe_result
            else [ScriptedResponse(status=403)] * 2
        )
        with scripted_network(responses) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.param("api_key") for request in network.requests_log] == ["report-key"] * len(responses)

    @pytest.mark.parametrize(
        "campaign_api_key, account_id, schema_name, management_response, expected",
        [
            (
                "campaign-key",
                None,
                None,
                None,
                (False, "Enter both the Campaign Management API key and the account ID, or leave both empty."),
            ),
            (
                None,
                None,
                "campaigns",
                None,
                (False, "Add a Campaign Management API key and account ID to sync this table."),
            ),
            (None, None, "max_ad_revenue", None, (True, None)),
            # A Campaign Management outage must not block settings for a report table.
            ("campaign-key", "42", "max_ad_revenue", None, (True, None)),
            (
                "campaign-key",
                "42",
                None,
                ScriptedResponse(status=401),
                (False, "Invalid AppLovin Campaign Management API key or account ID"),
            ),
            ("campaign-key", "42", "campaigns", ScriptedResponse(json=[]), (True, None)),
        ],
    )
    def test_validate_campaign_management_credentials(
        self,
        campaign_api_key: Optional[str],
        account_id: Optional[str],
        schema_name: Optional[str],
        management_response: Optional[ScriptedResponse],
        expected: tuple[bool, Optional[str]],
    ) -> None:
        config = AppLovinSourceConfig(api_key="report-key", campaign_api_key=campaign_api_key, account_id=account_id)
        responses = [ScriptedResponse(json={"code": 200, "results": []})]
        if management_response is not None:
            responses.append(management_response)

        with scripted_network(responses) as network:
            assert self.source.validate_credentials(config, self.team_id, schema_name) == expected

        assert len(network.requests_log) == len(responses)

    @pytest.mark.parametrize(
        "campaign_api_key, account_id, expected_campaigns_reason",
        [
            (None, None, "Add a Campaign Management API key and account ID to this source to sync this table."),
            (
                "campaign-key",
                None,
                "Add a Campaign Management API key and account ID to this source to sync this table.",
            ),
            ("campaign-key", "42", None),
        ],
    )
    def test_endpoint_permissions_flag_campaign_tables_without_credentials(
        self, campaign_api_key: Optional[str], account_id: Optional[str], expected_campaigns_reason: Optional[str]
    ) -> None:
        config = AppLovinSourceConfig(api_key="report-key", campaign_api_key=campaign_api_key, account_id=account_id)

        assert self.source.get_endpoint_permissions(config, self.team_id, ["campaigns", "max_ad_revenue"]) == {
            "campaigns": expected_campaigns_reason,
            "max_ad_revenue": None,
        }


class TestAppLovinCanonicalDescriptions:
    def setup_method(self) -> None:
        self.source = AppLovinSource()

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_each_entry_has_a_description_and_docs_url(self, endpoint: str) -> None:
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
