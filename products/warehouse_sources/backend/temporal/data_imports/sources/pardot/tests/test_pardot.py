import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.pardot import (
    PardotPageTokenExpiredError,
    PardotQueryRejectedError,
    PardotResumeConfig,
    _build_query_params,
    _format_datetime,
    get_rows,
    pardot_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.settings import PARDOT_ENDPOINTS

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.pardot.pardot.make_tracked_session"
REFRESH_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.pardot.pardot.salesforce_refresh_access_token"
)

CREDENTIALS: dict[str, Any] = {
    "environment": "production",
    "business_unit_id": "0Uv000000000000000",
    "access_token": "access",
    "refresh_token": "refresh",
    "instance_url": "https://acme.my.salesforce.com",
}


class FakeResumeManager(ResumableSourceManager[PardotResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: PardotResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[PardotResumeConfig] = []
        self.clear_count = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> PardotResumeConfig | None:
        return self.state

    def save_state(self, data: PardotResumeConfig) -> None:
        self.saved.append(data)
        self.state = data

    def clear_state(self) -> None:
        self.clear_count += 1
        self.state = None


def _response(payload: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://pi.pardot.com/api/v5/objects/prospects"
    response._content = json.dumps(payload).encode()
    return response


def _session(get_responses: list[Response]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = get_responses
    return session


def _collect(
    session: mock.MagicMock,
    manager: FakeResumeManager,
    endpoint: str = "prospects",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    with mock.patch(SESSION_PATCH, return_value=session):
        pages = get_rows(
            endpoint=endpoint,
            api_version="v5",
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
            **{**CREDENTIALS, **kwargs},
        )
        return [row for page in pages for row in page]


def _get_params(session: mock.MagicMock) -> list[dict[str, Any]]:
    return [call.kwargs["params"] for call in session.get.call_args_list]


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # v5 refuses the `Z` designator with "Invalid date time value" and fails the
            # whole query, so every branch has to emit a numeric offset.
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05+00:00"),
            ("2024-01-02T05:04:05+02:00", "2024-01-02T03:04:05+00:00"),
            ("not a timestamp", "not a timestamp"),
        ],
    )
    def test_formats_cursor_values(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestBuildQueryParams:
    def test_incremental_filters_and_sorts_on_the_chosen_cursor(self) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS["prospects"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            incremental_field="updatedAt",
        )

        assert params["orderBy"] == "updatedAt"
        assert params["updatedAtAfterOrEqualTo"] == "2024-05-01T00:00:00+00:00"

    @pytest.mark.parametrize(
        "endpoint, incremental_field",
        [
            # The endpoint advertises no incremental field at all.
            ("prospect_accounts", "createdAt"),
            # The requested field isn't one this endpoint advertises.
            ("prospects", "lastActivityAt"),
        ],
    )
    def test_unsupported_cursor_falls_back_to_the_default_sort(self, endpoint: str, incremental_field: str) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            incremental_field=incremental_field,
        )

        assert params["orderBy"] == "id"
        assert not any(key.endswith("AfterOrEqualTo") for key in params)


def _refused_field_body(field: str) -> dict[str, Any]:
    return {"code": 51, "message": f"Invalid parameter: fields. It contains an invalid or unknown field: {field}."}


class TestFieldLists:
    @pytest.mark.parametrize(
        "endpoint, write_only_field",
        [
            # v5 400s a query whose `fields` list names a write-only-on-create field.
            ("custom_fields", "valuesPrefill"),
            ("list_emails", "scheduledTime"),
        ],
    )
    def test_does_not_request_write_only_fields(self, endpoint: str, write_only_field: str) -> None:
        assert write_only_field not in PARDOT_ENDPOINTS[endpoint].fields

    def test_a_refused_field_is_dropped_and_the_query_retried(self) -> None:
        session = _session(
            [
                _response(_refused_field_body("salesforceCmsId"), status_code=400),
                _response({"values": [{"id": 1}], "nextPageToken": "t1"}),
                _response({"values": [{"id": 2}]}),
            ]
        )

        rows = _collect(session, FakeResumeManager(), endpoint="forms")
        first, retried, paged = _get_params(session)

        assert [row["id"] for row in rows] == [1, 2]
        assert "salesforceCmsId" in first["fields"].split(",")
        assert "salesforceCmsId" not in retried["fields"].split(",")
        assert paged["fields"] == retried["fields"]

    def test_a_refused_primary_key_stops_the_endpoint(self) -> None:
        session = _session([_response(_refused_field_body("id"), status_code=400)])

        with pytest.raises(PardotQueryRejectedError):
            _collect(session, FakeResumeManager(), endpoint="forms")


class TestResume:
    def test_expired_resume_token_restarts_the_endpoint(self) -> None:
        session = _session(
            [
                _response({"code": 184, "message": "Invalid page token"}, status_code=400),
                _response({"values": [{"id": 1}]}),
            ]
        )
        manager = FakeResumeManager(PardotResumeConfig(next_page_token="stale-token"))

        rows = _collect(session, manager)

        assert [row["id"] for row in rows] == [1]
        assert manager.clear_count == 2  # once when the token is dropped, once on completion
        assert "nextPageToken" not in _get_params(session)[1]

    def test_expired_token_mid_sync_is_not_swallowed(self) -> None:
        session = _session(
            [
                _response({"values": [{"id": 1}], "nextPageToken": "t1"}),
                _response({"message": "page token expired"}, status_code=400),
            ]
        )

        with pytest.raises(PardotPageTokenExpiredError):
            _collect(session, FakeResumeManager())

    def test_other_bad_requests_surface_the_reason_rather_than_restarting(self) -> None:
        # raise_for_status would store the 900-character request URL as the customer's error,
        # which says nothing about why v5 refused it.
        session = _session(
            [
                _response(
                    {"code": 51, "message": "Invalid parameter: Parameter updatedAtAfterOrEqualTo is invalid."},
                    status_code=400,
                )
            ]
        )
        manager = FakeResumeManager(PardotResumeConfig(next_page_token="saved-token"))

        with pytest.raises(PardotQueryRejectedError) as exc_info:
            _collect(session, manager)

        assert "Parameter updatedAtAfterOrEqualTo is invalid" in str(exc_info.value)


class TestAuth:
    def test_repeated_401_surfaces_the_error(self) -> None:
        session = _session(
            [
                _response({"message": "Session expired"}, status_code=401),
                _response({"message": "Session expired"}, status_code=401),
            ]
        )

        with mock.patch(REFRESH_PATCH, return_value="refreshed"), pytest.raises(requests.HTTPError):
            _collect(session, FakeResumeManager())

    def test_401_without_a_refresh_token_asks_for_a_reconnect(self) -> None:
        session = _session([_response({"message": "Session expired"}, status_code=401)])

        with pytest.raises(ValueError, match="Reconnect"):
            _collect(session, FakeResumeManager(), refresh_token=None)

    def test_business_unit_header_and_secrets_redaction_are_wired(self) -> None:
        session = _session([_response({"values": []})])

        with mock.patch(SESSION_PATCH, return_value=session) as make_session:
            list(
                get_rows(
                    endpoint="prospects",
                    api_version="v5",
                    resumable_source_manager=FakeResumeManager(),
                    logger=mock.MagicMock(),
                    **CREDENTIALS,
                )
            )

        kwargs = make_session.call_args.kwargs
        assert kwargs["headers"]["Pardot-Business-Unit-Id"] == CREDENTIALS["business_unit_id"]
        assert set(kwargs["redact_values"]) == {CREDENTIALS["access_token"], CREDENTIALS["refresh_token"]}

    def test_unknown_environment_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            list(
                get_rows(
                    **{**CREDENTIALS, "environment": "staging"},
                    endpoint="prospects",
                    api_version="v5",
                    resumable_source_manager=FakeResumeManager(),
                    logger=mock.MagicMock(),
                )
            )


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [(200, True), (403, False), (500, False)],
    )
    def test_probe_status_maps_to_validity(self, status_code: int, expected_valid: bool) -> None:
        session = _session([_response({"values": []}, status_code=status_code)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(**CREDENTIALS)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    def test_stale_stored_token_is_refreshed_before_giving_up(self) -> None:
        # The stored access token is often older than its lifetime by the time the source is
        # configured, so a 401 must not be reported as a bad connection.
        session = _session(
            [
                _response({"message": "Session expired"}, status_code=401),
                _response({"values": []}),
            ]
        )

        with mock.patch(SESSION_PATCH, return_value=session), mock.patch(REFRESH_PATCH, return_value="refreshed"):
            is_valid, message = validate_credentials(**CREDENTIALS)

        assert (is_valid, message) == (True, None)
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer refreshed"

    def test_failed_refresh_asks_the_user_to_reconnect(self) -> None:
        session = _session([_response({"message": "Session expired"}, status_code=401)])

        with mock.patch(SESSION_PATCH, return_value=session), mock.patch(REFRESH_PATCH, side_effect=requests.HTTPError):
            is_valid, message = validate_credentials(**CREDENTIALS)

        assert is_valid is False
        assert message is not None and "Reconnect" in message

    def test_unknown_environment_is_reported_not_raised(self) -> None:
        is_valid, message = validate_credentials(**{**CREDENTIALS, "environment": "staging"})

        assert is_valid is False
        assert message is not None and "staging" in message


class TestPardotSourceResponse:
    def test_items_are_lazy_until_iterated(self) -> None:
        session = _session([_response({"values": [{"id": 1}]})])
        response = pardot_source(
            **CREDENTIALS,
            endpoint="campaigns",
            api_version="v5",
            resumable_source_manager=FakeResumeManager(),
            logger=mock.MagicMock(),
        )

        with mock.patch(SESSION_PATCH, return_value=session):
            session.get.assert_not_called()
            rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]

        assert rows == [{"id": 1}]
