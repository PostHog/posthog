from datetime import UTC, datetime

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout import (
    FilloutSubmissionsPaginator,
    _format_fillout_datetime,
    _validated_api_base_url,
    fillout_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.source import FilloutSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fillout import (
    FilloutSourceConfig,
)


class TestFilloutTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(FilloutSource(), FilloutSourceConfig(api_key="key"))

    @parameterized.expand(
        [
            # A full page that has not yet reached the total — keep paging.
            ("more_pages", 150, 400, [{"submissionId": str(i)} for i in range(150)], True),
            # Offset would reach the filtered total — stop.
            ("reached_total", 150, 150, [{"submissionId": str(i)} for i in range(150)], False),
            # Short page (fewer than limit) — stop even if total is unknown.
            ("short_page", 150, 10_000, [{"submissionId": "a"}], False),
            # Empty page — stop.
            ("empty_page", 150, 10_000, [], False),
        ]
    )
    def test_submissions_paginator_termination(self, _name, limit, total_responses, data, expected_has_next) -> None:
        paginator = FilloutSubmissionsPaginator(limit=limit)
        request = Mock()
        request.params = {}
        paginator.init_request(request)

        response = Mock()
        response.json.return_value = {"totalResponses": total_responses}
        paginator.update_state(response, data=data)

        assert paginator.has_next_page is expected_has_next

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45), "2026-03-01T12:30:45.000Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45.000Z"),
            # Sub-millisecond precision truncates down, so the window never skips a row.
            ("microseconds", datetime(2026, 3, 1, 12, 30, 45, 123_999, tzinfo=UTC), "2026-03-01T12:30:45.123Z"),
            ("passthrough_string", "1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ]
    )
    def test_format_fillout_datetime(self, _name, value, expected) -> None:
        assert _format_fillout_datetime(value) == expected

    def test_validated_api_base_url_rejects_unknown(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://api.fillout.com/v1/api or https://eu-api.fillout.com/v1/api.",
        ):
            _validated_api_base_url("https://api.fillout.com")

    def test_validate_credentials_handles_request_exception(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            result = validate_credentials(api_key="key")

        assert result[0] is False
        assert result[1] is not None and result[1].startswith("/forms request failed:")
        assert "boom" in result[1]
        assert {request.path for request in network.requests_log} == {"/v1/api/forms"}

    @parameterized.expand(
        [
            ("next_form_readable", [400, 200]),
            ("not_found_then_readable", [404, 200]),
            ("no_form_readable", [400, 400]),
        ]
    )
    def test_validate_credentials_skips_a_form_fillout_cannot_serve(self, _name, probe_statuses) -> None:
        with scripted_network(
            [
                ScriptedResponse(json=[{"formId": "form_1"}, {"formId": "form_2"}]),
                *(ScriptedResponse(status=status, json={"message": "form unavailable"}) for status in probe_statuses),
            ]
        ) as network:
            result = validate_credentials(api_key="key")

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == [
            "/v1/api/forms",
            "/v1/api/forms/form_1/submissions",
            "/v1/api/forms/form_2/submissions",
        ]
        assert [request.param("limit") for request in network.requests_log[1:]] == ["1", "1"]

    @parameterized.expand(
        [
            (401, "Invalid Fillout API key"),
        ]
    )
    def test_validate_credentials_forms_auth_failures(self, status, expected_message) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"message": "nope"})]) as network:
            result = validate_credentials(api_key="key")

        assert result == (False, expected_message)
        assert [request.path for request in network.requests_log] == ["/v1/api/forms"]

    @parameterized.expand(
        [
            (
                "submissions",
                "https://api.fillout.com/v1/api/forms/form_1/submissions",
                "Fillout API key is missing permission to read submissions",
            ),
            (
                "form_metadata",
                "https://api.fillout.com/v1/api/forms/form_1",
                "Fillout API key is missing permission to read form metadata",
            ),
        ]
    )
    def test_validate_credentials_reports_per_form_permission_error(
        self, schema_name, expected_probe_url, expected_message
    ) -> None:
        with scripted_network(
            [
                ScriptedResponse(json=[{"formId": "form_1"}]),
                ScriptedResponse(status=403, json={"message": "forbidden"}),
            ]
        ) as network:
            result = validate_credentials(api_key="key", schema_name=schema_name)

        assert result == (False, expected_message)
        assert network.requests_log[1].url.split("?")[0] == expected_probe_url

    @parameterized.expand([("submissions",), ("form_metadata",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint=endpoint)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.rest_api_resource")
    def test_fillout_source_forms_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = fillout_source(
            api_key="key",
            api_base_url="https://api.fillout.com/v1/api",
            endpoint="forms",
            team_id=1,
            job_id="job-1",
        )

        assert response.name == "forms"
        assert response.primary_keys == ["formId"]
        # `/forms` has no stable timestamp, so it is not partitioned.
        assert response.partition_mode is None
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            (
                "submissions",
                {"submissionId": "sub_1"},
                {"submissionId": "sub_1", "form_id": "form_1"},
                # submissionId is only unique within a form, so the parent form id is part of the key.
                ["form_id", "submissionId"],
                "datetime",
                ["submissionTime"],
            ),
            (
                "form_metadata",
                {"id": "form_1", "name": "Survey", "questions": []},
                {"id": "form_1", "name": "Survey", "questions": [], "form_id": "form_1"},
                # One row per form, keyed on the parent id that `submissions` also carries.
                ["form_id"],
                # The metadata object carries no timestamp, so there is nothing to partition on.
                None,
                None,
            ),
        ]
    )
    def test_fillout_source_fanout_row_format(
        self,
        endpoint,
        child_row,
        expected_row,
        expected_primary_keys,
        expected_partition_mode,
        expected_partition_keys,
    ) -> None:
        child_payload = {"responses": [child_row], "totalResponses": 1} if endpoint == "submissions" else child_row
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json=[{"formId": "form_1"}]),
                ScriptedResponse(json=child_payload),
            ],
            team_id=1,
            job_id="job-1",
        )

        assert result.raised is None
        assert result.rows == [expected_row]
        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys
        assert result.response.partition_mode == expected_partition_mode
        assert result.response.partition_keys == expected_partition_keys
        assert result.response.sort_mode == (None if endpoint == "submissions" else "asc")

    @parameterized.expand(
        [
            # `/forms/{formId}/submissions` is the only limit/offset endpoint, and its rows sit
            # under `responses`.
            ("submissions", "limit", FilloutSubmissionsPaginator, "responses"),
            # `/forms/{formId}` returns the form's whole metadata object in one response, so
            # there is nothing to page through and no page-size param either endpoint accepts.
            ("form_metadata", None, SinglePagePaginator, "$"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.build_dependent_resource")
    def test_fillout_source_wires_paginator_and_selectors(
        self, endpoint, expected_page_size_param, expected_paginator, expected_selector, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])

        fillout_source(
            api_key="key",
            api_base_url="https://api.fillout.com/v1/api",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == expected_page_size_param
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "$"
        assert kwargs["child_endpoint_extra"]["data_selector"] == expected_selector
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], expected_paginator)

    @parameterized.expand(
        [
            ("incremental", True, datetime(2026, 3, 1, tzinfo=UTC), True),
            ("first_sync", True, None, False),
            ("non_incremental", False, datetime(2026, 3, 1, tzinfo=UTC), True),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.build_dependent_resource")
    def test_fillout_source_submissions_passes_watermark(
        self, _name, should_use_incremental_field, last_value, expects_after_date, mock_build_dependent_resource
    ) -> None:
        mock_build_dependent_resource.return_value = iter([])

        fillout_source(
            api_key="key",
            api_base_url="https://api.fillout.com/v1/api",
            endpoint="submissions",
            team_id=1,
            job_id="job-1",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        assert kwargs["db_incremental_field_last_value"] == last_value

        # Without a watermark the factory yields no incremental config, so the request carries
        # no `afterDate` rather than a sentinel date Fillout rejects.
        window = kwargs["incremental_config_factory"]("submissionTime")
        assert (window is not None) is expects_after_date

    def test_fillout_source_rejects_unknown_api_base_url(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://api.fillout.com/v1/api or https://eu-api.fillout.com/v1/api.",
        ):
            fillout_source(
                api_key="key",
                api_base_url="https://api.fillout.com",
                endpoint="forms",
                team_id=1,
                job_id="job-1",
            )
