from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout import (
    FilloutSubmissionsPaginator,
    _format_fillout_datetime,
    _incremental_window_factory,
    _validated_api_base_url,
    fillout_source,
    get_resource,
    validate_credentials,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestFilloutTransport:
    def test_submissions_paginator_init_sets_offset_limit_sort(self) -> None:
        paginator = FilloutSubmissionsPaginator(limit=150)
        request = Mock()
        request.params = {"afterDate": "2026-01-01T00:00:00.000Z"}

        paginator.init_request(request)

        assert request.params["offset"] == 0
        assert request.params["limit"] == 150
        assert request.params["sort"] == "asc"
        # `finished` is Fillout's default, so the request carries no `status` of its own.
        assert "status" not in request.params
        # The incremental window filter is left untouched.
        assert request.params["afterDate"] == "2026-01-01T00:00:00.000Z"

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

    def test_submissions_paginator_advances_offset(self) -> None:
        paginator = FilloutSubmissionsPaginator(limit=150)
        request = Mock()
        request.params = {}
        paginator.init_request(request)

        response = Mock()
        response.json.return_value = {"totalResponses": 1000}
        paginator.update_state(response, data=[{"submissionId": str(i)} for i in range(150)])
        paginator.update_request(request)

        assert request.params["offset"] == 150

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

    def test_incremental_window_omitted_without_a_watermark(self) -> None:
        # Fillout 400s the submissions request when `afterDate` carries a sentinel date, so a
        # sync with no watermark yet must send no `afterDate` at all.
        assert _incremental_window_factory(None)("submissionTime") is None

    def test_incremental_window_binds_afterDate_to_the_watermark(self) -> None:
        config = _incremental_window_factory(datetime(2026, 3, 1, tzinfo=UTC))("submissionTime")

        assert config is not None
        assert config["start_param"] == "afterDate"
        assert config["cursor_path"] == "submissionTime"
        # No fallback date: the watermark is the only value `afterDate` is ever given.
        assert "initial_value" not in config

    @parameterized.expand(
        [
            ("https://api.fillout.com/v1/api",),
            ("https://eu-api.fillout.com/v1/api",),
            ("https://api.zite.com/v1/api/",),
        ]
    )
    def test_validated_api_base_url_accepts_allowed_hosts(self, api_base_url: str) -> None:
        assert _validated_api_base_url(api_base_url) == api_base_url.rstrip("/")

    def test_validated_api_base_url_rejects_unknown(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of",
        ):
            _validated_api_base_url("https://api.fillout.com")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        result = validate_credentials(api_key="key")
        assert result == (False, "/forms request failed: boom")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_checks_forms_and_submissions(self, mock_session) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = [{"formId": "form_1", "name": "Survey"}]
        submissions_response = Mock(status_code=200, text="ok")
        submissions_response.json.return_value = {"responses": [], "totalResponses": 0, "pageCount": 0}
        mock_session.return_value.get.side_effect = [forms_response, submissions_response]

        result = validate_credentials(api_key="key")

        assert result == (True, None)
        assert mock_session.return_value.get.call_count == 2
        assert mock_session.return_value.get.call_args_list[0].args[0] == "https://api.fillout.com/v1/api/forms"
        assert (
            mock_session.return_value.get.call_args_list[1].args[0]
            == "https://api.fillout.com/v1/api/forms/form_1/submissions"
        )

    @parameterized.expand(
        [
            (401, "Invalid Fillout API key"),
            (403, "Fillout API key is missing permission to list forms"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_forms_auth_failures(self, status, expected_message, mock_session) -> None:
        forms_response = Mock(status_code=status, text="nope")
        forms_response.json.return_value = {"message": "nope"}
        mock_session.return_value.get.side_effect = [forms_response]

        result = validate_credentials(api_key="key")

        assert result == (False, expected_message)
        assert mock_session.return_value.get.call_count == 1

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_returns_success_when_no_forms_exist(self, mock_session) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = []
        mock_session.return_value.get.side_effect = [forms_response]

        result = validate_credentials(api_key="key")

        assert result == (True, None)
        assert mock_session.return_value.get.call_count == 1

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_for_forms_schema_skips_submissions_probe(self, mock_session) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = [{"formId": "form_1"}]
        mock_session.return_value.get.side_effect = [forms_response]

        result = validate_credentials(api_key="key", schema_name="forms")

        assert result == (True, None)
        assert mock_session.return_value.get.call_count == 1

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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout.make_tracked_session")
    def test_validate_credentials_reports_per_form_permission_error(
        self, schema_name, expected_probe_url, expected_message, mock_session
    ) -> None:
        forms_response = Mock(status_code=200, text="ok")
        forms_response.json.return_value = [{"formId": "form_1"}]
        probe_response = Mock(status_code=403, text="forbidden")
        probe_response.json.return_value = {"message": "forbidden"}
        mock_session.return_value.get.side_effect = [forms_response, probe_response]

        result = validate_credentials(api_key="key", schema_name=schema_name)

        assert result == (False, expected_message)
        assert mock_session.return_value.get.call_args_list[1].args[0] == expected_probe_url

    def test_get_resource_forms_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="forms"))
        assert resource["name"] == "forms"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/forms"
        assert resource["endpoint"]["data_selector"] == "$"
        assert resource["table_format"] == "delta"

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
                {"submissionId": "sub_1", "_forms_formId": "form_1"},
                {"submissionId": "sub_1", "form_id": "form_1"},
                # submissionId is only unique within a form, so the parent form id is part of the key.
                ["form_id", "submissionId"],
                "datetime",
                ["submissionTime"],
            ),
            (
                "form_metadata",
                {"id": "form_1", "name": "Survey", "questions": [], "_forms_formId": "form_1"},
                {"id": "form_1", "name": "Survey", "questions": [], "form_id": "form_1"},
                # One row per form, keyed on the parent id that `submissions` also carries.
                ["form_id"],
                # The metadata object carries no timestamp, so there is nothing to partition on.
                None,
                None,
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_fillout_source_fanout_row_format(
        self,
        endpoint,
        child_row,
        expected_row,
        expected_primary_keys,
        expected_partition_mode,
        expected_partition_keys,
        mock_rest_api_resources,
    ) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("forms", [{"formId": "form_1"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        response = fillout_source(
            api_key="key",
            api_base_url="https://api.fillout.com/v1/api",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
        )

        rows = list(cast(Any, response.items()))
        assert rows == [expected_row]
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode == expected_partition_mode
        assert response.partition_keys == expected_partition_keys
        assert response.sort_mode == "asc"

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
            match="API base URL must be one of",
        ):
            fillout_source(
                api_key="key",
                api_base_url="https://api.fillout.com",
                endpoint="forms",
                team_id=1,
                job_id="job-1",
            )
