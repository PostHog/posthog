import json
import time
import socket
import threading
from typing import Any
from urllib.parse import urlparse

import pytest
import time_machine
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
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    ANOMALIES_PAGE_SIZE,
    APPDYNAMICS_ENDPOINTS,
    MAX_METRIC_PATHS,
    MAX_ROWS_PER_TIME_WINDOW,
    METRIC_TREE_MAX_REQUESTS_PER_APPLICATION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.source import AppdynamicsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appdynamics import (
    AppdynamicsAuthMethodConfig,
    AppdynamicsSourceConfig,
)

BASE_URL = "https://acme.saas.appdynamics.com"
MILLIS_PER_DAY = 24 * 60 * 60 * 1000
# 2024-01-31T00:00:00Z, used as the frozen "now" for window tests
FROZEN_NOW_MS = 1706659200000

BASIC_AUTH = AppdynamicsAuth(account_name="acme", username="user", password="pass")
OAUTH_AUTH = AppdynamicsAuth(account_name="acme", api_client_name="client", api_client_secret="secret")


def _driver(metric_paths: str | None = None, event_types: str | None = None) -> SourceDriver:
    return SourceDriver(
        AppdynamicsSource(),
        AppdynamicsSourceConfig(
            host=BASE_URL,
            account_name="acme",
            auth_method=AppdynamicsAuthMethodConfig(selection="basic", username="user", password="pass"),
            metric_paths=metric_paths,
            event_types=event_types,
        ),
    )


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


class _PartialHeaderServer:
    """A local HTTP server that sends a status line then trickles headers forever without ever
    terminating them, holding the connection open — reproducing a controller that stalls in the
    response-header phase faster than any read-idle timeout. Records when the client closes the
    socket so a test can prove the in-flight connection was actually torn down (not leaked).
    """

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self.client_closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        try:
            conn.recv(4096)  # consume the request line/headers
            conn.sendall(b"HTTP/1.1 200 OK\r\n")  # status line only — headers never terminated
            while True:
                conn.sendall(b"X-Trickle: 1\r\n")  # keep dribbling headers, never the blank line
                time.sleep(0.02)
        except OSError:
            # sendall raises once the client force-closes its socket at the deadline.
            self.client_closed.set()
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def __enter__(self) -> "_PartialHeaderServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self._listener.close()
        except OSError:
            pass


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
    return mock.patch.object(appdynamics_module, "_make_abortable_session", return_value=session)


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
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            valid, error = validate_credentials(BASE_URL, BASIC_AUTH, team_id=1)
        assert valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/controller/rest/applications"}

    def test_redirects_are_never_followed(self) -> None:
        session = FakeSession(responder=lambda path, params: FakeResponse(status_code=200))
        with _patch_session(session):
            validate_credentials(BASE_URL, BASIC_AUTH, team_id=1)
        _, _, kwargs = session.get_calls[0]
        assert kwargs["allow_redirects"] is False
        # The probe only needs the status code, so it must stream rather than buffer a body.
        assert kwargs["stream"] is True


class TestAppdynamicsClient:
    def test_oauth_token_cached_until_expiry(self) -> None:
        session = FakeSession()
        with _patch_session(session):
            client = AppdynamicsClient(BASE_URL, OAUTH_AUTH, mock.MagicMock())

        with time_machine.travel("2024-01-31T00:00:00Z", tick=False) as frozen:
            client.get_json("/controller/rest/applications", {})
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 1

            frozen.move_to("2024-01-31T00:10:00Z")  # past the 5 min TTL
            client.get_json("/controller/rest/applications", {})
            assert len(session.post_calls) == 2

        for _, _, kwargs in session.get_calls:
            assert kwargs["headers"]["Authorization"] == "Bearer tok"
            assert kwargs["auth"] is None

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

    def test_header_deadline_closes_connection_stuck_parsing_headers(self) -> None:
        # A real server that stalls mid-header keeps `requests` blocked before the body watchdog
        # can run. The deadline must force-close the in-flight socket so the request unwinds and
        # the connection is reclaimed — Session.close() alone can't reach an in-use connection.
        with _PartialHeaderServer() as server:
            client = AppdynamicsClient(f"http://127.0.0.1:{server.port}", BASIC_AUTH, mock.MagicMock())
            with mock.patch.object(appdynamics_module, "MAX_DOWNLOAD_SECONDS", 0.3):
                started = time.monotonic()
                with pytest.raises(AppdynamicsError, match="response headers"):
                    client.get_json("/controller/rest/applications", {})
                assert time.monotonic() - started < 5
            # The client must have actually torn down the connection, not merely abandoned it.
            assert server.client_closed.wait(timeout=5)


