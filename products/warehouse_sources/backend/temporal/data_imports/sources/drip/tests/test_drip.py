from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.drip import (
    DripResumeConfig,
    _base_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import (
    CAMPAIGN_SUBSCRIBER_STATUSES,
    DRIP_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.source import DripSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.drip import DripSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(DripSource(), DripSourceConfig(api_token="token", account_id="9999"))


def _page(data_key: str, items: list[Any], total_pages: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if total_pages is not None:
        body["meta"] = {"total_pages": total_pages}
    return ScriptedResponse(json=body)


class TestBaseParams:
    @parameterized.expand(
        [
            ("subscribers", {"per_page": 1000}),
            ("campaigns", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("broadcasts", {"per_page": 100, "sort": "created_at", "direction": "asc"}),
            ("workflows", {"per_page": 100}),
            ("forms", {}),
            ("goals", {}),
        ]
    )
    def test_base_params(self, endpoint: str, expected: dict[str, Any]) -> None:
        assert _base_params(endpoint) == expected

    @parameterized.expand(
        [
            ("subscribers", {"per_page": 1000, "page": 1}),
            ("campaigns", {"per_page": 100, "sort": "created_at", "direction": "asc", "page": 1}),
            ("broadcasts", {"per_page": 100, "sort": "created_at", "direction": "asc", "page": 1}),
            ("workflows", {"per_page": 100, "page": 1}),
            # Non-paginated endpoints still send page=1 (mirrors the original hand-rolled source).
            ("forms", {"page": 1}),
            ("goals", {"page": 1}),
        ]
    )
    def test_params_sent_on_first_request(self, endpoint: str, expected: dict[str, Any]) -> None:
        result = _driver().run(endpoint, [_page(DRIP_ENDPOINTS[endpoint].data_key, [{"id": 1}])])

        assert result.raised is None
        assert result.queries[0] == {key: (str(value),) for key, value in expected.items()}


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "subscribers",
            [_page("subscribers", [{"id": 5}], total_pages=3)],
            resume_state=DripResumeConfig(next_page=3),
        )

        # Starts at the resume point (page 3) and stops, since total_pages == 3.
        assert result.raised is None
        assert result.params("page") == ["3"]
        assert len(result.requests) == 1

    def test_full_page_then_partial_terminates_without_meta(self) -> None:
        full_page = [{"id": i} for i in range(100)]  # workflows per_page == 100
        partial_page = [{"id": i} for i in range(100, 140)]
        result = _driver().run("workflows", [_page("workflows", full_page), _page("workflows", partial_page)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == list(range(140))
        assert result.params("page") == ["1", "2"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("not_found", 404, False, "Drip account ID not found. Please check your account ID."),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, message = validate_credentials("token", "9999")

        assert is_valid is expected_valid
        assert message == expected_message
        assert network.requests_log[0].path == "/v2/9999/subscribers"
        assert network.requests_log[0].param("per_page") == "1"


class TestDripSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        if endpoint == "campaign_subscribers":
            script = [_page("campaigns", []) for _ in CAMPAIGN_SUBSCRIBER_STATUSES]
        else:
            script = [_page(DRIP_ENDPOINTS[endpoint].data_key, [])]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        response = result.response
        assert response is not None
        config = DRIP_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestScalarEndpoints:
    @parameterized.expand(
        [
            ("tags", "tag", ["Customer", "SEO"]),
            ("custom_field_identifiers", "identifier", ["first_name", "last_name"]),
        ]
    )
    def test_bare_strings_become_single_column_rows(self, endpoint: str, column: str, values: list[str]) -> None:
        result = _driver().run(endpoint, [_page(DRIP_ENDPOINTS[endpoint].data_key, values)])

        assert result.raised is None
        assert result.rows == [{column: value} for value in values]


class TestCampaignSubscribersFanout:
    def test_child_pages_are_followed_per_campaign(self) -> None:
        responses: list[ScriptedResponse] = []
        for index, _status in enumerate(CAMPAIGN_SUBSCRIBER_STATUSES):
            responses.append(_page("campaigns", [{"id": 10}]))
            responses.append(_page("subscribers", [{"id": f"a{index}"}], total_pages=2))
            responses.append(_page("subscribers", [{"id": f"b{index}"}], total_pages=2))

        result = _driver().run("campaign_subscribers", responses)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a0", "b0", "a1", "b1", "a2", "b2"]
        child_pages = [request.param("page") for request in result.requests if request.param("status") is not None]
        assert child_pages == ["1", "2", "1", "2", "1", "2"]
