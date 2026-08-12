import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.settings import (
    ENDPOINTS,
    SHUTTERSTOCK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.shutterstock import (
    ShutterstockAuth,
    ShutterstockResumeConfig,
    _format_start_date,
    check_endpoint_access,
    get_rows,
    shutterstock_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# The credential/scope probes build their own tracked session in the shutterstock module.
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.shutterstock.make_tracked_session"
)

BASIC_AUTH = ShutterstockAuth(consumer_key="ck", consumer_secret="cs")
TOKEN_AUTH = ShutterstockAuth(access_token="tok")


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _page(items: list[dict[str, Any]]) -> Response:
    return _response({"data": items, "page": 1, "per_page": 100, "total_count": 999})


def _make_manager(resume_state: ShutterstockResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it
    after the run shows only the final state — snapshot a copy per request instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _collect(
    endpoint: str,
    responses: list[Response],
    MockSession: mock.MagicMock,
    manager: mock.MagicMock | None = None,
    auth: ShutterstockAuth = BASIC_AUTH,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], mock.MagicMock]:
    session = MockSession.return_value
    snapshots = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    batches = list(get_rows(auth, endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs))
    return batches, snapshots, manager


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, 123456, tzinfo=UTC), "2026-03-04T22:13:20+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("2026-03-04T22:13:20+00:00", "2026-03-04T22:13:20+00:00"),
            ("", None),
        ],
    )
    def test_format_start_date(self, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestCredentialProbes:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(PROBE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials(BASIC_AUTH) is expected

    @mock.patch(PROBE_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials(BASIC_AUTH) is False

    @pytest.mark.parametrize(
        "endpoint, status_code, expect_reason, expect_scope",
        [
            ("image_licenses", 200, False, None),
            ("image_licenses", 403, True, "licenses.view"),
            ("image_collections", 401, True, "collections.view"),
            ("subscriptions", 403, True, "purchases.view"),
            ("images_updated", 401, True, None),
            # A throttle or server blip is not a missing scope — the table stays selectable.
            ("image_licenses", 429, False, None),
            ("image_licenses", 500, False, None),
        ],
    )
    @mock.patch(PROBE_SESSION_PATCH)
    def test_check_endpoint_access(
        self,
        mock_session: mock.MagicMock,
        endpoint: str,
        status_code: int,
        expect_reason: bool,
        expect_scope: str | None,
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        reason = check_endpoint_access(BASIC_AUTH, endpoint)

        if not expect_reason:
            assert reason is None
        else:
            assert reason is not None
            if expect_scope:
                assert expect_scope in reason


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_empty_page_and_checkpoints(self, MockSession: mock.MagicMock) -> None:
        batches, snapshots, manager = _collect(
            "images_updated",
            [
                _page([{"id": "1"}, {"id": "2"}]),
                _page([]),
            ],
            MockSession,
        )

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["per_page"] == 500
        assert snapshots[1]["params"]["page"] == 2
        # State saved once (after page 1, pointing at page 2); the empty page ends the run.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == ShutterstockResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, snapshots, _ = _collect(
            "images_updated",
            [_page([])],
            MockSession,
            manager=_make_manager(ShutterstockResumeConfig(page=7)),
        )

        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_uses_consumer_key_and_secret(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect("images_updated", [_page([])], MockSession, auth=BASIC_AUTH)

        assert snapshots[0]["auth"].username == "ck"
        assert snapshots[0]["auth"].password == "cs"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_access_token_uses_bearer_auth(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect("image_licenses", [_page([])], MockSession, auth=TOKEN_AUTH)

        assert snapshots[0]["auth"].token == "tok"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_carries_watermark_and_ascending_sort(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "image_licenses",
            [_page([])],
            MockSession,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert snapshots[0]["params"]["start_date"] == "2026-01-01T00:00:00+00:00"
        assert snapshots[0]["params"]["sort"] == "oldest"
        assert snapshots[0]["params"]["per_page"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_licenses_full_refresh_fetches_full_history(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "image_licenses",
            [_page([])],
            MockSession,
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # No lookback default for license history: a full refresh walks all of it, still
        # ascending so pages don't skip/duplicate rows inserted mid-sync.
        assert "start_date" not in snapshots[0]["params"]
        assert snapshots[0]["params"]["sort"] == "oldest"

    @freeze_time("2026-01-31 00:00:00")
    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_updated_feed_defaults_to_bounded_lookback_without_watermark(
        self, MockSession: mock.MagicMock, should_use_incremental_field: bool
    ) -> None:
        # The updated feeds return only the last hour when no start_date is passed, so an
        # unwatermarked sync must bound the window explicitly or it silently syncs nothing.
        _, snapshots, _ = _collect(
            "images_updated",
            [_page([])],
            MockSession,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=None,
        )

        assert snapshots[0]["params"]["start_date"] == "2026-01-01T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_makes_a_single_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        batches, snapshots, manager = _collect(
            "subscriptions",
            [_page([{"id": "s1"}, {"id": "s2"}])],
            MockSession,
        )

        assert session.send.call_count == 1
        assert [item["id"] for batch in batches for item in batch] == ["s1", "s2"]
        assert "page" not in snapshots[0]["params"]
        assert "per_page" not in snapshots[0]["params"]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_reads_as_end_of_data(self, MockSession: mock.MagicMock) -> None:
        batches, _, manager = _collect("images_updated", [_response({"message": "no results"})], MockSession)

        assert batches == []
        manager.save_state.assert_not_called()


class TestShutterstockSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = SHUTTERSTOCK_ENDPOINTS[endpoint]
        response = shutterstock_source(
            BASIC_AUTH, endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SHUTTERSTOCK_ENDPOINTS.values()))
    def test_incremental_endpoints_sort_ascending_on_their_cursor(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.cursor_field is not None
            assert config.incremental_fields
            assert config.incremental_fields[0]["field"] == config.cursor_field
