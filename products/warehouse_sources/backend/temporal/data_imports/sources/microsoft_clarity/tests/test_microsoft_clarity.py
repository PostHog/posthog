import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.microsoft_clarity import (
    BASE_URL,
    INSIGHTS_PATH,
    _build_params,
    _resolve_dimensions,
    microsoft_clarity_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    ENDPOINT_NAME,
    NO_DIMENSION,
)

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.microsoft_clarity.make_tracked_session"


def _make_response(status_code: int, *, json_body: Any = None, text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = f"{BASE_URL}{INSIGHTS_PATH}"
    if json_body is not None:
        response._content = json.dumps(json_body).encode()
    elif text is not None:
        response._content = text.encode()
    else:
        response._content = b""
    return response


class TestBuildParams:
    def test_no_dimensions(self) -> None:
        assert _build_params("1", []) == {"numOfDays": "1"}

    def test_with_dimensions_numbered_in_order(self) -> None:
        params = _build_params("2", ["OS", "Browser"])
        assert params == {"numOfDays": "2", "dimension1": "OS", "dimension2": "Browser"}


class TestResolveDimensions:
    def test_all_none_returns_empty(self) -> None:
        assert _resolve_dimensions(NO_DIMENSION, NO_DIMENSION, NO_DIMENSION) == []

    def test_none_values_are_skipped(self) -> None:
        assert _resolve_dimensions(None, None, None) == []

    def test_selected_dimensions_are_kept_in_order(self) -> None:
        assert _resolve_dimensions("OS", "Browser", NO_DIMENSION) == ["OS", "Browser"]

    def test_gap_in_selection_is_compacted(self) -> None:
        assert _resolve_dimensions("OS", NO_DIMENSION, "Device") == ["OS", "Device"]

    def test_duplicate_selection_is_deduplicated(self) -> None:
        assert _resolve_dimensions("OS", "OS", "Device") == ["OS", "Device"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, [], True, None),
            ("unauthorized", 401, None, False, "Invalid or expired Microsoft Clarity API token."),
            ("forbidden", 403, None, False, "This Microsoft Clarity API token is not authorized for this project."),
            ("quota_exceeded_still_valid", 429, None, True, None),
            ("unexpected_status", 400, None, False, "Microsoft Clarity returned status 400."),
        ]
    )
    @mock.patch(SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        json_body: Any,
        expected_valid: bool,
        expected_error: str | None,
        MockSession: Any,
    ) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(status, json_body=json_body)

        valid, error = validate_credentials("token")

        assert valid is expected_valid
        assert error == expected_error

    @mock.patch(SESSION_PATCH)
    def test_transport_exception_is_invalid(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.side_effect = requests.ConnectionError("down")

        valid, error = validate_credentials("token")

        assert valid is False
        assert error == "Could not reach Microsoft Clarity. Please try again."


SAMPLE_PAYLOAD = [
    {
        "metricName": "Traffic",
        "information": [
            {
                "totalSessionCount": "9554",
                "totalBotSessionCount": "8369",
                "distantUserCount": "189733",
                "PagesPerSessionPercentage": 1.0931,
                "OS": "Other",
            },
            {
                "totalSessionCount": "291942",
                "totalBotSessionCount": "31076",
                "distantUserCount": "212836",
                "PagesPerSessionPercentage": 2.2609,
                "OS": "Android",
            },
        ],
    },
    {
        "metricName": "ScrollDepth",
        "information": [{"averageScrollDepthPercentage": 45.2, "OS": "Other"}],
    },
]


class TestMicrosoftClaritySource:
    @freeze_time("2026-07-23T12:00:00Z")
    @mock.patch(SESSION_PATCH)
    def test_flattens_every_metric_and_information_row(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(200, json_body=SAMPLE_PAYLOAD)

        response = microsoft_clarity_source(
            token="token", num_of_days="1", dimension1="OS", dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
        )
        rows = list(cast("Iterable[Any]", response.items()))

        assert len(rows) == 3
        assert rows[0]["metric_name"] == "Traffic"
        assert rows[0]["row_index"] == 0
        assert rows[0]["OS"] == "Other"
        assert rows[0]["synced_at"] == "2026-07-23T12:00:00+00:00"
        assert rows[1]["metric_name"] == "Traffic"
        assert rows[1]["row_index"] == 1
        assert rows[1]["OS"] == "Android"
        assert rows[2]["metric_name"] == "ScrollDepth"
        assert rows[2]["row_index"] == 0

    @mock.patch(SESSION_PATCH)
    def test_num_of_days_is_recorded_on_every_row(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(200, json_body=SAMPLE_PAYLOAD)

        response = microsoft_clarity_source(
            token="token", num_of_days="3", dimension1=NO_DIMENSION, dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
        )
        rows = list(cast("Iterable[Any]", response.items()))

        assert all(row["num_of_days"] == 3 for row in rows)

    @mock.patch(SESSION_PATCH)
    def test_source_response_shape(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(200, json_body=SAMPLE_PAYLOAD)

        response = microsoft_clarity_source(
            token="token", num_of_days="1", dimension1=NO_DIMENSION, dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
        )

        assert response.name == ENDPOINT_NAME
        assert response.primary_keys == ["metric_name", "synced_at", "row_index"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["synced_at"]

    @mock.patch(SESSION_PATCH)
    def test_dimension_params_are_sent_to_the_api(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(200, json_body=[])

        microsoft_clarity_source(
            token="token", num_of_days="2", dimension1="Browser", dimension2="Device", dimension3=NO_DIMENSION
        )

        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"numOfDays": "2", "dimension1": "Browser", "dimension2": "Device"}

    @mock.patch(SESSION_PATCH)
    def test_non_list_payload_yields_no_rows(self, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(200, json_body={"unexpected": "shape"})

        response = microsoft_clarity_source(
            token="token", num_of_days="1", dimension1=NO_DIMENSION, dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
        )

        assert list(cast("Iterable[Any]", response.items())) == []

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("quota_exceeded", 429), ("server_error", 500)])
    @mock.patch(SESSION_PATCH)
    def test_error_status_raises(self, _name: str, status: int, MockSession: Any) -> None:
        session = MockSession.return_value
        session.get.return_value = _make_response(status, text="boom")

        with pytest.raises(requests.HTTPError):
            microsoft_clarity_source(
                token="token",
                num_of_days="1",
                dimension1=NO_DIMENSION,
                dimension2=NO_DIMENSION,
                dimension3=NO_DIMENSION,
            )
