import ipaddress
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import RecordedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pganalyze import (
    PgAnalyzeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze import (
    PgAnalyzeRetryableError,
    QueryStatsWindow,
    _post_graphql,
    _query_stats_windows,
    _resolve_api_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.settings import PGANALYZE_API_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.source import PgAnalyzeSource

_PUBLIC_IP = {ipaddress.ip_address("93.184.216.34")}


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.reason = "OK" if response.ok else "Error"
    response.text = text
    if json_data is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_data
    return response


class TestPostGraphql:
    def test_returns_data_on_success(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"data": {"getServers": []}})

        result = _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

        assert result == {"getServers": []}

    def test_raises_retryable_on_5xx(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=502, text="bad gateway")

        with pytest.raises(PgAnalyzeRetryableError, match="server error 502"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_retryable_on_429(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(status_code=429, text="too many")

        with pytest.raises(PgAnalyzeRetryableError, match="rate limited"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_graphql_errors_field(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"errors": [{"message": "field x not found"}]})

        with pytest.raises(Exception, match="GraphQL error"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_raises_on_missing_data_key(self):
        session = mock.MagicMock()
        session.post.return_value = _mock_response(json_data={"unexpected": "shape"})

        with pytest.raises(Exception, match="Unexpected pganalyze response format"):
            _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

    def test_retries_on_read_timeout(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            requests.ReadTimeout("Read timed out. (read timeout=60)"),
            _mock_response(json_data={"data": {"getServers": []}}),
        ]

        result = _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

        assert result == {"getServers": []}
        assert session.post.call_count == 2

    def test_retries_on_connection_error(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            requests.ConnectionError("Connection aborted"),
            _mock_response(json_data={"data": {"getServers": []}}),
        ]

        result = _post_graphql(session, "https://app.pganalyze.com/graphql", "query {}", {})

        assert result == {"getServers": []}
        assert session.post.call_count == 2


class TestValidateCredentials:
    def test_returns_true_on_valid_credentials(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze.make_tracked_session"
        ) as mock_sess:
            sess = mock.MagicMock()
            sess.post.return_value = _mock_response(json_data={"data": {"getServers": []}})
            mock_sess.return_value = sess

            ok, err = validate_credentials("token", "acme", None)

            assert ok is True
            assert err is None
            sess.post.assert_called_once()
            sess.close.assert_called_once()

    @pytest.mark.parametrize("status_code", [401])
    def test_returns_false_on_auth_error(self, status_code):
        with scripted_network([ScriptedResponse(status=status_code, body=b"forbidden")]) as network:
            ok, err = validate_credentials("bad", "acme", None)

        assert ok is False
        assert err is not None
        assert "Invalid" in err
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/graphql"
        assert network.requests_log[0].headers["authorization"] == "Token bad"

    def test_returns_false_on_graphql_error(self):
        with scripted_network([ScriptedResponse(json={"errors": [{"message": "Organization not found"}]})]) as network:
            ok, err = validate_credentials("token", "wrong-slug", None)

        assert ok is False
        assert err is not None
        assert "Organization not found" in err
        assert len(network.requests_log) == 1
        assert network.requests_log[0].json()["variables"] == {"organizationSlug": "wrong-slug"}

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/",
            "http://127.0.0.1/graphql",
            "http://localhost/graphql",
            "http://10.0.0.1/graphql",
            "file:///etc/passwd",
        ],
    )
    def test_returns_false_for_ssrf_targets(self, blocked_url):
        # is_url_allowed short-circuits in dev mode (DEBUG=True), so force it off
        with mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            ok, err = validate_credentials("token", "acme", blocked_url)

        assert ok is False
        assert err is not None
        assert "not allowed" in err


class TestResolveApiUrl:
    def test_defaults_to_public_api_when_none(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            assert _resolve_api_url(None) == PGANALYZE_API_URL

    def test_defaults_to_public_api_when_empty_string(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            assert _resolve_api_url("") == PGANALYZE_API_URL
            assert _resolve_api_url("   ") == PGANALYZE_API_URL

    def test_accepts_well_formed_public_url(self):
        with (
            mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            mock.patch("posthog.security.url_validation.resolve_host_ips", return_value=_PUBLIC_IP),
        ):
            url = "https://app.pganalyze.com/graphql"
            assert _resolve_api_url(url) == url

    @pytest.mark.parametrize(
        "blocked_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/graphql",
            "http://localhost/graphql",
        ],
    )
    def test_rejects_ssrf_targets(self, blocked_url):
        with mock.patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            with pytest.raises(ValueError, match="not allowed"):
                _resolve_api_url(blocked_url)


_NOW = datetime(2026, 3, 4, 15, 30, tzinfo=UTC)


def _day(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=UTC)


class TestQueryStatsWindows:
    @parameterized.expand(
        [
            ("no_watermark_syncs_the_last_finished_day", None, _NOW, [(3, 4)]),
            ("string_watermark_resumes_after_its_day", "2026-03-01T00:00:00+00:00", _NOW, [(2, 3), (3, 4)]),
            ("watermark_on_last_finished_day_syncs_nothing", _day(3), _NOW, []),
            ("day_inside_settle_delay_is_not_finished", None, _day(4).replace(minute=30), [(2, 3)]),
            (
                "old_watermark_is_capped_at_the_catchup_limit",
                datetime(2025, 1, 1, tzinfo=UTC),
                _NOW,
                [(1, 2), (2, 3), (3, 4)],
            ),
        ]
    )
    def test_windows(self, _label: str, watermark: Any, now: datetime, expected_days: list[tuple[int, int]]) -> None:
        assert _query_stats_windows(watermark, now) == [
            QueryStatsWindow(start=_day(start), end=_day(end)) for start, end in expected_days
        ]


def _query_stats_script(request: RecordedRequest) -> ScriptedResponse:
    body = request.json()
    query = body["query"]
    if "getServers" in query:
        return ScriptedResponse(
            json={
                "data": {
                    "getServers": [
                        {"humanId": "srv-a", "name": "primary"},
                        {"humanId": None, "name": "unregistered"},
                        {"humanId": "srv-b", "name": "replica"},
                    ]
                }
            }
        )
    if "getIssues" in query:
        issues = {
            "srv-a": [{"databaseId": 11}, {"databaseId": 11}, {"databaseId": None}],
            "srv-b": [{"databaseId": 22}],
        }[body["variables"]["serverId"]]
        return ScriptedResponse(json={"data": {"getIssues": issues}})
    database_id = body["variables"]["databaseId"]
    return ScriptedResponse(
        json={"data": {"getQueryStats": [{"id": int(database_id) * 100, "totalCalls": 5, "avgTime": 1.5}]}}
    )


class TestQueryStatsExtraction:
    @parameterized.expand(
        [
            ("full_refresh", False, None, 1),
            ("incremental_from_watermark", True, "2026-03-01T00:00:00+00:00", 2),
        ]
    )
    def test_fetches_each_discovered_database_per_window(
        self, _label: str, incremental: bool, watermark: str | None, window_count: int
    ) -> None:
        config = PgAnalyzeSourceConfig(api_key="token", organization_slug="acme", api_url=None)
        with time_machine.travel(_NOW, tick=False):
            result = SourceDriver(PgAnalyzeSource(), config).run(
                "query_stats",
                _query_stats_script,
                should_use_incremental_field=incremental,
                incremental_field="window_start" if incremental else None,
                db_incremental_field_last_value=watermark,
            )

        assert result.raised is None
        stats_variables = [r.json()["variables"] for r in result.requests if "getQueryStats" in r.json()["query"]]
        assert [v["databaseId"] for v in stats_variables] == ["11", "22"] * window_count
        assert stats_variables[-1] == {
            "databaseId": "22",
            "startTs": int(_day(3).timestamp()),
            "endTs": int(_day(4).timestamp()),
        }
        assert len(result.rows) == 2 * window_count
        assert result.rows[-1] == {
            "id": 2200,
            "totalCalls": 5,
            "avgTime": 1.5,
            "databaseId": 22,
            "serverHumanId": "srv-b",
            "serverName": "replica",
            "window_start": "2026-03-03T00:00:00+00:00",
            "window_end": "2026-03-04T00:00:00+00:00",
        }
