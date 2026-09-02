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
    PAGE_SIZE,
    PardotPageTokenExpiredError,
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
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats_cursor_values(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_converts_non_utc_offsets(self) -> None:
        naive = datetime.fromisoformat("2024-01-02T05:04:05+02:00")

        assert _format_datetime(naive) == "2024-01-02T03:04:05Z"


class TestBuildQueryParams:
    def test_full_refresh_sorts_on_the_endpoint_default(self) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS["prospects"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params["orderBy"] == "id"
        assert params["limit"] == PAGE_SIZE
        assert "id" in params["fields"].split(",")
        assert not any(key.endswith("AfterOrEqualTo") for key in params)

    def test_incremental_filters_and_sorts_on_the_chosen_cursor(self) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS["prospects"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            incremental_field="updatedAt",
        )

        assert params["orderBy"] == "updatedAt"
        assert params["updatedAtAfterOrEqualTo"] == "2024-05-01T00:00:00Z"

    def test_first_incremental_run_sorts_on_the_cursor_without_filtering(self) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS["visits"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="createdAt",
        )

        assert params["orderBy"] == "createdAt"
        assert "createdAtAfterOrEqualTo" not in params

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

    def test_endpoint_without_documented_sort_omits_order_by(self) -> None:
        params = _build_query_params(
            PARDOT_ENDPOINTS["forms"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "orderBy" not in params


class TestPagination:
    def test_walks_pages_until_the_token_runs_out(self) -> None:
        session = _session(
            [
                _response({"values": [{"id": 1}], "nextPageToken": "t1"}),
                _response({"values": [{"id": 2}], "nextPageToken": "t2"}),
                _response({"values": [{"id": 3}], "nextPageToken": None}),
            ]
        )
        manager = FakeResumeManager()

        rows = _collect(session, manager)

        assert [row["id"] for row in rows] == [1, 2, 3]

    def test_page_token_requests_drop_every_param_but_fields(self) -> None:
        session = _session(
            [
                _response({"values": [{"id": 1}], "nextPageToken": "t1"}),
                _response({"values": [{"id": 2}]}),
            ]
        )

        _collect(session, FakeResumeManager())
        first, second = _get_params(session)

        assert first["limit"] == PAGE_SIZE
        assert second == {"fields": first["fields"], "nextPageToken": "t1"}

    def test_state_is_saved_per_page_and_cleared_when_the_endpoint_completes(self) -> None:
        session = _session(
            [
                _response({"values": [{"id": 1}], "nextPageToken": "t1"}),
                _response({"values": [{"id": 2}], "nextPageToken": None}),
            ]
        )
        manager = FakeResumeManager()

        _collect(session, manager)

        assert [state.next_page_token for state in manager.saved] == ["t1"]
        assert manager.clear_count == 1

    def test_empty_page_yields_nothing(self) -> None:
        session = _session([_response({"values": [], "nextPageToken": None})])

        assert _collect(session, FakeResumeManager()) == []

    def test_missing_values_key_is_treated_as_an_empty_page(self) -> None:
        session = _session([_response({"nextPageToken": None})])

        assert _collect(session, FakeResumeManager()) == []


class TestResume:
    def test_resumes_from_the_saved_page_token(self) -> None:
        session = _session([_response({"values": [{"id": 9}]})])
        manager = FakeResumeManager(PardotResumeConfig(next_page_token="saved-token"))

        rows = _collect(session, manager)

        assert [row["id"] for row in rows] == [9]
        assert _get_params(session)[0]["nextPageToken"] == "saved-token"

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

    def test_other_bad_requests_are_raised_rather_than_restarted(self) -> None:
        session = _session([_response({"message": "Invalid field name"}, status_code=400)])
        manager = FakeResumeManager(PardotResumeConfig(next_page_token="saved-token"))

        with pytest.raises(requests.HTTPError):
            _collect(session, manager)


class TestAuth:
    def test_the_integration_token_is_used_as_is(self) -> None:
        session = _session([_response({"values": []})])

        _collect(session, FakeResumeManager())

        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer access"

    def test_expired_access_token_is_refreshed_once(self) -> None:
        session = _session(
            [
                _response({"message": "Session expired"}, status_code=401),
                _response({"values": [{"id": 1}]}),
            ]
        )

        with mock.patch(REFRESH_PATCH, return_value="refreshed") as refresh:
            rows = _collect(session, FakeResumeManager())

        assert [row["id"] for row in rows] == [1]
        # capture=False keeps the refresh request body (refresh token, shared client secret) and
        # its minted-access-token response out of HTTP sample capture.
        refresh.assert_called_once_with(CREDENTIALS["refresh_token"], CREDENTIALS["instance_url"], capture=False)
        assert session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer refreshed"

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

    def test_every_request_path_disables_http_sample_capture(self) -> None:
        # Prospect/visitor bodies carry PII the name-based scrubber can't redact, so both the
        # sync and credential-validation paths must build capture-disabled sessions.
        pull_session = _session([_response({"values": []})])
        validate_session = _session([_response({"values": []}, status_code=200)])

        with mock.patch(SESSION_PATCH) as make_session:
            make_session.return_value = pull_session
            list(
                get_rows(
                    endpoint="prospects",
                    api_version="v5",
                    resumable_source_manager=FakeResumeManager(),
                    logger=mock.MagicMock(),
                    **CREDENTIALS,
                )
            )
            make_session.return_value = validate_session
            validate_credentials(**CREDENTIALS)

        assert make_session.call_count == 2
        assert all(call.kwargs["capture"] is False for call in make_session.call_args_list)

    @pytest.mark.parametrize(
        "environment, expected_host",
        [
            ("production", "https://pi.pardot.com"),
            ("sandbox", "https://pi.demo.pardot.com"),
        ],
    )
    def test_environment_selects_the_api_host(self, environment: str, expected_host: str) -> None:
        session = _session([_response({"values": []})])
        credentials = {**CREDENTIALS, "environment": environment}

        with mock.patch(SESSION_PATCH, return_value=session):
            list(
                get_rows(
                    endpoint="prospects",
                    api_version="v5",
                    resumable_source_manager=FakeResumeManager(),
                    logger=mock.MagicMock(),
                    **credentials,
                )
            )

        assert session.get.call_args.args[0] == f"{expected_host}/api/v5/objects/prospects"

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
    def test_partitions_high_volume_tables_on_creation_time(self) -> None:
        response = pardot_source(
            **CREDENTIALS,
            endpoint="visitor_activities",
            api_version="v5",
            resumable_source_manager=FakeResumeManager(),
            logger=mock.MagicMock(),
        )

        assert response.name == "visitor_activities"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
        assert response.sort_mode == "asc"

    def test_unpartitioned_table_declares_no_partition_keys(self) -> None:
        response = pardot_source(
            **CREDENTIALS,
            endpoint="campaigns",
            api_version="v5",
            resumable_source_manager=FakeResumeManager(),
            logger=mock.MagicMock(),
        )

        assert response.partition_mode is None
        assert response.partition_keys is None

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
