import json
import time
import threading
from typing import Any
from urllib.parse import urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics import (
    appdynamics as appdynamics_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.appdynamics import (
    AppdynamicsAuth,
    AppdynamicsClient,
    AppdynamicsError,
    AppdynamicsResumeConfig,
    appdynamics_source,
    get_rows,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    APPDYNAMICS_ENDPOINTS,
    MAX_METRIC_PATHS,
)

BASE_URL = "https://acme.saas.appdynamics.com"
MILLIS_PER_DAY = 24 * 60 * 60 * 1000
# 2024-01-31T00:00:00Z, used as the frozen "now" for window tests
FROZEN_NOW_MS = 1706659200000

BASIC_AUTH = AppdynamicsAuth(account_name="acme", username="user", password="pass")
OAUTH_AUTH = AppdynamicsAuth(account_name="acme", api_client_name="client", api_client_secret="secret")


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else []
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json

    def iter_content(self, chunk_size: int = 1) -> Any:
        body = self.text.encode() if self.text else json.dumps(self._json).encode()
        yield body

    def close(self) -> None:
        pass

    def raise_for_status(self) -> None:
        if not self.ok:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=response)


class _TrickleResponse:
    """A 200 response whose body never stops arriving, to exercise the download deadline.

    Yields small chunks with a gap shorter than any read-idle timeout, so only the hard
    wall-clock deadline (which closes the connection) can end the read.
    """

    status_code = 200
    text = ""

    def __init__(self) -> None:
        self._closed = False

    @property
    def ok(self) -> bool:
        return True

    def iter_content(self, chunk_size: int = 1) -> Any:
        while not self._closed:
            time.sleep(0.02)
            yield b"x" * 8
        raise OSError("connection closed")

    def close(self) -> None:
        self._closed = True

    def json(self) -> Any:
        return {}


class _HeaderTrickleSession:
    """A session whose GET never returns response headers, to exercise the pre-response deadline.

    Models a controller trickling the status line/headers slower than any read-idle timeout: the
    call blocks until the deadline tears the session down, so only the pre-response wall-clock
    deadline can free the worker.
    """

    def __init__(self) -> None:
        self._closed = threading.Event()

    def get(self, url: str, params: dict[str, Any], **kwargs: Any) -> Any:
        self._closed.wait()
        raise OSError("connection closed")

    def close(self) -> None:
        self._closed.set()


class FakeResumeManager:
    def __init__(self, initial: AppdynamicsResumeConfig | None = None):
        self.state = initial
        self.saved: list[AppdynamicsResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AppdynamicsResumeConfig | None:
        return self.state

    def save_state(self, data: AppdynamicsResumeConfig) -> None:
        self.state = data
        self.saved.append(data)


class FakeSession:
    """Routes GETs by URL path and records every request's path + params."""

    def __init__(self, responder: Any = None, post_response: FakeResponse | None = None):
        self._responder = responder or (lambda path, params: FakeResponse(json_data=[]))
        self._post_response = post_response or FakeResponse(json_data={"access_token": "tok", "expires_in": 300})
        self.get_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any], **kwargs: Any) -> FakeResponse:
        path = urlparse(url).path
        self.get_calls.append((path, params, kwargs))
        return self._responder(path, params)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append(kwargs)
        return self._post_response


