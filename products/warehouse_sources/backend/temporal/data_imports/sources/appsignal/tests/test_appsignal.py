from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.appsignal.appsignal import (
    APPSIGNAL_GRAPHQL_URL,
    APPSIGNAL_V2_URL,
    AppsignalResumeConfig,
    AppsignalRetryableError,
    _fetch_graphql,
    _fetch_json,
    _fetch_v2,
    _parse_iso,
    _to_epoch,
    _to_iso,
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

    @mock.patch(f"{MODULE}.WINDOW_PAGE_LIMIT", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_over_limit_narrow_window_is_fetched_not_split_forever(self, mock_session):
        # More rows than the page limit inside a span narrower than 2 * MIN_WINDOW_SECONDS.
        # Bisection can't shrink such a window (the right child's `mid - 1` overlap makes it equal
        # to its parent), so it must be fetched directly rather than split endlessly.
        base = self._now() - 10
        rows = [{"id": str(offset), "time": base + offset} for offset in range(3)]
        session = _windowed_session(rows)
        inner_get = session.get.side_effect
        calls = {"n": 0}

        def guarded_get(*args: Any, **kwargs: Any) -> mock.MagicMock:
            calls["n"] += 1
            assert calls["n"] <= 100, "windowed walk failed to terminate"
            return inner_get(*args, **kwargs)

        session.get.side_effect = guarded_get
        mock_session.return_value = session

        manager = _make_manager(AppsignalResumeConfig(window_start=base))
        batches = list(get_rows("token", "app-id", "error_samples", mock.MagicMock(), manager))

        assert {row["id"] for batch in batches for row in batch} == {"0", "1", "2"}

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
            mock.patch.object(_fetch_json.retry, "sleep", lambda _: None),  # type: ignore[attr-defined]
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
            mock.patch.object(_fetch_graphql.retry, "sleep", lambda _: None),  # type: ignore[attr-defined]
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
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(APPSIGNAL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "createdAt", "time", "timestamp", "trace_time"}


def _v2_session(
    graphql: Any = None,
    post: dict[str, Any] | None = None,
    get: dict[str, Any] | None = None,
) -> mock.MagicMock:
    """Fake a session that routes by URL: the GraphQL endpoint, V2 POST paths, V2 GET paths.

    A handler is either a payload or a callable taking the request body and returning one.
    """
    post_handlers, get_handlers = post or {}, get or {}

    def resolve(handler: Any, body: Any) -> Any:
        return handler(body) if callable(handler) else handler

    def do_post(url: str, params: Any = None, json: Any = None, timeout: Any = None) -> mock.MagicMock:
        if url == APPSIGNAL_GRAPHQL_URL:
            return _response(resolve(graphql, json) or {})
        path = url.removeprefix(APPSIGNAL_V2_URL)
        assert path in post_handlers, f"unexpected V2 POST {path}"
        return _response(resolve(post_handlers[path], json))

    def do_get(url: str, params: Any = None, timeout: Any = None) -> mock.MagicMock:
        path = url.removeprefix(APPSIGNAL_V2_URL)
        assert path in get_handlers, f"unexpected V2 GET {path}"
        handler = get_handlers[path]
        if isinstance(handler, int):
            return _response({}, status_code=handler)
        return _response(resolve(handler, None))

    session = mock.MagicMock()
    session.post.side_effect = do_post
    session.get.side_effect = do_get
    return session


_LOG_SOURCES = {"data": {"app": {"logs": {"sources": [{"id": "src-1"}]}}}}


def _at(line: dict[str, Any]) -> datetime:
    parsed = _parse_iso(line["timestamp"])
    assert parsed is not None
    return parsed


def _log_lines_handler(lines: list[dict[str, Any]]):
    """Serve log lines oldest-first from an inclusive keyset cursor, as the V2 endpoint does."""

    def handle(body: dict[str, Any]) -> list[dict[str, Any]]:
        cursor = _parse_iso(body["pagination"]["cursor"]["time"])
        matching = [line for line in lines if cursor is None or _at(line) >= cursor]
        return matching[: body["pagination"]["per_page"]]

    return handle


class TestFetchV2:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_transient_statuses_are_retryable(self, status_code):
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=status_code)

        with (
            mock.patch.object(_fetch_v2.retry, "sleep", lambda _: None),  # type: ignore[attr-defined]
            pytest.raises(AppsignalRetryableError),
        ):
            _fetch_v2(session, "token", "/logs/lines", mock.MagicMock(), body={})

    @pytest.mark.parametrize("status_code", [401, 403, 404, 422])
    def test_client_statuses_are_terminal(self, status_code):
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=status_code)

        with pytest.raises(requests.HTTPError):
            _fetch_v2(session, "token", "/logs/lines", mock.MagicMock(), body={})


class TestAppRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_apps_carry_their_organization(self, mock_session):
        # Only the configured app's organization: a personal token often reaches several, and
        # syncing those would expose apps this connection never named.
        session = _v2_session(
            graphql={
                "data": {
                    "app": {
                        "organization": {
                            "id": "org-1",
                            "name": "Acme",
                            "slug": "acme",
                            "apps": [{"id": "a1", "name": "web"}, {"id": "a2", "name": "api"}],
                        }
                    }
                }
            }
        )
        mock_session.return_value = session

        batches = list(get_rows("token", "app-id", "apps", mock.MagicMock(), _make_manager()))

        assert [(row["id"], row["organizationSlug"]) for row in batches[0]] == [("a1", "acme"), ("a2", "acme")]
        assert session.post.call_args.kwargs["json"]["variables"] == {"appId": "app-id"}

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_missing_app_raises_clear_error(self, mock_session):
        mock_session.return_value = _v2_session(graphql={"data": {"app": None}})

        with pytest.raises(Exception, match="AppSignal app not found"):
            list(get_rows("token", "app-id", "apps", mock.MagicMock(), _make_manager()))


class TestLogLineRows:
    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_boundary_line_is_not_yielded_twice(self, mock_session):
        # The cursor is the last line's timestamp and the endpoint is inclusive of it, so the
        # next page re-serves that line. Without the boundary filter it lands in the table twice.
        lines = [{"id": str(n), "timestamp": f"2026-01-0{n}T00:00:00Z"} for n in (1, 2, 3)]
        mock_session.return_value = _v2_session(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_handler(lines)})

        batches = list(get_rows("token", "app-id", "log_lines", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]

    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_full_page_on_one_instant_steps_past_it_instead_of_looping(self, mock_session):
        # Every line shares a timestamp, so the keyset cursor cannot advance on its own and the
        # walk would re-request the same page forever.
        lines = [{"id": str(n), "timestamp": "2026-01-01T00:00:00Z"} for n in (1, 2, 3)]
        mock_session.return_value = _v2_session(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_handler(lines)})
        logger = mock.MagicMock()

        batches = list(get_rows("token", "app-id", "log_lines", logger, _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2"]
        assert "share timestamp" in logger.warning.call_args.args[0]

    @pytest.mark.parametrize(
        "should_use_incremental_field, watermark, expected_cursor",
        [(False, "2026-01-02T00:00:00Z", None), (True, "2026-01-02T00:00:00Z", "2026-01-01T23:59:59Z")],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_first_page_cursor_follows_the_watermark(
        self, mock_session, should_use_incremental_field, watermark, expected_cursor
    ):
        session = _v2_session(graphql=_LOG_SOURCES, post={"/logs/lines": []})
        mock_session.return_value = session

        list(
            get_rows(
                "token",
                "app-id",
                "log_lines",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=watermark,
            )
        )

        body = session.post.call_args.kwargs["json"]
        assert body["pagination"]["cursor"] == {"time": expected_cursor}
        assert body["source_ids"] == ["src-1"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_app_without_log_sources_makes_no_query(self, mock_session):
        session = _v2_session(graphql={"data": {"app": {"logs": {"sources": []}}}})
        mock_session.return_value = session

        assert list(get_rows("token", "app-id", "log_lines", mock.MagicMock(), _make_manager())) == []
        assert session.post.call_count == 1

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        lines = [{"id": "late", "timestamp": "2026-01-05T00:00:00Z"}]
        session = _v2_session(graphql=_LOG_SOURCES, post={"/logs/lines": _log_lines_handler(lines)})
        mock_session.return_value = session

        manager = _make_manager(AppsignalResumeConfig(cursor_time="2026-01-04T00:00:00Z"))
        list(get_rows("token", "app-id", "log_lines", mock.MagicMock(), manager))

        assert session.post.call_args_list[1].kwargs["json"]["pagination"]["cursor"] == {"time": "2026-01-04T00:00:00Z"}


class TestMetricRows:
    _NAMES_PATH = "/metrics/names/app-id"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_metric_without_type_does_not_abort_the_catalog(self, mock_session):
        # type_and_tags 404s when a metric stops reporting between the two calls; the rest of
        # the catalog must still sync.
        mock_session.return_value = _v2_session(
            get={
                self._NAMES_PATH: ["cpu", "gone"],
                "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": [["hostname"]]},
                "/metrics/type_and_tags/app-id/gone": 404,
            }
        )

        batches = list(get_rows("token", "app-id", "metric_names", mock.MagicMock(), _make_manager()))

        assert batches[0] == [
            {"name": "cpu", "metric_type": "gauge", "available_tags": [["hostname"]]},
            {"name": "gone", "metric_type": None, "available_tags": []},
        ]

    @mock.patch(f"{MODULE}.METRICS_INITIAL_LOOKBACK_SECONDS", 3600)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_timeseries_selectors_use_the_field_for_the_metric_type(self, mock_session):
        session = _v2_session(
            get={
                self._NAMES_PATH: ["cpu", "requests", "latency", "unknown"],
                "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": [["hostname"]]},
                "/metrics/type_and_tags/app-id/requests": {"metric_type": "counter", "available_tags": []},
                "/metrics/type_and_tags/app-id/latency": {
                    "metric_type": "measurement",
                    "available_tags": [{"namespace": "web"}],
                },
                "/metrics/type_and_tags/app-id/unknown": {"metric_type": "mystery", "available_tags": []},
            },
            post={"/metrics/timeseries": {"series": []}},
        )
        mock_session.return_value = session

        list(get_rows("token", "app-id", "metric_timeseries", mock.MagicMock(), _make_manager()))

        body = session.post.call_args.kwargs["json"]
        assert body["resolution"] == "HOURLY"
        assert body["select"] == [
            {"name": "cpu", "field": "gauge", "tags": {"hostname": "*"}},
            {"name": "requests", "field": "counter", "tags": {}},
            {"name": "latency", "field": "mean", "tags": {"namespace": "*"}},
        ]

    @mock.patch(f"{MODULE}.METRICS_INITIAL_LOOKBACK_SECONDS", 3600)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_series_are_flattened_into_ascending_point_rows(self, mock_session):
        # Points restart at the window's start for every metric, so a batch built straight from
        # the response order is not ascending and would corrupt the asc watermark.
        mock_session.return_value = _v2_session(
            get={
                self._NAMES_PATH: ["cpu"],
                "/metrics/type_and_tags/app-id/cpu": {"metric_type": "gauge", "available_tags": []},
            },
            post={
                "/metrics/timeseries": {
                    "series": [
                        {
                            "id": "cpu/host=b/gauge",
                            "name": "cpu",
                            "field": "gauge",
                            "tags": {"host": "b"},
                            "data": [{"timestamp": "2026-01-01T02:00:00Z", "value": 4.0}],
                        },
                        {
                            "id": "cpu/host=a/gauge",
                            "name": "cpu",
                            "field": "gauge",
                            "tags": {"host": "a"},
                            "data": [{"timestamp": "2026-01-01T01:00:00Z", "value": 1.0}],
                        },
                    ]
                }
            },
        )

        batches = list(get_rows("token", "app-id", "metric_timeseries", mock.MagicMock(), _make_manager()))

        assert [(row["series_id"], row["timestamp"], row["value"]) for row in batches[0]] == [
            ("cpu/host=a/gauge", "2026-01-01T01:00:00Z", 1.0),
            ("cpu/host=b/gauge", "2026-01-01T02:00:00Z", 4.0),
        ]


def _traces_handler(traces: list[dict[str, Any]]):
    """Serve traces inside the requested window, truncated at `per_page` like the V2 endpoint."""

    def handle(body: dict[str, Any]) -> list[dict[str, Any]]:
        matching = [trace for trace in traces if body["from"] <= trace["time"] <= body["to"]]
        return matching[: body["pagination"]["per_page"]]

    return handle


class TestTraceRows:
    def _traces(self, count: int) -> list[dict[str, Any]]:
        base = int(datetime.now(UTC).timestamp()) - 3000
        return [
            {"trace_id": str(offset), "site_id": "app-id", "time": _to_iso(base + offset * 100)}
            for offset in range(count)
        ]

    @mock.patch(f"{MODULE}.V2_PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_full_response_splits_the_window_until_every_trace_is_reached(self, mock_session):
        # The response is capped at per_page and the cursor carries no position, so a full
        # response means truncation. Without the split the extra traces never sync.
        traces = self._traces(5)
        mock_session.return_value = _v2_session(
            post={
                "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                "/tracing/traces/performance": _traces_handler(traces),
            }
        )

        batches = list(get_rows("token", "app-id", "performance_traces", mock.MagicMock(), _make_manager()))

        rows = [row for batch in batches for row in batch]
        assert {row["trace_id"] for row in rows} == {"0", "1", "2", "3", "4"}
        for batch in batches:
            assert [row["time"] for row in batch] == sorted(row["time"] for row in batch)

    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_spans_carry_the_parent_trace_time(self, mock_session):
        traces = self._traces(2)
        mock_session.return_value = _v2_session(
            post={
                "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                "/tracing/traces/performance": _traces_handler(traces),
                "/tracing/trace": lambda body: [{"span_id": f"s-{body['trace_id']}", "trace_id": body["trace_id"]}],
            }
        )

        batches = list(get_rows("token", "app-id", "trace_spans", mock.MagicMock(), _make_manager()))

        assert [(row["span_id"], row["trace_time"]) for batch in batches for row in batch] == [
            ("s-0", traces[0]["time"]),
            ("s-1", traces[1]["time"]),
        ]

    @mock.patch(f"{MODULE}.MAX_SPAN_TRACES_PER_SYNC", 1)
    @mock.patch(f"{MODULE}.TRACES_INITIAL_LOOKBACK_SECONDS", 3600)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_span_cap_stops_the_sweep_and_checkpoints_the_last_trace(self, mock_session):
        traces = self._traces(3)
        mock_session.return_value = _v2_session(
            post={
                "/tracing/actions": [{"namespace": "web", "action": "UsersController#show"}],
                "/tracing/traces/performance": _traces_handler(traces),
                "/tracing/trace": lambda body: [{"span_id": f"s-{body['trace_id']}", "trace_id": body["trace_id"]}],
            }
        )
        manager = _make_manager()

        batches = list(get_rows("token", "app-id", "trace_spans", mock.MagicMock(), manager))

        # Traces are handled oldest-first, so stopping early leaves the rest for the next sync.
        assert [row["span_id"] for batch in batches for row in batch] == ["s-0"]
        assert manager.save_state.call_args.args[0].window_start == _to_epoch(traces[0]["time"])
