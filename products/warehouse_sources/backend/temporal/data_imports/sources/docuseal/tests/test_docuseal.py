from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.docuseal import (
    DEFAULT_REGION,
    DOCUSEAL_HOSTS,
    PAGE_SIZE,
    DocusealResumeConfig,
    _base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.source import DocusealSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docuseal import (
    DocusealSourceConfig,
)


def _response(rows: list[dict[str, Any]], next_cursor: int | None) -> ScriptedResponse:
    body = {"data": rows, "pagination": {"count": len(rows), "next": next_cursor, "prev": None}}
    return ScriptedResponse(json=body)


def _rows(start_id: int, count: int) -> list[dict[str, Any]]:
    """`count` rows in DocuSeal's newest-first (descending id) order, starting at `start_id`."""
    return [{"id": start_id - offset, "created_at": "2026-01-01T00:00:00Z"} for offset in range(count)]


def _driver() -> SourceDriver:
    return SourceDriver(DocusealSource(), DocusealSourceConfig(api_key="tok", region="us"))


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", DOCUSEAL_HOSTS["us"]),
            ("eu", DOCUSEAL_HOSTS["eu"]),
            (None, DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("", DOCUSEAL_HOSTS[DEFAULT_REGION]),
            ("unknown", DOCUSEAL_HOSTS[DEFAULT_REGION]),
        ]
    )
    def test_picks_correct_base_url(self, region: str | None, expected: str) -> None:
        assert _base_url(region) == expected


class TestValidateCredentials:
    def test_probes_selected_region_host(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            success, error = validate_credentials("key", "eu")

        assert success is True
        assert error is None
        assert network.requests_log[0].url.startswith(DOCUSEAL_HOSTS["eu"])

    def test_returns_false_on_network_error(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            success, error = validate_credentials("key", "us")

        assert success is False
        assert error is not None
        assert "could not reach docuseal" in error.lower()


class TestPagination:
    def test_stops_when_next_cursor_is_null(self) -> None:
        # A full-size page whose `next` is null must still terminate.
        result = _driver().run("templates", [_response(_rows(100, PAGE_SIZE), next_cursor=None)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.paths == ["/templates"]

    def test_resume_uses_saved_after_cursor(self) -> None:
        result = _driver().run(
            "templates", [_response(_rows(499, 2), next_cursor=498)], resume_state=DocusealResumeConfig(after=500)
        )

        # First request must continue from the saved cursor, not start over.
        assert result.raised is None
        assert result.params("after") == ["500"]
        assert [row["id"] for row in result.rows] == [499, 498]

    def test_saves_only_already_fetched_cursors_after_yield(self) -> None:
        # Walk several full pages then a short one, and assert we never persist a cursor we haven't
        # fetched from yet (the "save current page, not next" invariant) — otherwise a crash would
        # skip rows still buffered.
        result = _driver().run(
            "templates",
            [
                _response(_rows(1000, PAGE_SIZE), next_cursor=901),
                _response(_rows(900, PAGE_SIZE), next_cursor=801),
                _response(_rows(800, PAGE_SIZE), next_cursor=701),
                _response(_rows(700, 50), next_cursor=651),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 3 * PAGE_SIZE + 50
        assert result.saved_states, "expected at least one checkpoint save across the walk"
        fetched_afters = {int(after) if after is not None else None for after in result.params("after")}
        saved_afters = [state.after for state in result.saved_states]
        assert result.params("after") == [None, "901", "801", "701"]
        assert all(after in fetched_afters for after in saved_afters)


class TestDocusealSourceResponse:
    @parameterized.expand(["templates", "submissions", "submitters"])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([], next_cursor=None)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Rows arrive newest-first, so the pipeline must not assume ascending order.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