def _patch_session(session: Any) -> Any:
    return mock.patch.object(appdynamics_module, "make_tracked_session", return_value=session)


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("full_url", "https://acme.saas.appdynamics.com", "https://acme.saas.appdynamics.com"),
            ("trailing_slash", "https://acme.saas.appdynamics.com/", "https://acme.saas.appdynamics.com"),
            ("bare_account", "acme", "https://acme.saas.appdynamics.com"),
            ("host_no_scheme", "acme.saas.appdynamics.com", "https://acme.saas.appdynamics.com"),
            ("http_upgraded", "http://acme.saas.appdynamics.com", "https://acme.saas.appdynamics.com"),
            (
                "strips_path_and_query",
                "https://acme.saas.appdynamics.com/controller?x=1",
                "https://acme.saas.appdynamics.com",
            ),
            ("strips_userinfo", "https://u:p@acme.saas.appdynamics.com", "https://acme.saas.appdynamics.com"),
            ("keeps_port", "https://onprem.example.com:8090", "https://onprem.example.com:8090"),
            ("whitespace", "  acme  ", "https://acme.saas.appdynamics.com"),
        ]
    )
    def test_normalize(self, _name: str, value: str, expected: str) -> None:
        assert normalize_host(value) == expected

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_host("")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_accepted", 403, None, True),
            ("forbidden_for_schema_rejected", 403, "applications", False),
            ("unexpected_status", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_valid: bool) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(status_code=status))
        with _patch_session(session):
            valid, _ = validate_credentials(BASE_URL, BASIC_AUTH, team_id=1, schema_name=schema_name)
        assert valid is expected_valid

    def test_oauth_exchanges_token_before_probe(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(json_data=[]))
        with _patch_session(session):
            valid, error = validate_credentials(BASE_URL, OAUTH_AUTH, team_id=1)

        assert (valid, error) == (True, None)
        assert session.post_calls[0]["data"]["client_id"] == "client@acme"
        _, _, kwargs = session.get_calls[0]
        assert kwargs["headers"]["Authorization"] == "Bearer tok"

    def test_oauth_rejected_token_fails_validation(self) -> None:
        session = FakeSession(post_response=FakeResponse(status_code=401, json_data={}))
        with _patch_session(session):
            valid, error = validate_credentials(BASE_URL, OAUTH_AUTH, team_id=1)

        assert valid is False
        assert error is not None
        assert session.get_calls == []

    def test_invalid_host(self) -> None:
        valid, error = validate_credentials("", BASIC_AUTH, team_id=1)
        assert valid is False
        assert error is not None

    def test_network_error_is_handled(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(appdynamics_module, "make_tracked_session", return_value=session):
            valid, error = validate_credentials(BASE_URL, BASIC_AUTH, team_id=1)
        assert valid is False
        assert error is not None

    def test_redirects_are_never_followed(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(status_code=200))
        with _patch_session(session):
            validate_credentials(BASE_URL, BASIC_AUTH, team_id=1)
        _, _, kwargs = session.get_calls[0]
        assert kwargs["allow_redirects"] is False
        # The probe only needs the status code, so it must stream rather than buffer a body.
        assert kwargs["stream"] is True


class TestAppdynamicsClient:
    def test_basic_auth_sends_account_qualified_username(self) -> None:
        session = FakeSession()
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        client.get_json("/controller/rest/applications", {})

        _, params, kwargs = session.get_calls[0]
        assert kwargs["auth"] == ("user@acme", "pass")
        assert "Authorization" not in kwargs["headers"]
        assert params["output"] == "JSON"

    def test_oauth_token_cached_until_expiry(self) -> None:
        session = FakeSession()
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, OAUTH_AUTH, mock.MagicMock())

        with freeze_time("2024-01-31T00:00:00Z") as frozen:
            client.get_json("/controller/rest/applications", {})
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 1

            frozen.move_to("2024-01-31T00:10:00Z")  # past the 5 min TTL
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 2

        for _, _, kwargs in session.get_calls:
            assert kwargs["headers"]["Authorization"] == "Bearer tok"
            assert kwargs["auth"] is None

    def test_short_lived_token_is_refreshed_before_its_ttl(self) -> None:
        # A short TTL must not be cached past expiry: the refresh margin is capped at half the
        # TTL, so a 10s token is re-fetched well before 10s rather than trusted for a fixed 30s.
        session = FakeSession(post_response=FakeResponse(json_data={"access_token": "tok", "expires_in": 10}))
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, OAUTH_AUTH, mock.MagicMock())

        with freeze_time("2024-01-31T00:00:00Z") as frozen:
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 1
            frozen.move_to("2024-01-31T00:00:06Z")  # past the 5s cache window (10 - min(60, 5))
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 2

    def test_oauth_failure_raises_non_retryable(self) -> None:
        session = FakeSession(post_response=FakeResponse(status_code=400, json_data={}))
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, OAUTH_AUTH, mock.MagicMock())
        with pytest.raises(AppdynamicsError):
            client.get_json("/controller/rest/applications", {})

    def test_redirect_raises_non_retryable(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(status_code=302))
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        with pytest.raises(AppdynamicsError):
            client.get_json("/controller/rest/applications", {})

    def test_client_error_raises_http_error(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(status_code=401))
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        with pytest.raises(requests.HTTPError):
            client.get_json("/controller/rest/applications", {})

    def test_response_body_is_streamed(self) -> None:
        session = FakeSession()
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        client.get_json("/controller/rest/applications", {})
        _, _, kwargs = session.get_calls[0]
        assert kwargs["stream"] is True

    def test_oversized_response_is_rejected(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(json_data=[{"a": "b" * 100}]))
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        # Non-retryable: a host that overflows the cap won't stop on a retry.
        with mock.patch.object(appdynamics_module, "MAX_RESPONSE_BYTES", 10):
            with pytest.raises(AppdynamicsError):
                client.get_json("/controller/rest/applications", {})

    def test_download_deadline_interrupts_trickled_body(self) -> None:
        # A trickled body never idle-times-out, so only the wall-clock deadline can end it.
        session = FakeSession(responder=lambda path, params: _TrickleResponse())
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        with mock.patch.object(appdynamics_module, "MAX_DOWNLOAD_SECONDS", 0.2):
            started = time.monotonic()
            with pytest.raises(AppdynamicsError):
                client.get_json("/controller/rest/applications", {})
            assert time.monotonic() - started < 5

    def test_header_deadline_interrupts_trickled_headers(self) -> None:
        # Headers that never arrive keep `session.get` blocked before the body watchdog can run,
        # so only the pre-response deadline can free the worker.
        session = _HeaderTrickleSession()
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, BASIC_AUTH, mock.MagicMock())
        with mock.patch.object(appdynamics_module, "MAX_DOWNLOAD_SECONDS", 0.2):
            started = time.monotonic()
            with pytest.raises(AppdynamicsError, match="response headers"):
                client.get_json("/controller/rest/applications", {})
            assert time.monotonic() - started < 5


