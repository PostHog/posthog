from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.segment import segment
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment import (
    PAGE_SIZE,
    SegmentResumeConfig,
    _base_url,
    _build_url,
    _extract_rows,
    _next_cursor,
    _redact_rows,
    get_rows,
    segment_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import (
    REGION_BASE_URLS,
    SEGMENT_ENDPOINTS,
)


class _FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, state: SegmentResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SegmentResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SegmentResumeConfig | None:
        return self._state

    def save_state(self, data: SegmentResumeConfig) -> None:
        self.saved.append(data)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "api", "https://api.segmentapis.com"),
            ("eu", "eu1", "https://eu1.api.segmentapis.com"),
            # An unknown region falls back to the US host rather than building a broken URL.
            ("unknown", "mars", "https://api.segmentapis.com"),
        ]
    )
    def test_base_url(self, _name: str, region: str, expected: str) -> None:
        assert _base_url(region) == expected

    def test_both_documented_regions_are_covered(self) -> None:
        assert set(REGION_BASE_URLS) == {"api", "eu1"}


class TestBuildUrl:
    def test_first_page_has_count_and_no_cursor(self) -> None:
        url = _build_url("https://api.segmentapis.com", "/sources", None)
        assert url == f"https://api.segmentapis.com/sources?pagination[count]={PAGE_SIZE}"

    def test_cursor_is_url_encoded(self) -> None:
        # Segment cursors are base64 and contain `=` padding, which must be percent-encoded in a query value.
        url = _build_url("https://api.segmentapis.com", "/sources", "Mw==")
        assert url == f"https://api.segmentapis.com/sources?pagination[count]={PAGE_SIZE}&pagination[cursor]=Mw%3D%3D"

    def test_bracket_keys_stay_literal(self) -> None:
        # Segment expects literal brackets in the pagination keys, not percent-encoded ones.
        url = _build_url("https://api.segmentapis.com", "/labels", "abc")
        assert "pagination[count]" in url
        assert "%5B" not in url


