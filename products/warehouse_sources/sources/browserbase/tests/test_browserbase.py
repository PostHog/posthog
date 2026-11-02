import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase import (
    BROWSERBASE_BASE_URL,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.source import BrowserbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.browserbase import (
    BrowserbaseSourceConfig,
)


def _driver(api_key: str = "bb_key") -> SourceDriver:
    return SourceDriver(BrowserbaseSource(), BrowserbaseSourceConfig(api_key=api_key))


class TestGetRows:
    @parameterized.expand(
        [
            ("bare_list_endpoint", "sessions", "Required a list response body"),
            ("enveloped_endpoint", "agents", "matched nothing in the response"),
        ]
    )
    def test_unexpected_response_shape_raises(self, _name: str, endpoint: str, message: str) -> None:
        # Browserbase answers either with a bare array or with rows under `data`; neither shape is
        # present here. Raise so the sync fails loudly instead of finishing "successfully" with
        # zero rows.
        result = _driver().run(endpoint, [ScriptedResponse(json={"statusCode": 500})])

        assert isinstance(result.raised, ValueError)
        assert message in str(result.raised)

    def test_api_key_sent_via_header_auth(self) -> None:
        result = _driver("bb_test_key").run("sessions", [ScriptedResponse(json=[{"id": "sess_1"}])])

        assert result.raised is None
        assert result.requests[0].headers["x-bb-api-key"] == "bb_test_key"
        assert result.requests[0].headers["accept"] == "application/json"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_after_retries(self, _name: str, status_code: int) -> None:
        result = _driver().run("sessions", always(ScriptedResponse(status=status_code, json={"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 5 attempts before giving up.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_immediately(self, _name: str, status_code: int) -> None:
        result = _driver().run("sessions", [ScriptedResponse(status=status_code, json={"error": "nope"})])

        assert isinstance(result.raised, requests.HTTPError)
        # Client errors are not retried - they can never succeed on retry.
        assert len(result.requests) == 1


class TestKeyRedaction:
    def test_source_session_redacts_key(self) -> None:
        # The API key must be masked in tracked HTTP logs/samples, not left recoverable from a bucket.
        result = _driver("bb_secret").run("sessions", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("bb_secret",)
        # Response bodies carry arbitrary customer userMetadata the scrubbers can't recognise.
        assert result.session_options[0]["capture"] is False

    def test_validate_credentials_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("bb_secret") is True

        assert network.session_options[0]["redact_values"] == ("bb_secret",)
        assert network.session_options[0]["capture"] is False


class TestValidateCredentials:
    def test_probes_projects_with_key_header(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            assert validate_credentials("bb_key") is True

        assert network.requests_log[0].url == f"{BROWSERBASE_BASE_URL}/projects"
        assert network.requests_log[0].headers["x-bb-api-key"] == "bb_key"


class TestCursorPagination:
    def test_follows_next_cursor_until_it_is_null(self) -> None:
        # Without the cursor wired to `nextCursor`/`cursor` a sync silently stops after one page.
        result = _driver().run(
            "agent_runs",
            [
                ScriptedResponse(json={"data": [{"runId": "run_1"}], "limit": 1000, "nextCursor": "cur_2"}),
                ScriptedResponse(json={"data": [{"runId": "run_2"}], "limit": 1000, "nextCursor": None}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"runId": "run_1"}, {"runId": "run_2"}]
        assert len(result.requests) == 2
        assert result.params("cursor") == [None, "cur_2"]
        # Ask for the largest page the endpoint allows, so a sync makes as few round trips as it can.
        assert result.params("limit") == ["1000", "1000"]


class TestFanout:
    def test_project_usage_yields_one_row_per_project_keyed_by_project(self) -> None:
        # The usage body is a bare object with no id of its own, so without the parent id copied
        # down the table has no key and no way to tell whose usage a row is.
        result = _driver().run(
            "project_usage",
            [
                ScriptedResponse(json=[{"id": "proj_1"}, {"id": "proj_2"}]),
                ScriptedResponse(json={"browserMinutes": 12, "proxyBytes": 345}),
                ScriptedResponse(json={"browserMinutes": 67, "proxyBytes": 890}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"browserMinutes": 12, "proxyBytes": 345, "projectId": "proj_1"},
            {"browserMinutes": 67, "proxyBytes": 890, "projectId": "proj_2"},
        ]
        assert result.urls[1:] == [
            f"{BROWSERBASE_BASE_URL}/projects/proj_1/usage",
            f"{BROWSERBASE_BASE_URL}/projects/proj_2/usage",
        ]

    def test_session_logs_fan_out_binds_the_session_id(self) -> None:
        result = _driver().run(
            "session_logs",
            [
                ScriptedResponse(json=[{"id": "sess_1"}]),
                ScriptedResponse(json=[{"sessionId": "sess_1", "pageId": 1, "method": "Page.navigate"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"sessionId": "sess_1", "pageId": 1, "method": "Page.navigate"}]
        assert result.urls[1] == f"{BROWSERBASE_BASE_URL}/sessions/sess_1/logs"


class TestBrowserbaseSource:
    @parameterized.expand(
        [
            ("sessions", ["id"], "createdAt"),
            ("projects", ["id"], "createdAt"),
            ("agents", ["agentId"], "createdAt"),
            ("agent_runs", ["runId"], "createdAt"),
            # Fan-out children carry no id of their own, so the parent id is part of the key.
            ("project_usage", ["projectId"], None),
            ("session_logs", ["sessionId", "pageId", "method", "timestamp"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        body = {"data": [], "nextCursor": None} if endpoint in {"agents", "agent_runs"} else []
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        # Partition on the stable creation timestamp, never updatedAt.
        assert result.response.partition_keys == ([partition_key] if partition_key else None)
        assert result.response.partition_mode == ("datetime" if partition_key else None)
