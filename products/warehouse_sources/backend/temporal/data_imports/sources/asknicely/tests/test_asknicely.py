from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import (
    AskNicelyResumeConfig,
    _to_unix_timestamp,
    build_responses_url,
    build_stats_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import (
    RESPONSES_PAGE_SIZE,
    UNSUBSCRIBED_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.source import AsknicelySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asknicely import (
    AsknicelySourceConfig,
)


def _response(rows: list[dict[str, Any]], total_pages: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"success": True, "data": rows}
    if total_pages is not None:
        body["totalpages"] = str(total_pages)
    return ScriptedResponse(json=body)


class TestAsknicely:
    @pytest.mark.parametrize("subdomain", ["", "acme.asknice.ly", "a/b", "a b", "-leading"])
    def test_build_responses_url_rejects_invalid_subdomain(self, subdomain: str) -> None:
        with pytest.raises(ValueError):
            build_responses_url(subdomain, page_number=1, since_time=0)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            (date(2023, 11, 14), 1699920000),
        ],
    )
    def test_to_unix_timestamp(self, value: Any, expected: int) -> None:
        assert _to_unix_timestamp(value) == expected

    @pytest.mark.parametrize("value", ["not-a-timestamp", None, True, {"ts": 1}])
    def test_to_unix_timestamp_rejects_unusable_values(self, value: Any) -> None:
        with pytest.raises(ValueError):
            _to_unix_timestamp(value)

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(AsknicelySource(), AsknicelySourceConfig(subdomain="acme", api_key="key"))

    def test_paginates_until_totalpages_and_normalizes_rows(self) -> None:
        responses = [
            _response([{"response_id": "r1", "responded": "100"}], total_pages=2),
            _response([{"response_id": "r2", "responded": "200"}], total_pages=2),
        ]

        result = self._driver().run("responses", responses)

        assert result.raised is None
        assert [row["response_id"] for row in result.rows] == ["r1", "r2"]
        # String timestamps are coerced to ints via the data_map.
        assert result.rows[0]["responded"] == 100
        assert result.urls == [
            build_responses_url("acme", page_number=1, since_time=0),
            build_responses_url("acme", page_number=2, since_time=0),
        ]
        # Only the intermediate page boundary is checkpointed — never past the final page.
        assert result.saved_states == [AskNicelyResumeConfig(page_number=2, since_time=0)]

    def test_stops_on_empty_page_when_totalpages_missing(self) -> None:
        responses = [
            _response([{"response_id": f"r{i}", "responded": "100"} for i in range(RESPONSES_PAGE_SIZE)]),
            _response([]),
        ]

        result = self._driver().run("responses", responses)

        assert result.raised is None
        assert len(result.rows) == RESPONSES_PAGE_SIZE
        assert len(result.requests) == 2

    def test_incremental_since_time_steps_back_one_second(self) -> None:
        result = self._driver().run(
            "responses",
            [_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )
        assert result.raised is None
        assert result.urls == [build_responses_url("acme", page_number=1, since_time=1699999999)]

    def test_incremental_since_time_clamps_at_zero(self) -> None:
        result = self._driver().run(
            "responses",
            [_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=0,
        )
        assert result.raised is None
        assert result.urls == [build_responses_url("acme", page_number=1, since_time=0)]

    def test_resumes_from_saved_page_and_cutoff(self) -> None:
        # The saved since_time must win over a freshly derived one: page numbering is only
        # stable against the cutoff the interrupted run used.
        result = self._driver().run(
            "responses",
            [_response([])],
            resume_state=AskNicelyResumeConfig(page_number=3, since_time=500),
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.urls == [build_responses_url("acme", page_number=3, since_time=500)]

    def test_no_checkpoint_on_single_short_page(self) -> None:
        # A run that finishes on its first page must never checkpoint — there is no next page.
        result = self._driver().run("responses", [_response([{"response_id": "r1", "responded": "100"}])])
        assert result.raised is None
        assert result.saved_states == []

    def test_unsubscribed_paginates_by_page_number_and_normalizes_rows(self) -> None:
        first = [
            {"id": str(i), "unsubscribetime": "1452219376", "email": f"c{i}@example.com"}
            for i in range(UNSUBSCRIBED_PAGE_SIZE)
        ]
        responses = [_response(first), _response([{"id": "last", "unsubscribetime": "1452219999"}])]

        result = self._driver().run("contacts_unsubscribed", responses)

        assert result.raised is None
        assert len(result.rows) == UNSUBSCRIBED_PAGE_SIZE + 1
        # The unix timestamp arrives as a string; it has to be an int to partition on and to
        # compare against the responses table's timestamps.
        assert result.rows[0]["unsubscribetime"] == 1452219376
        assert result.paths == ["/api/v1/contacts/unsubscribed"] * 2
        assert [request.origin for request in result.requests] == ["https://acme.asknice.ly"] * 2
        assert result.params("pagenumber") == ["1", "2"]
        assert result.params("pagesize") == [str(UNSUBSCRIBED_PAGE_SIZE)] * 2
        # The short second page ends the walk, so only the one page boundary is checkpointed.
        assert result.saved_states == [AskNicelyResumeConfig(page_number=2, since_time=0)]

    def test_unsubscribed_resumes_from_saved_page(self) -> None:
        result = self._driver().run(
            "contacts_unsubscribed", [_response([])], resume_state=AskNicelyResumeConfig(page_number=3, since_time=0)
        )

        assert result.raised is None
        assert result.params("pagenumber") == ["3"]

    def test_stats_fetches_one_page_and_never_checkpoints(self) -> None:
        # The stats series comes back whole, so a second request would re-read the same rows
        # and a saved checkpoint would leave a later run resuming a page that never existed.
        result = self._driver().run(
            "stats",
            [_response([{"year": "2023", "month": "8", "day": "16", "nps": "50.0"}])],
        )

        assert result.raised is None
        assert [row["day"] for row in result.rows] == ["16"]
        assert result.urls == [build_stats_url("acme")]
        assert result.saved_states == []

    def test_sync_session_disables_capture_and_redirects(self) -> None:
        # Survey bodies stay out of HTTP sample capture, and the X-apikey header must never be
        # replayed to a redirect target.
        result = self._driver().run("responses", [_response([])])
        assert result.raised is None
        assert result.session_options[0]["capture"] is False
        assert result.session_options[0]["allow_redirects"] is False

    def test_validate_credentials_session_disables_redirects(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("acme", "key") == (True, None)
        assert network.session_options[0]["allow_redirects"] is False
        assert network.session_options[0]["capture"] is False

    def test_validate_credentials_rejects_invalid_subdomain(self) -> None:
        with scripted_network([]) as network:
            # An invalid subdomain raises inside build_responses_url before any request is made,
            # and validate_credentials swallows it into a (False, message) result.
            is_valid, error_message = validate_credentials("bad domain", "key")

        assert is_valid is False
        assert error_message is not None
        assert network.requests_log == []