class TestExtractRows:
    @parameterized.expand(
        [
            ("sources_key", {"data": {"sources": [{"id": "s1"}], "pagination": {}}}, [{"id": "s1"}]),
            # The array key isn't always the endpoint name: audit-events returns it under "events".
            ("events_key", {"data": {"events": [{"id": "e1"}], "pagination": {}}}, [{"id": "e1"}]),
            ("labels_key", {"data": {"labels": [{"key": "env", "value": "dev"}]}}, [{"key": "env", "value": "dev"}]),
            ("empty_list", {"data": {"sources": [], "pagination": {}}}, []),
            ("no_data", {}, []),
            ("data_not_dict", {"data": []}, []),
        ]
    )
    def test_extract_rows(self, _name: str, body: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _extract_rows(body) == expected

    def test_pagination_object_is_never_returned_as_rows(self) -> None:
        # `pagination` is a dict, not a list, so it must not be mistaken for the resource array.
        body = {"data": {"pagination": {"next": "x"}, "sources": [{"id": "s1"}]}}
        assert _extract_rows(body) == [{"id": "s1"}]


class TestRedactRows:
    def test_no_redacted_fields_returns_rows_unchanged(self) -> None:
        rows = [{"id": "1", "settings": {"k": "v"}}]
        assert _redact_rows(rows, frozenset()) == rows

    def test_drops_only_the_named_fields(self) -> None:
        rows = [{"id": "1", "settings": {"apiKey": "secret"}, "name": "keep"}]
        assert _redact_rows(rows, frozenset({"settings"})) == [{"id": "1", "name": "keep"}]

    def test_non_dict_rows_pass_through(self) -> None:
        # Defensive: a malformed row that isn't a dict should not raise.
        malformed: list[Any] = ["not-a-dict"]
        assert _redact_rows(malformed, frozenset({"settings"})) == malformed


class TestNextCursor:
    @parameterized.expand(
        [
            ("has_next", {"data": {"pagination": {"next": "Mw=="}}}, "Mw=="),
            ("next_null", {"data": {"pagination": {"next": None}}}, None),
            ("next_empty", {"data": {"pagination": {"next": ""}}}, None),
            ("no_pagination", {"data": {"sources": []}}, None),
            ("no_data", {}, None),
        ]
    )
    def test_next_cursor(self, _name: str, body: dict[str, Any], expected: str | None) -> None:
        assert _next_cursor(body) == expected


class TestGetRows:
    @staticmethod
    def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, pages: list[dict]) -> list[dict]:
        """Drive get_rows with a queue of fake page bodies, returning the flattened rows."""
        page_iter = iter(pages)

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return next(page_iter)

        monkeypatch.setattr(segment, "_fetch", fake_fetch)
        monkeypatch.setattr(segment, "make_tracked_session", lambda *a, **k: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="tok",
            region="api",
            config=SEGMENT_ENDPOINTS[endpoint],
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_paginates_until_next_is_absent(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = [
            {"data": {"sources": [{"id": "s1"}], "pagination": {"next": "c1"}}},
            {"data": {"sources": [{"id": "s2"}], "pagination": {"next": "c2"}}},
            {"data": {"sources": [{"id": "s3"}], "pagination": {"next": None}}},
        ]
        rows = self._collect("sources", manager, monkeypatch, pages)
        assert rows == [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}]

    def test_saves_cursor_after_each_non_terminal_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = [
            {"data": {"sources": [{"id": "s1"}], "pagination": {"next": "c1"}}},
            {"data": {"sources": [{"id": "s2"}], "pagination": {"next": "c2"}}},
            {"data": {"sources": [{"id": "s3"}], "pagination": {"next": None}}},
        ]
        self._collect("sources", manager, monkeypatch, pages)
        # State is saved only for the pages that have a next cursor — never on the terminal page.
        assert manager.saved == [SegmentResumeConfig(cursor="c1"), SegmentResumeConfig(cursor="c2")]

    def test_terminal_single_page_saves_no_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = [{"data": {"sources": [{"id": "only"}], "pagination": {"next": None}}}]
        self._collect("sources", manager, monkeypatch, pages)
        assert manager.saved == []

    def test_resume_starts_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(state=SegmentResumeConfig(cursor="resumed"))
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            captured_urls.append(url)
            return {"data": {"sources": [{"id": "s9"}], "pagination": {"next": None}}}

        monkeypatch.setattr(segment, "_fetch", fake_fetch)
        monkeypatch.setattr(segment, "make_tracked_session", lambda *a, **k: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="tok",
            region="api",
            config=SEGMENT_ENDPOINTS["sources"],
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)

        assert rows == [{"id": "s9"}]
        assert "pagination[cursor]=resumed" in captured_urls[0]

    def test_credential_fields_are_redacted(self, monkeypatch: Any) -> None:
        # Credential-like config must never reach the queryable warehouse table.
        cases = [
            ("destinations", {"id": "d1", "settings": {"apiKey": "secret"}}, {"id": "d1"}),
            ("warehouses", {"id": "w1", "settings": {"password": "secret"}}, {"id": "w1"}),
            ("sources", {"id": "s1", "writeKeys": ["wk_secret"]}, {"id": "s1"}),
        ]
        for endpoint, raw_row, expected_row in cases:
            manager = _FakeResumableManager()
            pages = [{"data": {endpoint: [raw_row], "pagination": {"next": None}}}]
            rows = self._collect(endpoint, manager, monkeypatch, pages)
            assert rows == [expected_row], endpoint

    def test_single_object_endpoint_yields_one_row_and_no_pagination(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        captured_urls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            captured_urls.append(url)
            return {"data": {"workspace": {"id": "w1", "name": "Acme", "slug": "acme"}}}

        monkeypatch.setattr(segment, "_fetch", fake_fetch)
        monkeypatch.setattr(segment, "make_tracked_session", lambda *a, **k: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="tok",
            region="api",
            config=SEGMENT_ENDPOINTS["workspace"],
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)

        assert rows == [{"id": "w1", "name": "Acme", "slug": "acme"}]
        # The workspace endpoint hits its bare path once, with no pagination params.
        assert captured_urls == ["https://api.segmentapis.com/"]
        assert manager.saved == []


class TestSegmentSource:
    @parameterized.expand([(name,) for name in SEGMENT_ENDPOINTS])
    def test_source_response_carries_endpoint_primary_keys(self, endpoint: str) -> None:
        response = segment_source(
            api_token="tok",
            region="api",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == SEGMENT_ENDPOINTS[endpoint].primary_keys

    def test_labels_use_composite_primary_key(self) -> None:
        response = segment_source(
            api_token="tok",
            region="api",
            endpoint="labels",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.primary_keys == ["key", "value"]

    @parameterized.expand(
        [
            ("audit_events_partitions_on_timestamp", "audit_events", "datetime", ["timestamp"]),
            ("sources_unpartitioned", "sources", None, None),
        ]
    )
    def test_partitioning(
        self, _name: str, endpoint: str, expected_mode: str | None, expected_keys: list[str] | None
    ) -> None:
        response = segment_source(
            api_token="tok",
            region="api",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_mode == expected_mode
        assert response.partition_keys == expected_keys
