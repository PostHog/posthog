from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll import (
    MAX_RETRY_ATTEMPTS,
    AdRollResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ADROLL_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.source import AdRollSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adroll import AdRollSourceConfig

CAMPAIGNS_PATH = ADROLL_ENDPOINTS["campaigns"].path


def _driver() -> SourceDriver:
    return SourceDriver(AdRollSource(), AdRollSourceConfig(client_id="cid", personal_access_token="pat"))


def _page(results: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"results": results})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("cid", "pat") is expected

        assert network.requests_log[0].path == ADROLL_ENDPOINTS["organization"].path
        assert network.requests_log[0].param("apikey") == "cid"
        assert network.requests_log[0].headers["authorization"] == "Token pat"


class TestRows:
    @pytest.mark.parametrize("endpoint", ["advertisable_reports", "campaign_reports", "ad_reports"])
    def test_report_endpoints_filter_by_advertisables_in_entity_format(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"eid": "ADV1"}]),
                _page([{"eid": "C1", "impressions": 5}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"eid": "C1", "impressions": 5, "_advertisable_eid": "ADV1"}]
        assert result.paths[1] == ADROLL_ENDPOINTS[endpoint].path
        # The reporting endpoints take a list of advertisables, not a single one.
        assert result.requests[1].param("advertisables") == "ADV1"
        assert result.requests[1].param("data_format") == "entity"

    def test_advertisables_without_eid_are_skipped(self) -> None:
        result = _driver().run("ads", [_page([{"name": "broken"}])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("advertisables", always(ScriptedResponse(status=500, json={"error": "boom"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == MAX_RETRY_ATTEMPTS

    def test_non_retryable_client_error_raises(self) -> None:
        result = _driver().run("advertisables", [ScriptedResponse(status=401, json={"error": "boom"})])

        assert isinstance(result.raised, Exception)
        assert "401" in str(result.raised)
        assert len(result.requests) == 1


class TestFanOutResume:
    def test_resume_skips_completed_advertisables(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                _page([{"eid": "ADV1"}, {"eid": "ADV2"}]),
                _page([{"eid": "C2"}]),
            ],
            resume_state=AdRollResumeConfig(
                fanout_state={
                    "completed": [f"{CAMPAIGNS_PATH}?advertisable=ADV1"],
                    "current": None,
                    "child_state": None,
                }
            ),
        )

        # ADV1 was already synced — only the parent list and ADV2's campaigns are fetched.
        assert result.raised is None
        assert [(row["eid"], row["_advertisable_eid"]) for row in result.rows] == [("C2", "ADV2")]
        assert len(result.requests) == 2
        assert result.requests[1].param("advertisable") == "ADV2"


class TestAdRollSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = ADROLL_ENDPOINTS[endpoint]
        answer = ScriptedResponse(json={"eid": "ORG1"}) if endpoint == "organization" else _page([])
        result = _driver().run(endpoint, [answer])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == [config.primary_key]
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
