from datetime import UTC, date, datetime
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.guardian import (
    GuardianSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.guardian import (
    GuardianResumeConfig,
    _format_from_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source import GuardianSource


def _driver(api_key: str = "k") -> SourceDriver:
    return SourceDriver(GuardianSource(), GuardianSourceConfig(api_key=api_key))


def _page(
    results: list[dict[str, Any]] | None,
    *,
    pages: int | None = 1,
    current_page: int = 1,
) -> ScriptedResponse:
    inner: dict[str, Any] = {"status": "ok", "results": results or []}
    # sections/editions omit pagination metadata; content/tags report `pages`/`currentPage`.
    if pages is not None:
        inner["pages"] = pages
        inner["currentPage"] = current_page
    return ScriptedResponse(json={"response": inner})


class TestFormatFromDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T02:58:14Z", "2026-03-04"),
            ("", None),
            (None, None),
        ],
    )
    def test_format_from_date(self, value: Any, expected: str | None) -> None:
        assert _format_from_date(value) == expected


class TestRequestParams:
    def test_non_incremental_endpoint_never_sets_from_date(self) -> None:
        # tags advertises no incremental field, so even an accidental cursor value is ignored.
        result = _driver().run(
            "tags",
            [_page([{"id": "a"}])],
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.requests[0].param("from-date") is None


class TestPagination:
    def test_paginates_until_last_page(self) -> None:
        result = _driver().run(
            "content",
            [
                _page([{"id": "a"}, {"id": "b"}], pages=2, current_page=1),
                _page([{"id": "c"}], pages=2, current_page=2),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a", "b", "c"]
        assert result.params("page") == ["1", "2"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "content",
            [_page([{"id": "c"}], pages=3, current_page=3)],
            resume_state=GuardianResumeConfig(page=3),
        )

        # Resuming at page 3 skips the already-synced earlier pages.
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c"]
        assert result.params("page") == ["3"]

    def test_missing_response_envelope_raises_loudly(self) -> None:
        result = _driver().run("content", [ScriptedResponse(json={})])

        # A 200 body without the `response` envelope means the shape changed — fail loud, not 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetries:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_status_is_retried_then_reraised(self, status_code: int) -> None:
        result = _driver().run("content", always(ScriptedResponse(status=status_code, json={"response": {}})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/search"] * 5

    def test_auth_failure_raises_without_leaking_api_key(self) -> None:
        # The api-key rides in the query string; a non-2xx must not surface it in the exception, but
        # the base host must survive so get_non_retryable_errors() can still match.
        result = _driver(api_key="super-secret").run("content", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, HTTPError)
        message = str(result.raised)
        assert "super-secret" not in message
        assert "401 Client Error: Unauthorized for url: https://content.guardianapis.com/search" in message


class TestValidateCredentials:
    def test_network_error_is_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("some-key") is False

        assert {request.path for request in network.requests_log} == {"/sections"}


class TestGuardianSourceResponse:
    @pytest.mark.parametrize("endpoint", ["tags", "sections", "editions"])
    def test_reference_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([], pages=1 if endpoint == "tags" else None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_keys is None
        assert result.response.partition_mode is None
        # Full-refresh endpoints carry no order-by, so their order is unspecified.
        assert result.response.sort_mode is None
