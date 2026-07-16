from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal import (
    AppsignalResumeConfig,
    AppsignalRetryableError,
    _fetch_graphql,
    _fetch_json,
    _to_epoch,
    appsignal_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.settings import (
    APPSIGNAL_ENDPOINTS,
    ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal"


def _make_manager(resume_state: AppsignalResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200, url: str = "https://appsignal.com") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.reason = {200: "OK", 401: "Unauthorized", 404: "Not Found"}.get(status_code, "Error")
    response.url = url
    response.json.return_value = payload
    return response


def _windowed_session(rows: list[dict[str, Any]], cursor: str = "time") -> mock.MagicMock:
    """Fake a legacy REST endpoint: `since`/`from` and `before`/`to` bound the rows (both
    inclusive), `count_only` returns the matching count, `limit` caps returned rows. Rows are
    served newest-first to prove the walk doesn't rely on server ordering."""

    def get(url: str, params: dict[str, Any] | None = None, timeout: Any = None) -> mock.MagicMock:
        params = params or {}
        since = params.get("since", params.get("from", 0))
        before = params.get("before", params.get("to", 2**62))
        matching = [row for row in rows if since <= row[cursor] <= before]
        if params.get("count_only"):
            return _response({"count": len(matching)})
        matching = sorted(matching, key=lambda row: row[cursor], reverse=True)
        return _response({"log_entries": matching[: int(params["limit"])], "markers": matching[: int(params["limit"])]})

    session = mock.MagicMock()
    session.get.side_effect = get
    return session


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-date", None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (404, False), (500, False)])
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)
        assert validate_credentials("token", "app-id") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token", "app-id") is False


class TestWindowedRows:
    def _now(self) -> int:
        return int(datetime.now(UTC).timestamp())

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_single_window_yields_sorted_rows(self, mock_session):
        base = self._now() - 10_000
        rows = [{"id": "b", "time": base + 50}, {"id": "a", "time": base + 10}]
        mock_session.return_value = _windowed_session(rows)

        manager = _make_manager()
        batches = list(get_rows("token", "app-id", "error_samples", mock.MagicMock(), manager))

        assert len(batches) == 1
        # Server returned newest-first; the walk re-sorts ascending so asc watermarking holds.
        assert [row["id"] for row in batches[0]] == ["a", "b"]
        manager.save_state.assert_called_once()

    @mock.patch(f"{MODULE}.WINDOW_PAGE_LIMIT", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_bisection_fetches_every_row_when_window_overflows(self, mock_session):
        base = self._now() - 100_000
        rows = [{"id": str(offset), "time": base + offset * 1000} for offset in range(7)]
        mock_session.return_value = _windowed_session(rows)

        manager = _make_manager()
        batches = list(get_rows("token", "app-id", "error_samples", mock.MagicMock(), manager))

        yielded_ids = {row["id"] for batch in batches for row in batch}
        assert yielded_ids == {str(offset) for offset in range(7)}
        for batch in batches:
            assert [row["time"] for row in batch] == sorted(row["time"] for row in batch)
        # State advances after each yielded window.
        assert manager.save_state.call_count == len(batches)

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_incremental_walk_starts_just_below_watermark(self, mock_session):
        base = self._now() - 10_000
        rows = [{"id": "old", "time": base}, {"id": "new", "time": base + 5000}]
        mock_session.return_value = _windowed_session(rows)

        manager = _make_manager()
        batches = list(
            get_rows(
                "token",
                "app-id",
                "error_samples",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=base + 4000,
            )
        )

        assert {row["id"] for batch in batches for row in batch} == {"new"}
        first_params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        # 1s overlap below the watermark: bound inclusivity is undocumented upstream.
        assert first_params["since"] == base + 4000 - 1

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_window_start(self, mock_session):
        base = self._now() - 10_000
        rows = [{"id": "done", "time": base}, {"id": "pending", "time": base + 5000}]
        mock_session.return_value = _windowed_session(rows)

        manager = _make_manager(AppsignalResumeConfig(window_start=base + 1000))
        batches = list(get_rows("token", "app-id", "error_samples", mock.MagicMock(), manager))

        assert {row["id"] for batch in batches for row in batch} == {"pending"}

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_range_yields_nothing_and_saves_no_state(self, mock_session):
        mock_session.return_value = _windowed_session([])

        manager = _make_manager()
        assert list(get_rows("token", "app-id", "error_samples", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_deploy_markers_use_from_to_params_and_kind_filter(self, mock_session):
        base = self._now() - 10_000
        rows = [{"id": "m1", "created_at": base + 10}]
        mock_session.return_value = _windowed_session(rows, cursor="created_at")

        manager = _make_manager()
        batches = list(get_rows("token", "app-id", "deploy_markers", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["m1"]
        params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        assert params["kind"] == "deploy"
        assert "from" in params and "to" in params
        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert url == "https://appsignal.com/api/app-id/markers.json"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_auth_failure_error_message_does_not_leak_token(self, mock_session):
        secret = "super-secret-token-value"
        response = _response(
            {}, status_code=401, url=f"https://appsignal.com/api/app-id/samples/errors.json?token={secret}"
        )
        mock_session.return_value.get.return_value = response

        with pytest.raises(requests.HTTPError) as exc_info:
            list(get_rows(secret, "app-id", "error_samples", mock.MagicMock(), _make_manager()))

        message = str(exc_info.value)
        assert secret not in message
        assert message.startswith("401 Client Error: Unauthorized for url: https://appsignal.com")

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_transport_error_message_does_not_leak_token(self, mock_session):
        # requests raises ConnectionError before any response exists, with the full request URL —
        # token included — in its message. That path is not covered by the status-error scrubbing.
        secret = "super-secret-token-value"
        mock_session.return_value.get.side_effect = requests.ConnectionError(
            f"HTTPSConnectionPool(host='appsignal.com', port=443): Max retries exceeded with url: "
            f"/api/app-id/samples/errors.json?token={secret} (Caused by NewConnectionError())"
        )

        with (
            mock.patch.object(_fetch_json.retry, "sleep", lambda _: None),
            pytest.raises(AppsignalRetryableError) as exc_info,
        ):
            list(get_rows(secret, "app-id", "error_samples", mock.MagicMock(), _make_manager()))

        assert secret not in str(exc_info.value)


class TestIncidentRows:
    def _graphql_session(self, pages: list[list[dict[str, Any]]], field: str) -> mock.MagicMock:
        session = mock.MagicMock()
        session.post.side_effect = [_response({"data": {"app": {field: page}}}) for page in pages]
        return session

    @mock.patch(f"{MODULE}.GRAPHQL_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_pages_by_offset_until_short_page(self, mock_session):
        pages = [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        mock_session.return_value = self._graphql_session(pages, "exceptionIncidents")

        manager = _make_manager()
        batches = list(get_rows("token", "app-id", "exception_incidents", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        offsets = [call.kwargs["json"]["variables"]["offset"] for call in mock_session.return_value.post.call_args_list]
        assert offsets == [0, 2]
        # State saved only after the full first page — the short page ends the walk.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == 2

    @mock.patch(f"{MODULE}.GRAPHQL_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value = self._graphql_session([[{"id": "5"}]], "performanceIncidents")

        manager = _make_manager(AppsignalResumeConfig(offset=4))
        list(get_rows("token", "app-id", "performance_incidents", mock.MagicMock(), manager))

        variables = mock_session.return_value.post.call_args_list[0].kwargs["json"]["variables"]
        assert variables["offset"] == 4
        assert variables["appId"] == "app-id"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_missing_app_raises_clear_error(self, mock_session):
        session = mock.MagicMock()
        session.post.return_value = _response({"data": {"app": None}})
        mock_session.return_value = session

        with pytest.raises(Exception, match="AppSignal app not found"):
            list(get_rows("token", "app-id", "exception_incidents", mock.MagicMock(), _make_manager()))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_graphql_errors_raise(self, mock_session):
        session = mock.MagicMock()
        session.post.return_value = _response({"errors": [{"message": "Field 'nope' doesn't exist"}]})
        mock_session.return_value = session

        with pytest.raises(Exception, match="Field 'nope' doesn't exist"):
            list(get_rows("token", "app-id", "exception_incidents", mock.MagicMock(), _make_manager()))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_transport_error_message_does_not_leak_token(self, mock_session):
        secret = "super-secret-token-value"
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError(
            f"HTTPSConnectionPool(host='appsignal.com', port=443): Max retries exceeded with url: "
            f"/graphql?token={secret} (Caused by NewConnectionError())"
        )
        mock_session.return_value = session

        with (
            mock.patch.object(_fetch_graphql.retry, "sleep", lambda _: None),
            pytest.raises(AppsignalRetryableError) as exc_info,
        ):
            list(get_rows(secret, "app-id", "exception_incidents", mock.MagicMock(), _make_manager()))

        assert secret not in str(exc_info.value)


class TestAppsignalSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = APPSIGNAL_ENDPOINTS[endpoint]
        response = appsignal_source("token", "app-id", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(APPSIGNAL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "createdAt", "time"}
