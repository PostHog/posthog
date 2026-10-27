from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerize import (
    PartnerizeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.partnerize import (
    DEFAULT_START_DATE,
    PARTNERIZE_BASE_URL,
    PartnerizeResumeConfig,
    _format_start_date,
    _make_unwrap,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import (
    ENDPOINTS,
    PARTNERIZE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source import PartnerizeSource


def _driver() -> SourceDriver:
    return SourceDriver(
        PartnerizeSource(),
        PartnerizeSourceConfig(application_key="app-key", user_api_key="api-key", publisher_id="111111l92"),
    )


def _conversion_page(ids: list[str], limit: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "conversions": [{"conversion_data": {"conversion_id": i}} for i in ids],
            "limit": limit,
            "count": len(ids),
        },
    )


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2020, 3, 8, 17, 18, 33, tzinfo=UTC), "2020-03-08T17:18:33Z"),
            ("naive_datetime", datetime(2020, 3, 8, 17, 18, 33), "2020-03-08T17:18:33Z"),
            ("date", date(2020, 3, 8), "2020-03-08T00:00:00Z"),
            # Watermarks read back from the warehouse arrive as strings in Partnerize's own format.
            ("api_format_string", "2020-03-08 17:18:33", "2020-03-08T17:18:33Z"),
            ("iso_string", "2020-03-08T17:18:33+00:00", "2020-03-08T17:18:33Z"),
            ("unparseable_string", "not a date at all 12345 67890", DEFAULT_START_DATE),
            ("none", None, DEFAULT_START_DATE),
        ]
    )
    def test_coerces_watermark_to_iso_z(self, _name: str, value: Any, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestUnwrap:
    def test_missing_wrapper_key_yields_item_as_is(self) -> None:
        # Defensive: if the API returns flat rows, they pass through unmodified.
        unwrap = _make_unwrap("conversion_data")
        assert unwrap({"conversion_id": "111111l314"}) == {"conversion_id": "111111l314"}


class TestReportRows:
    def test_paginates_by_offset_and_saves_state_after_yield(self) -> None:
        result = _driver().run("conversions", [_conversion_page(["a", "b"], limit=2), _conversion_page(["c"], limit=2)])

        assert result.raised is None
        assert [row["conversion_id"] for row in result.rows] == ["a", "b", "c"]
        assert result.params("offset") == ["0", "2"]
        # State is saved after the full first page is yielded, then the short page terminates.
        assert result.saved_states == [PartnerizeResumeConfig(offset=2)]
        assert result.committed_states == [PartnerizeResumeConfig(offset=2)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "conversions", [_conversion_page([], limit=300)], resume_state=PartnerizeResumeConfig(offset=600)
        )

        assert result.raised is None
        assert result.params("offset") == ["600"]

    def test_incremental_windows_from_watermark(self) -> None:
        result = _driver().run(
            "conversions",
            [_conversion_page([], limit=300)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01 12:00:00",
            incremental_field="conversion_time",
        )

        assert result.raised is None
        assert result.params("start_date") == ["2024-05-01T12:00:00Z"]
        # The default window filters on the conversion time, no date_type override needed.
        assert result.params("date_type") == [None]

    def test_missing_data_key_is_retried_then_reraises(self) -> None:
        # A 200 body without the data key is an unexpected shape; the request is reissued and, if it
        # never recovers, surfaces as a retryable error after the attempt cap.
        result = _driver().run("conversions", always(ScriptedResponse(json={"count": 0})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_non_list_data_is_retried_then_reraises(self) -> None:
        result = _driver().run("conversions", always(ScriptedResponse(json={"conversions": {"unexpected": "object"}})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    def test_non_dict_body_is_retried_then_reraises(self) -> None:
        result = _driver().run("conversions", always(ScriptedResponse(json=["unexpected"])))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, reason: str) -> None:
        result = _driver().run("conversions", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    def test_client_error_raises_http_error_without_retry(self, _name: str, status: int, reason: str) -> None:
        # 401/403/404 are credential/permission failures — never retried, surfaced as an HTTPError
        # whose message carries the stable status text that get_non_retryable_errors matches on.
        result = _driver().run("conversions", [ScriptedResponse(status=status, json={"error": "denied"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert reason in str(result.raised)
        assert len(result.requests) == 1


class TestListRows:
    def test_follows_hypermedia_next_page_and_saves_state(self) -> None:
        next_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=2"
        result = _driver().run(
            "countries",
            [
                ScriptedResponse(
                    json={
                        "countries": [{"country": {"ref_country_id": 1}}],
                        "hypermedia": {"pagination": {"next_page": next_url}},
                    }
                ),
                ScriptedResponse(json={"countries": [{"country": {"ref_country_id": 2}}]}),
            ],
        )

        assert result.raised is None
        assert [row["ref_country_id"] for row in result.rows] == [1, 2]
        assert result.urls[1] == next_url
        assert result.saved_states == [PartnerizeResumeConfig(next_url=next_url)]

    def test_relative_next_page_is_resolved_against_base(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                ScriptedResponse(
                    json={
                        "campaigns": [{"campaign": {"campaign_id": "10l1"}}],
                        "hypermedia": {"pagination": {"next_page": "/user/publisher/111111l92/campaign/a?page=2"}},
                    }
                ),
                ScriptedResponse(json={"campaigns": []}),
            ],
        )

        assert result.raised is None
        assert result.urls[1] == f"{PARTNERIZE_BASE_URL}/user/publisher/111111l92/campaign/a?page=2"

    @parameterized.expand(
        [
            ("different_host", "https://evil.example.com/steal"),
            ("lookalike_prefix", "https://api.partnerize.com.evil.example.com/steal"),
        ]
    )
    def test_off_host_next_page_terminates_without_following(self, _name: str, next_page: str) -> None:
        # The session carries the Basic auth header, so a tampered next_page pointing off-host (a
        # different host, or a lookalike that only prefixes the base) must not be followed (SSRF
        # guard). The first page's rows still surface; the cursor is not followed and not saved.
        result = _driver().run(
            "countries",
            [
                ScriptedResponse(
                    json={
                        "countries": [{"country": {"ref_country_id": 1}}],
                        "hypermedia": {"pagination": {"next_page": next_page}},
                    }
                )
            ],
        )

        assert result.raised is None
        assert [row["ref_country_id"] for row in result.rows] == [1]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = f"{PARTNERIZE_BASE_URL}/reference/country?page=5"
        result = _driver().run(
            "countries",
            [ScriptedResponse(json={"countries": []})],
            resume_state=PartnerizeResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.urls == [resume_url]


class TestPartnerizeSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = PARTNERIZE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={config.data_key: []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.kind == "report":
            # The reports document no ordering guarantee, so the watermark only commits on completion.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("not_found", 404, False, "Your Partnerize credentials do not have access to publisher '111111l92'."),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("app-key", "api-key", "111111l92") == (expected_valid, expected_message)
        assert {request.path for request in network.requests_log} == {"/user/publisher/111111l92"}

    def test_connection_error_is_swallowed(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            valid, message = validate_credentials("app-key", "api-key", "111111l92")
        assert valid is False
        assert message == "Could not validate Partnerize credentials"
        assert {request.path for request in network.requests_log} == {"/user/publisher/111111l92"}
