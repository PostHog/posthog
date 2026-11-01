from collections.abc import Sequence
from typing import Any

import pytest

from requests.exceptions import HTTPError
from structlog.testing import capture_logs

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rapid7insightvm import (
    Rapid7InsightvmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm import (
    Rapid7InsightvmResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.source import (
    Rapid7InsightvmSource,
)


def _page(items: list[dict[str, Any]] | None, cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items or [], "metadata": {"cursor": cursor} if cursor is not None else {}})


def _numbered_page(items: list[dict[str, Any]], number: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "metadata": {"number": number, "totalPages": total_pages}})


def _error(status: int, body: dict[str, Any] | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body or {})


def _redirect(location: str = "https://evil.example.com/") -> ScriptedResponse:
    return ScriptedResponse(status=302, headers={"Location": location})


def _run(
    responses: Sequence[ScriptedResponse | BaseException],
    api_key: str = "key",
    schema: str = "assets",
    **inputs: Any,
) -> DriveResult:
    config = Rapid7InsightvmSourceConfig(api_key=api_key, region="us")
    return SourceDriver(Rapid7InsightvmSource(), config).run(schema, responses, **inputs)


class TestPagination:
    def test_saves_cursor_after_each_yielded_batch(self) -> None:
        pages = [
            _page([{"id": 1}], cursor="c1"),
            _page([{"id": 2}], cursor="c2"),
            _page([{"id": 3}], cursor=None),
        ]
        result = _run(pages)

        # State is persisted only for pages with a successor cursor (c1, c2); the final page (no next
        # cursor) saves nothing, so a resumed run re-yields the last page rather than skipping it.
        assert [state.cursor for state in result.saved_states] == ["c1", "c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _run(
            [_page([{"id": 99}], cursor=None)], resume_state=Rapid7InsightvmResumeConfig(cursor="saved-cursor")
        )

        # The first (and only) request must carry the saved cursor as its starting point.
        assert result.params("cursor") == ["saved-cursor"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run([_page([{"id": 99}], cursor=None)])

        assert result.params("cursor") == [None]


class TestPageNumberPagination:
    @pytest.mark.parametrize(
        "schema, total_pages, expected_requests, truncated",
        [
            ("scans", 2, 2, False),
            ("scan_engines", 2, 2, False),
            ("scans", 20, 20, False),
            # The API serves at most 10,000 results through page/size, so the walk stops at page 19.
            ("scans", 25, 20, True),
        ],
    )
    def test_walks_pages_with_get_until_the_last_page(
        self, schema: str, total_pages: int, expected_requests: int, truncated: bool
    ) -> None:
        pages = [_numbered_page([{"id": f"{schema}-{n}"}], n, total_pages) for n in range(expected_requests)]
        with capture_logs() as logs:
            result = _run(pages, schema=schema)

        assert result.raised is None
        assert {request.method for request in result.requests} == {"GET"}
        assert result.params("page") == [str(n) for n in range(expected_requests)]
        assert set(result.params("size")) == {"500"}
        assert len(result.rows) == expected_requests
        assert [state.page for state in result.saved_states] == list(range(1, expected_requests))
        assert any("10,000-result page window" in log["event"] for log in logs) is truncated

    def test_resumes_from_saved_page(self) -> None:
        result = _run(
            [_numbered_page([{"id": "s"}], 3, 4)],
            schema="scans",
            resume_state=Rapid7InsightvmResumeConfig(page=3),
        )

        assert result.params("page") == ["3"]


class TestRetryAndErrorClassification:
    def test_client_error_raises_http_error(self) -> None:
        # A 403 is permanent — surface it as an HTTPError instead of retrying.
        result = _run([_error(403)])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestCredentialedSessionIsHardened:
    def test_redirect_is_rejected(self) -> None:
        # A 3xx from the credentialed endpoint would replay `X-Api-Key` to the redirect target;
        # the client pins redirects off and rejects any 3xx before following it.
        result = _run([_redirect()])

        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
        assert len(result.requests) == 1

    def test_api_key_is_redacted_from_errors(self) -> None:
        # The key must never leak into a user-visible error message.
        result = _run(
            [_redirect(location="https://us.api.insight.rapid7.com/?token=super-secret-key")],
            api_key="super-secret-key",
        )

        assert isinstance(result.raised, ValueError)
        assert "super-secret-key" not in str(result.raised)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
        ],
    )
    def test_status_maps_to_validity(self, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid
        assert network.requests_log[0].method == "POST"
        assert network.requests_log[0].headers["x-api-key"] == "key"

    def test_probe_pins_redirects_off_and_redacts_key(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("secret-key", "us")

        assert network.session_options == [{"redact_values": ("secret-key",), "allow_redirects": False}]
