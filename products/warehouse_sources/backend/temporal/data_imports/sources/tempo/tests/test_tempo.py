from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tempo import TempoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import ENDPOINTS, TEMPO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.source import TempoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.tempo import (
    PAGE_SIZE,
    TEMPO_BASE_URL,
    TempoResumeConfig,
    _build_initial_params,
    _format_updated_from,
    check_access,
    validate_credentials,
)


def _response(results: list[dict[str, Any]], next_url: str | None) -> ScriptedResponse:
    metadata: dict[str, Any] = {"count": len(results)}
    if next_url is not None:
        metadata["next"] = next_url
    return ScriptedResponse(json={"results": results, "metadata": metadata})


def _run(
    script: Any, endpoint: str = "accounts", resume_state: TempoResumeConfig | None = None, **inputs: Any
) -> DriveResult:
    driver = SourceDriver(TempoSource(), TempoSourceConfig(api_token="tempo-token"))
    return driver.run(endpoint, script, resume_state=resume_state, **inputs)


class TestBuildInitialParams:
    def test_worklogs_incremental_with_watermark(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED", "updatedFrom": "2026-03-01T12:30:45Z"}

    @parameterized.expand(
        [("wrong_field", "worklogs", "createdAt"), ("no_incremental_support", "accounts", "updatedAt")]
    )
    def test_rejects_unsupported_incremental_field(self, _name: str, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="does not support incremental field"):
            _build_initial_params(
                TEMPO_ENDPOINTS[endpoint],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
                incremental_field=field,
            )


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            (
                "non_utc_datetime",
                datetime(2026, 3, 1, 14, 30, 45, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-01T12:30:45Z",
            ),
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45), "2026-03-01T12:30:45Z"),
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("string_passthrough", "2026-03-01T12:30:45Z", "2026-03-01T12:30:45Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_updated_from(value) == expected


class TestPagination:
    def test_follows_next_url_without_resending_params(self) -> None:
        next_url = f"{TEMPO_BASE_URL}/accounts?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        result = _run([_response([{"id": 1}], next_url=next_url), _response([{"id": 2}], next_url=None)])

        assert result.rows == [{"id": 1}, {"id": 2}]
        # The first request carries the built params; the next-page URL already embeds them, so the
        # second request sends no params and targets the returned link verbatim.
        assert result.requests[0].query == {"limit": (str(PAGE_SIZE),)}
        assert result.requests[1].url == next_url
        # State saved once, after the first page, carrying the URL that fetches the second page.
        assert result.saved_states == [TempoResumeConfig(next_url=next_url)]

    def test_off_host_next_url_is_rejected(self) -> None:
        # metadata.next is server-controlled and the session carries the Bearer token, so a next URL
        # off the Tempo API host must fail (host-pinning) instead of being followed.
        result = _run([_response([{"id": 1}], next_url="https://evil.example.com/4/accounts")])

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert len(result.requests) == 1

    def test_off_host_resume_state_is_rejected(self) -> None:
        # Resume state is persisted outside the process; a poisoned next_url must not receive the
        # credentialed request.
        result = _run([], resume_state=TempoResumeConfig(next_url="https://evil.example.com/4/accounts?offset=100"))

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []


class TestTransportErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_recover(self, _name: str, status: int) -> None:
        result = _run([ScriptedResponse(status=status, json={"results": []}), _response([{"id": 1}], next_url=None)])

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        # A 429/5xx is retried rather than surfacing — the retry lands on the recovered page.
        assert len(result.requests) == 2

    def test_persistent_retryable_status_raises(self) -> None:
        result = _run(always(ScriptedResponse(status=500, json={"results": []})))

        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand(
        [("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden"), ("not_found", 404, "Not Found")]
    )
    def test_client_errors_raise_http_error(self, _name: str, status: int, reason: str) -> None:
        result = _run([ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, requests.HTTPError)

    def test_http_error_message_keeps_stable_prefix(self) -> None:
        # The message becomes the schema's latest_error and must keep the prefix
        # get_non_retryable_errors() matches on. No secret rides in the URL (the token is a header).
        result = _run(
            [ScriptedResponse(status=401, json={})],
            "worklogs",
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value="2026-03-01",
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://api.tempo.io" in str(result.raised)

    @parameterized.expand([("non_dict_body", [{"id": 1}]), ("missing_results_key", {"metadata": {"count": 0}})])
    def test_unexpected_payload_is_retried_then_recovers(self, _name: str, bad_body: Any) -> None:
        # A 200 whose body isn't the expected {"results": [...]} envelope is a transient bad shape —
        # retry, don't fail loud.
        result = _run([ScriptedResponse(json=bad_body), _response([{"id": 1}], next_url=None)])

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2


class TestTempoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _run(always(_response([], next_url=None)), endpoint)

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == TEMPO_ENDPOINTS[endpoint].primary_keys


class TestCheckAccess:
    @parameterized.expand(
        [
            ("forbidden", 403, 403, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert check_access("tempo-token") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
            assert check_access("tempo-token") == (0, "Could not connect to Tempo")

    @parameterized.expand(
        [
            # A 403 at source-create still proves the token is genuine — Tempo tokens are scoped.
            ("forbidden_at_create", 403, None, (True, None)),
            (
                "forbidden_for_schema",
                403,
                "teams",
                (False, "Your Tempo API token is missing the view scope for 'teams'"),
            ),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, endpoint: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("tempo-token", endpoint=endpoint) == expected