def _run_get_rows(
    responder: Any,
    endpoint: str,
    manager: FakeResumeManager,
    metric_paths: list[str] | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], FakeSession]:
    session = FakeSession(responder=responder)
    with _patch_session(session):
        batches = list(
            get_rows(
                base_url=BASE_URL,
                endpoint=endpoint,
                auth=BASIC_AUTH,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                metric_paths=metric_paths or ["Overall Application Performance|*"],
                **kwargs,
            )
        )
    return batches, session


class TestGetRows:
    def test_applications_yields_rows_without_state(self) -> None:
        manager = FakeResumeManager()
        batches, _ = _run_get_rows(
            lambda path, params: FakeResponse(json_data=[{"id": 1, "name": "app"}]),
            "applications",
            manager,
        )
        assert batches == [[{"id": 1, "name": "app"}]]
        assert manager.saved == []

    def test_too_many_applications_is_rejected(self) -> None:
        many = [{"id": i} for i in range(appdynamics_module.MAX_APPLICATIONS + 1)]
        manager = FakeResumeManager()
        with pytest.raises(AppdynamicsError):
            _run_get_rows(lambda path, params: FakeResponse(json_data=many), "business_transactions", manager)

    def test_metric_data_fan_out_budget_is_enforced(self) -> None:
        # Max applications × max metric paths × the 7-day metric window blows the aggregate
        # budget even though each individual dimension is within its own cap.
        apps = [{"id": i} for i in range(appdynamics_module.MAX_APPLICATIONS)]
        paths = [f"Metric|{i}" for i in range(MAX_METRIC_PATHS)]
        manager = FakeResumeManager()
        with pytest.raises(AppdynamicsError):
            _run_get_rows(lambda path, params: FakeResponse(json_data=apps), "metric_data", manager, metric_paths=paths)

    def test_duplicate_application_ids_are_deduplicated(self) -> None:
        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}, {"id": 1}, {"id": 2}])
            return FakeResponse(json_data=[{"name": "bt"}])

        manager = FakeResumeManager()
        batches, _ = _run_get_rows(responder, "business_transactions", manager)
        assert [row["application_id"] for batch in batches for row in batch] == [1, 2]

    def test_fan_out_injects_application_id_and_bookmarks_next_app(self) -> None:
        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}, {"id": 2}])
            return FakeResponse(json_data=[{"id": 10, "name": f"bt-{path.split('/')[4]}"}])

        manager = FakeResumeManager()
        batches, _ = _run_get_rows(responder, "business_transactions", manager)

        assert [row["application_id"] for batch in batches for row in batch] == [1, 2]
        # bookmark points at the NEXT application, saved once per non-final application
        assert [s.application_id for s in manager.saved] == [2]

    def test_fan_out_resumes_from_bookmarked_application(self) -> None:
        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}, {"id": 2}, {"id": 3}])
            return FakeResponse(json_data=[{"id": 10}])

        manager = FakeResumeManager(initial=AppdynamicsResumeConfig(application_id=2))
        batches, session = _run_get_rows(responder, "tiers", manager)

        fetched_apps = [row["application_id"] for batch in batches for row in batch]
        assert fetched_apps == [2, 3]

    def test_fan_out_deleted_bookmark_application_starts_over(self) -> None:
        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}])
            return FakeResponse(json_data=[{"id": 10}])

        manager = FakeResumeManager(initial=AppdynamicsResumeConfig(application_id=99))
        batches, _ = _run_get_rows(responder, "tiers", manager)
        assert [row["application_id"] for batch in batches for row in batch] == [1]

    @freeze_time("2024-01-31T00:00:00Z")
    def test_windowed_full_refresh_uses_lookback_and_chunks(self) -> None:
        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}])
            return FakeResponse(json_data=[{"id": 5, "startTimeInMillis": params["start-time"]}])

        manager = FakeResumeManager()
        batches, session = _run_get_rows(responder, "health_rule_violations", manager)

        window_calls = [(params["start-time"], params["end-time"]) for path, params, _ in session.get_calls[1:]]
        expected_start = FROZEN_NOW_MS - 30 * MILLIS_PER_DAY
        # 30-day lookback fetched in 7-day chunks: 4 full chunks + a 2-day remainder
        assert len(window_calls) == 5
        assert window_calls[0][0] == expected_start
        assert window_calls[-1][1] == FROZEN_NOW_MS
        for start, end in window_calls:
            assert start < end
        assert all(params["time-range-type"] == "BETWEEN_TIMES" for _, params, _ in session.get_calls[1:])
        # each window's state is saved after its rows are yielded
        assert [s.window_start for s in manager.saved] == [end for _, end in window_calls]

    @freeze_time("2024-01-31T00:00:00Z")
    def test_windowed_incremental_starts_one_ms_after_watermark(self) -> None:
        watermark = FROZEN_NOW_MS - MILLIS_PER_DAY

        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}])
            return FakeResponse(json_data=[])

        manager = FakeResumeManager()
        _, session = _run_get_rows(
            responder,
            "health_rule_violations",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        _, params, _ = session.get_calls[1]
        assert params["start-time"] == watermark + 1
        assert params["end-time"] == FROZEN_NOW_MS
        assert len(session.get_calls) == 2

    @freeze_time("2024-01-31T00:00:00Z")
    def test_windowed_resume_uses_saved_window_for_bookmarked_app_only(self) -> None:
        resume_start = FROZEN_NOW_MS - MILLIS_PER_DAY

        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 1}, {"id": 2}])
            return FakeResponse(json_data=[])

        manager = FakeResumeManager(initial=AppdynamicsResumeConfig(application_id=1, window_start=resume_start))
        _, session = _run_get_rows(
            responder,
            "health_rule_violations",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=FROZEN_NOW_MS - 2 * MILLIS_PER_DAY,
        )

        app_1_call = session.get_calls[1]
        app_2_call = session.get_calls[2]
        assert "/applications/1/" in app_1_call[0]
        assert app_1_call[1]["start-time"] == resume_start
        # the app after the bookmark starts from the regular watermark-derived window
        assert "/applications/2/" in app_2_call[0]
        assert app_2_call[1]["start-time"] == FROZEN_NOW_MS - 2 * MILLIS_PER_DAY + 1

    @freeze_time("2024-01-31T00:00:00Z")
    def test_metric_data_flattens_metric_values_per_path(self) -> None:
        metric = {
            "metricId": 42,
            "metricName": "BTM|Application Summary|Average Response Time (ms)",
            "metricPath": "Overall Application Performance|Average Response Time (ms)",
            "frequency": "ONE_MIN",
            "metricValues": [
                {"startTimeInMillis": 1706572800000, "value": 12, "min": 1, "max": 20},
                {"startTimeInMillis": 1706572860000, "value": 15, "min": 2, "max": 30},
            ],
        }

        def responder(path: str, params: dict[str, Any]) -> FakeResponse:
            if path == "/controller/rest/applications":
                return FakeResponse(json_data=[{"id": 7}])
            return FakeResponse(json_data=[metric])

        manager = FakeResumeManager()
        batches, session = _run_get_rows(
            responder,
            "metric_data",
            manager,
            metric_paths=["Overall Application Performance|*", "Business Transaction Performance|*"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
        )

        # one window (1 day, 1-day chunks) x two metric paths
        metric_calls = session.get_calls[1:]
        assert [params["metric-path"] for _, params, _ in metric_calls] == [
            "Overall Application Performance|*",
            "Business Transaction Performance|*",
        ]
        assert all(params["rollup"] == "false" for _, params, _ in metric_calls)

        rows = [row for batch in batches for row in batch]
        assert len(rows) == 4
        # every primary key column is present on every row
        assert all({"application_id", "metricId", "startTimeInMillis"} <= set(row) for row in rows)
        assert rows[0]["application_id"] == 7
        assert rows[0]["metricId"] == 42
        assert rows[0]["value"] == 12


class TestAppdynamicsSourceResponse:
    @parameterized.expand(list(APPDYNAMICS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = appdynamics_source(
            host=BASE_URL,
            auth=BASIC_AUTH,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),  # type: ignore[arg-type]
            team_id=1,
            metric_paths=["Overall Application Performance|*"],
        )
        config = APPDYNAMICS_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == ("desc" if config.time_windowed else "asc")
