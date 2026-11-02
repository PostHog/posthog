from datetime import UTC, date, datetime

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.insightly import (
    InsightlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly import (
    PAGE_SIZE,
    InsightlyResumeConfig,
    _format_updated_after,
    normalize_pod,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source import InsightlySource


def _driver() -> SourceDriver:
    return SourceDriver(InsightlySource(), InsightlySourceConfig(pod="na1", api_key="key"))


class TestNormalizePod:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "na 1",
            "evil.com",
            "na1.evil.com",
            "http://169.254.169.254",
            "na_1",
        ],
    )
    def test_rejects_invalid_pods(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_pod(raw)


class TestFormatUpdatedAfter:
    def test_date_formats_at_midnight(self) -> None:
        assert _format_updated_after(date(2021, 6, 7)) == "2021-06-07T00:00:00Z"

    def test_string_passes_through(self) -> None:
        assert _format_updated_after("2022-03-04T05:06:07Z") == "2022-03-04T05:06:07Z"


class TestPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "Contacts",
            [ScriptedResponse(json=[{"CONTACT_ID": 7}])],
            resume_state=InsightlyResumeConfig(skip=1000),
        )

        assert result.raised is None
        assert result.rows == [{"CONTACT_ID": 7}]
        assert result.params("skip") == ["1000"]

    def test_incremental_filter_applied_on_every_page(self) -> None:
        full_page = [{"CONTACT_ID": i} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "Contacts",
            [ScriptedResponse(json=full_page), ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == full_page
        # The `updated_after_utc` server-side filter is present on both the first and second page.
        assert result.params("updated_after_utc") == ["2020-01-01T00:00:00Z"] * 2
        assert result.params("skip") == ["0", "500"]

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # Users is full-refresh only; even with an incremental value it must not send updated_after_utc.
        result = _driver().run(
            "Users",
            [ScriptedResponse(json=[{"USER_ID": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.rows == [{"USER_ID": 1}]
        assert result.params("updated_after_utc") == [None]

    def test_lead_statuses_include_the_converted_status(self) -> None:
        result = _driver().run("LeadStatuses", [ScriptedResponse(json=[{"LEAD_STATUS_ID": 1}])])

        assert result.raised is None
        assert result.rows == [{"LEAD_STATUS_ID": 1}]
        assert result.params("include_converted") == ["true"]

    def test_raises_on_non_retryable_error(self) -> None:
        result = _driver().run("Contacts", [ScriptedResponse(status=401, json=[])])

        assert isinstance(result.raised, HTTPError)
        assert "401 Client Error" in str(result.raised)

    def test_raises_on_non_list_response(self) -> None:
        # A 200 with an unexpected (non-array) body must fail loudly, not sync zero rows silently.
        result = _driver().run("Contacts", [ScriptedResponse(json={"error": "something went wrong"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestValidateCredentials:
    def test_returns_none_on_transport_error(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("na1", "key") is None

        assert {request.path for request in network.requests_log} == {"/v3.1/Contacts"}

    def test_propagates_invalid_pod(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com", "key")


class TestInsightlySourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pks, expected_partition_keys, expected_mode",
        [
            ("Contacts", ["CONTACT_ID"], ["DATE_CREATED_UTC"], "datetime"),
            ("Opportunities", ["OPPORTUNITY_ID"], ["DATE_CREATED_UTC"], "datetime"),
            ("Users", ["USER_ID"], ["DATE_CREATED_UTC"], "datetime"),
            ("Pipelines", ["PIPELINE_ID"], None, None),
            (
                "OpportunityStateHistory",
                ["OPPORTUNITY_ID", "DATE_CHANGED_UTC", "FOR_OPPORTUNITY_STATE"],
                ["DATE_CHANGED_UTC"],
                "datetime",
            ),
        ],
    )
    def test_source_response_shape(
        self,
        endpoint: str,
        expected_pks: list[str],
        expected_partition_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_pks
        assert result.response.partition_keys == expected_partition_keys
        assert result.response.partition_mode == expected_mode
        assert result.response.sort_mode == "asc"
