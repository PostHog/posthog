from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.healthchecks import (
    HealthchecksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.healthchecks import (
    DEFAULT_BASE_URL,
    HealthchecksResumeConfig,
    HealthchecksRetryableError,
    _to_unix_seconds,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.source import HealthchecksSource


def _driver() -> SourceDriver:
    return SourceDriver(HealthchecksSource(), HealthchecksSourceConfig(api_key="key", base_url=None))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, DEFAULT_BASE_URL),
            ("", DEFAULT_BASE_URL),
            ("   ", DEFAULT_BASE_URL),
            ("https://healthchecks.io", "https://healthchecks.io"),
            ("healthchecks.example.com", "https://healthchecks.example.com"),
            ("https://hc.example.com/", "https://hc.example.com"),
            ("http://hc.internal:8000", "http://hc.internal:8000"),
        ],
    )
    def test_valid(self, value, expected):
        assert normalize_base_url(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "ftp://example.com",
            "https://",
            # SSRF host-confusion tricks: the parsed hostname (validated by the SSRF allowlist)
            # must not diverge from the host the HTTP client dials. Reject backslashes (raw and
            # encoded), userinfo, and query/fragment so the allowlist can't be bypassed.
            "http://169.254.169.254\\@example.com/",
            "http://169.254.169.254%5c@example.com/",
            "http://user@169.254.169.254",
            "http://example.com@169.254.169.254",
            "https://example.com?@169.254.169.254",
            "https://example.com#@169.254.169.254",
        ],
    )
    def test_invalid_raises(self, value):
        with pytest.raises(ValueError):
            normalize_base_url(value)


class TestToUnixSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.5, 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            # Naive datetimes are treated as UTC.
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            ("not-a-date", None),
        ],
    )
    def test_conversion(self, value, expected):
        assert _to_unix_seconds(value) == expected

    def test_date_conversion(self):
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestFetch:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise(self, status_code: int) -> None:
        result = _driver().run("checks", always(ScriptedResponse(status=status_code, json={})))

        assert isinstance(result.raised, HealthchecksRetryableError)
        # The source makes 5 attempts. The shared HTTP stack retries each one 3 times.
        assert result.paths == ["/api/v3/checks/"] * 20

    def test_client_error_raises_for_status(self) -> None:
        result = _driver().run(
            "checks",
            [ScriptedResponse(status=401, json={"error": "missing api key"})],
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/api/v3/checks/"]


class TestValidateCredentials:
    def test_invalid_key(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={"error": "wrong api key"})]) as network:
            ok, err = validate_credentials(None, "bad")

        assert ok is False
        assert err == "Invalid Healthchecks API key"
        assert network.requests_log[0].path == "/api/v3/checks/"
        assert network.requests_log[0].headers["x-api-key"] == "bad"

    def test_network_error(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            ok, err = validate_credentials(None, "key")

        assert ok is False
        assert "boom" in (err or "")
        assert {request.path for request in network.requests_log} == {"/api/v3/checks/"}

    def test_disables_sample_capture(self) -> None:
        # The checks response carries uuid/ping_url (ping credentials); the session must keep it
        # out of the HTTP sample store.
        with scripted_network([ScriptedResponse(json={"checks": []})]) as network:
            validate_credentials(None, "key")

        assert network.session_options[0]["capture"] is False


class TestGetRowsTopLevel:
    def test_checks_normalizes_id_from_unique_key(self) -> None:
        # Read-only keys omit uuid and expose unique_key; id must still be populated.
        result = _driver().run(
            "checks",
            [ScriptedResponse(json={"checks": [{"unique_key": "k-1", "name": "job"}]})],
        )

        assert result.raised is None
        assert result.rows[0]["id"] == "k-1"


class TestGetRowsFanOut:
    def test_flips_injects_check_id_and_bare_array(self) -> None:
        result = _driver().run(
            "flips",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}]}),
                ScriptedResponse(json=[{"timestamp": "2023-11-14T22:13:20+00:00", "up": 1}]),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"check_id": "u-1", "timestamp": "2023-11-14T22:13:20+00:00", "up": 1}]]
        assert result.paths == ["/api/v3/checks/", "/api/v3/checks/u-1/flips/"]

    def test_flips_incremental_passes_start_param(self) -> None:
        result = _driver().run(
            "flips",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}]}),
                ScriptedResponse(json=[]),
            ],
            incremental_field="timestamp",
            db_incremental_field_last_value=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("start") == "1700000000"

    def test_pings_404_is_skipped(self) -> None:
        # A read-only key can't address the pings sub-endpoint (needs the full uuid) -> 404 skip.
        result = _driver().run(
            "pings",
            [
                ScriptedResponse(json={"checks": [{"unique_key": "k-1"}]}),
                ScriptedResponse(status=404, json={}),
            ],
        )

        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/api/v3/checks/", "/api/v3/checks/k-1/pings/"]

    def test_pings_injects_check_id(self) -> None:
        result = _driver().run(
            "pings",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}]}),
                ScriptedResponse(json={"pings": [{"n": 5, "type": "success"}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"check_id": "u-1", "n": 5, "type": "success"}]]

    def test_fan_out_redacts_check_keys_and_disables_capture(self) -> None:
        # Each fan-out URL puts a check key in its path, and a check key doubles as a ping
        # credential, so the fan-out session must redact the keys from request telemetry (and
        # keep response bodies out of the sample store).
        result = _driver().run(
            "flips",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                ScriptedResponse(json=[]),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert all(options["capture"] is False for options in result.session_options)
        # The fan-out session is built last, once the per-check keys are known.
        assert set(result.session_options[-1]["redact_values"]) == {"key", "u-1", "u-2"}

    def test_fan_out_resumes_from_bookmark(self) -> None:
        # Two checks; resume bookmarked at the second, so only it is fetched.
        result = _driver().run(
            "flips",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                ScriptedResponse(json=[{"timestamp": "2023-01-01T00:00:00+00:00", "up": 0}]),
            ],
            resume_state=HealthchecksResumeConfig(check_key="u-2"),
        )

        assert result.raised is None
        assert result.items == [[{"check_id": "u-2", "timestamp": "2023-01-01T00:00:00+00:00", "up": 0}]]
        assert result.paths == ["/api/v3/checks/", "/api/v3/checks/u-2/flips/"]

    def test_fan_out_bookmarks_next_check_after_completing_current(self) -> None:
        # After finishing u-1 the bookmark advances to u-2, so a resume skips the already-yielded
        # u-1 rather than re-emitting them. The final check saves nothing (nothing left to resume).
        result = _driver().run(
            "flips",
            [
                ScriptedResponse(json={"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                ScriptedResponse(json=[{"timestamp": "2023-01-01T00:00:00+00:00", "up": 1}]),
                ScriptedResponse(json=[{"timestamp": "2023-01-02T00:00:00+00:00", "up": 0}]),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [HealthchecksResumeConfig(check_key="u-2")]


class TestHealthchecksSource:
    @pytest.mark.parametrize(
        "endpoint, expected_keys, expected_sort, has_partition",
        [
            ("checks", ["id"], "asc", False),
            ("channels", ["id"], "asc", False),
            ("flips", ["check_id", "timestamp"], "desc", True),
            ("pings", ["check_id", "n"], "asc", True),
        ],
    )
    def test_source_response_shape(
        self, endpoint: str, expected_keys: list[str], expected_sort: str, has_partition: bool
    ) -> None:
        body: dict[str, Any] = {"checks": []} if endpoint in ("checks", "flips", "pings") else {"channels": []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys
        assert result.response.sort_mode == expected_sort
        if has_partition:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys is not None
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