class TestGetRows:
    @parameterized.expand(
        [
            ("applications", "/controller/rest/applications"),
            ("database_servers", "/controller/rest/databases/servers"),
        ]
    )
    def test_account_level_endpoint_is_read_without_fanning_out(self, endpoint: str, expected_path: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[{"id": 1, "name": "thing"}])])
        assert result.raised is None
        assert result.items == [[{"id": 1, "name": "thing"}]]
        assert result.paths == [expected_path]
        assert result.saved_states == []

    def test_too_many_applications_is_rejected(self) -> None:
        many = [{"id": i} for i in range(appdynamics_module.MAX_APPLICATIONS + 1)]
        result = _driver().run("business_transactions", [ScriptedResponse(json=many)])
        assert isinstance(result.raised, AppdynamicsError)
        assert result.paths == ["/controller/rest/applications"]

    def test_metric_data_fan_out_budget_is_enforced(self) -> None:
        # Max applications × max metric paths × the 7-day metric window blows the aggregate
        # budget even though each individual dimension is within its own cap.
        apps = [{"id": i} for i in range(appdynamics_module.MAX_APPLICATIONS)]
        paths = [f"Metric|{i}" for i in range(MAX_METRIC_PATHS)]
        result = _driver(metric_paths="\n".join(paths)).run("metric_data", [ScriptedResponse(json=apps)])
        assert isinstance(result.raised, AppdynamicsError)
        assert result.paths == ["/controller/rest/applications"]

    def test_metric_tree_fan_out_budget_counts_the_per_application_request_cap(self) -> None:
        # Browsing the hierarchy costs many requests per application, so the budget check has
        # to multiply by that cap rather than assume one request per application.
        applications = 10
        apps = [{"id": i} for i in range(applications)]
        budget = applications * METRIC_TREE_MAX_REQUESTS_PER_APPLICATION - 1
        with mock.patch.object(appdynamics_module, "MAX_FANOUT_REQUESTS", budget):
            result = _driver().run("metrics", [ScriptedResponse(json=apps)])
        assert isinstance(result.raised, AppdynamicsError)
        assert result.paths == ["/controller/rest/applications"]

    def test_fan_out_injects_application_id_and_bookmarks_next_app(self) -> None:
        result = _driver().run(
            "business_transactions",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}]),
                ScriptedResponse(json=[{"id": 10, "name": "bt-1"}]),
                ScriptedResponse(json=[{"id": 10, "name": "bt-2"}]),
            ],
        )

        assert result.raised is None
        assert [row["application_id"] for row in result.rows] == [1, 2]
        # bookmark points at the NEXT application, saved once per non-final application
        assert [state.application_id for state in result.saved_states] == [2]
        assert result.paths == [
            "/controller/rest/applications",
            "/controller/rest/applications/1/business-transactions",
            "/controller/rest/applications/2/business-transactions",
        ]

    def test_fan_out_resumes_from_bookmarked_application(self) -> None:
        result = _driver().run(
            "tiers",
            [
                ScriptedResponse(json=[{"id": 1}, {"id": 2}, {"id": 3}]),
                ScriptedResponse(json=[{"id": 10}]),
                ScriptedResponse(json=[{"id": 10}]),
            ],
            resume_state=AppdynamicsResumeConfig(application_id=2),
        )

        assert result.raised is None
        assert [row["application_id"] for row in result.rows] == [2, 3]
        assert result.paths == [
            "/controller/rest/applications",
            "/controller/rest/applications/2/tiers",
            "/controller/rest/applications/3/tiers",
        ]

    @time_machine.travel("2024-01-31T00:00:00Z", tick=False)
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

        driver = _driver(metric_paths="Overall Application Performance|*\nBusiness Transaction Performance|*")
        result = driver.run(
            "metric_data",
            [ScriptedResponse(json=[{"id": 7}]), ScriptedResponse(json=[metric]), ScriptedResponse(json=[metric])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
        )

        # one window (1 day, 1-day chunks) x two metric paths
        assert result.raised is None
        assert result.params("metric-path")[1:] == [
            "Overall Application Performance|*",
            "Business Transaction Performance|*",
        ]
        assert result.params("rollup")[1:] == ["false", "false"]

        rows = result.rows
        assert len(rows) == 4
        # every primary key column is present on every row
        assert all({"application_id", "metricId", "startTimeInMillis"} <= set(row) for row in rows)
        assert rows[0]["application_id"] == 7
        assert rows[0]["metricId"] == 42
        assert rows[0]["value"] == 12

    @time_machine.travel("2024-01-31T00:00:00Z", tick=False)
    def test_window_that_cannot_be_split_further_warns_and_keeps_its_rows(self) -> None:
        logger = mock.MagicMock()
        with mock.patch.object(appdynamics_module, "MAX_WINDOW_SPLITS", 0):
            result = _driver().run(
                "events",
                [
                    ScriptedResponse(json=[{"id": 1}]),
                    ScriptedResponse(json=[{"id": i} for i in range(MAX_ROWS_PER_TIME_WINDOW)]),
                ],
                logger=logger,
                should_use_incremental_field=True,
                db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
            )

        assert result.raised is None
        assert len(result.requests) == 2  # the application list, then one un-split window
        assert len(result.items[0]) == MAX_ROWS_PER_TIME_WINDOW
        assert logger.warning.call_count == 1

    @time_machine.travel("2024-01-31T00:00:00Z", tick=False)
    def test_splitting_draws_from_the_sync_wide_request_allowance(self) -> None:
        # Splitting is per window but the fan-out limit is per sync, so a controller that
        # returns a full response every time must not multiply an accepted sync by the
        # per-window split cap.
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/controller/rest/applications":
                return ScriptedResponse(json=[{"id": 1}])
            return ScriptedResponse(json=[{"id": i} for i in range(MAX_ROWS_PER_TIME_WINDOW)])

        logger = mock.MagicMock()
        # One window is estimated, so an allowance of one leaves room for a single split.
        with mock.patch.object(appdynamics_module, "MAX_FANOUT_REQUESTS", 2):
            result = _driver().run(
                "events",
                responder,
                logger=logger,
                should_use_incremental_field=True,
                db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
            )

        # The whole window, then its two halves; neither half may split again.
        assert result.raised is None
        assert len(result.requests) == 1 + 3
        assert logger.warning.call_count == 2

    @parameterized.expand(
        [
            ("events", {"event-types": "APPLICATION_DEPLOYMENT,APP_SERVER_RESTART", "severities": "INFO,WARN,ERROR"}),
            ("request_snapshots", {"maximum-results": MAX_ROWS_PER_TIME_WINDOW}),
            ("anomalies", {"fetchSuspectedCause": "false"}),
        ]
    )
    @time_machine.travel("2024-01-31T00:00:00Z", tick=False)
    def test_windowed_endpoint_sends_its_required_params(self, endpoint: str, expected: dict[str, Any]) -> None:
        # The Controller rejects an events request with no `event-types`/`severities`, and caps
        # snapshots at its own default unless `maximum-results` is asked for.
        result = _driver(event_types="APPLICATION_DEPLOYMENT\nAPP_SERVER_RESTART").run(
            endpoint,
            [ScriptedResponse(json=[{"id": 1}]), ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
        )

        assert result.raised is None
        assert all(result.requests[1].param(key) == str(value) for key, value in expected.items())

    @time_machine.travel("2024-01-31T00:00:00Z", tick=False)
    def test_anomalies_paging_draws_from_the_sync_wide_request_allowance(self) -> None:
        # Paging is per window but the fan-out limit is per sync, so a controller that returns
        # a full page every time can't multiply an accepted sync by the per-window page cap.
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/controller/rest/applications":
                return ScriptedResponse(json=[{"id": 1}])
            return ScriptedResponse(json={"violationListItem": [{"id": n} for n in range(ANOMALIES_PAGE_SIZE)]})

        logger = mock.MagicMock()
        # One window is estimated, so an allowance of one leaves room for a single extra page.
        with mock.patch.object(appdynamics_module, "MAX_FANOUT_REQUESTS", 2):
            result = _driver().run(
                "anomalies",
                responder,
                logger=logger,
                should_use_incremental_field=True,
                db_incremental_field_last_value=FROZEN_NOW_MS - MILLIS_PER_DAY,
            )

        assert result.raised is None
        assert result.params("pageNumber")[1:] == ["0", "1"]
        assert logger.warning.call_count == 1

    def test_metric_tree_walk_stops_at_the_request_budget(self) -> None:
        tree = {"": [{"name": "f1", "type": "folder"}, {"name": "f2", "type": "folder"}]}
        tree["f1"] = [{"name": "leaf", "type": "leaf"}]
        tree["f2"] = [{"name": "leaf", "type": "leaf"}]

        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/controller/rest/applications":
                return ScriptedResponse(json=[{"id": 1}])
            return ScriptedResponse(json=tree.get(request.param("metric-path") or "", []))

        logger = mock.MagicMock()
        with mock.patch.object(appdynamics_module, "METRIC_TREE_MAX_REQUESTS_PER_APPLICATION", 2):
            result = _driver().run("metrics", responder, logger=logger)

        assert result.raised is None
        assert len(result.requests) == 1 + 2
        assert logger.warning.call_count == 1


class TestAppdynamicsSourceResponse:
    @parameterized.expand(list(APPDYNAMICS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        response = result.response
        assert response is not None
        config = APPDYNAMICS_ENDPOINTS[endpoint]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == ("desc" if config.time_windowed else "asc")
