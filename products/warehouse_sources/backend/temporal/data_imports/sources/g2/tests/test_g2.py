from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.g2 import g2
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.g2 import (
    G2ResumeConfig,
    MissingProductIdError,
    _build_url,
    _ensure_g2_url,
    _extract_error_detail,
    _flatten_item,
    g2_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.settings import G2_ENDPOINTS


class _FakeResumeManager(ResumableSourceManager[G2ResumeConfig]):
    def __init__(self, state: G2ResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[G2ResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> G2ResumeConfig | None:
        return self.state

    def save_state(self, data: G2ResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    return {"data": items, "links": {"self": "irrelevant", "next": next_url, "prev": None}}


def _resource(item_id: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": item_id, "type": "products", "attributes": attributes or {}}


def _collect_rows(
    monkeypatch: pytest.MonkeyPatch,
    pages: dict[str, dict[str, Any]],
    endpoint: str = "products",
    product_id: str = "",
    manager: ResumableSourceManager[G2ResumeConfig] | None = None,
) -> list[dict[str, Any]]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str]) -> dict[str, Any]:
        return pages[url]

    monkeypatch.setattr(g2, "_fetch_page", fake_fetch)

    rows: list[dict[str, Any]] = []
    for table in cast(
        "list[Any]",
        list(
            get_rows(
                access_token="token-1",
                endpoint=endpoint,
                product_id=product_id,
                api_version="v2",
                logger=mock.MagicMock(),
                resumable_source_manager=manager or _FakeResumeManager(),
            )
        ),
    ):
        rows.extend(table.to_pylist())
    return rows


class TestFlattenItem:
    def test_merges_attributes_into_root_alongside_id(self) -> None:
        item = _resource("p1", {"name": "Product One", "star_rating": 4.5})
        assert _flatten_item(item) == {"id": "p1", "name": "Product One", "star_rating": 4.5}

    def test_missing_attributes_yields_just_the_id(self) -> None:
        assert _flatten_item({"id": "p1", "type": "products"}) == {"id": "p1"}


class TestBuildUrl:
    def test_no_params_returns_bare_url(self) -> None:
        assert _build_url("https://data.g2.com/api/v2/products", {}) == "https://data.g2.com/api/v2/products"

    def test_encodes_bracketed_params(self) -> None:
        url = _build_url("https://data.g2.com/api/v2/products", {"page[size]": 250})
        assert url == "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"


class TestEnsureG2Url:
    def test_g2_origin_is_returned_unchanged(self) -> None:
        url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=cursor-1"
        assert _ensure_g2_url(url) == url

    @parameterized.expand(
        [
            # A pagination link or poisoned resume state pointing anywhere but the G2 API
            # origin would receive the bearer token — refuse it.
            ("foreign_host", "https://evil.example.com/api/v2/products"),
            ("http_downgrade", "http://data.g2.com/api/v2/products"),
            ("userinfo_trick", "https://data.g2.com@evil.example.com/api/v2/products"),
            ("host_suffix", "https://data.g2.com.evil.example.com/api/v2/products"),
            ("path_prefix_escape", "https://data.g2.comevil/api/v2/products"),
        ]
    )
    def test_non_g2_urls_are_refused(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError):
            _ensure_g2_url(url)


class TestExtractErrorDetail:
    def test_extracts_joined_titles(self) -> None:
        response = mock.MagicMock()
        response.json.return_value = {"errors": [{"status": "403", "title": "Forbidden"}]}
        assert _extract_error_detail(response) == "Forbidden"

    def test_returns_none_for_unparseable_body(self) -> None:
        response = mock.MagicMock()
        response.json.side_effect = ValueError("not json")
        assert _extract_error_detail(response) is None


class TestGetRowsPagination:
    def test_follows_links_next_and_flattens_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first_url = "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"
        next_url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=cursor-1&page%5Bsize%5D=250"
        pages = {
            first_url: _page([_resource("p1", {"name": "One"})], next_url=next_url),
            next_url: _page([_resource("p2", {"name": "Two"})]),
        }

        rows = _collect_rows(monkeypatch, pages)

        assert rows == [{"id": "p1", "name": "One"}, {"id": "p2", "name": "Two"}]

    def test_stops_when_next_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first_url = "https://data.g2.com/api/v2/categories?page%5Bsize%5D=250"
        pages = {first_url: _page([_resource("c1")])}

        rows = _collect_rows(monkeypatch, pages, endpoint="categories")

        assert len(rows) == 1

    def test_resumes_from_saved_next_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resume_url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=cursor-9"
        pages = {resume_url: _page([_resource("p9")])}

        rows = _collect_rows(monkeypatch, pages, manager=_FakeResumeManager(G2ResumeConfig(next_url=resume_url)))

        # No request for the first-page URL is wired, so resuming past it would raise KeyError.
        assert rows == [{"id": "p9"}]

    def test_refuses_a_links_next_pointing_off_the_g2_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first_url = "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"
        pages = {first_url: _page([_resource("p1")], next_url="https://evil.example.com/steal-token")}

        with pytest.raises(ValueError):
            _collect_rows(monkeypatch, pages)

    def test_refuses_a_saved_resume_url_pointing_off_the_g2_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        poisoned_url = "https://evil.example.com/steal-token"

        with pytest.raises(ValueError):
            _collect_rows(monkeypatch, {}, manager=_FakeResumeManager(G2ResumeConfig(next_url=poisoned_url)))

    def test_reviews_path_is_formatted_with_product_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        url = "https://data.g2.com/api/v2/products/prod-123/reviews?page%5Bsize%5D=250"
        pages = {url: _page([_resource("r1", {"title": "Great"})])}

        rows = _collect_rows(monkeypatch, pages, endpoint="reviews", product_id="prod-123")

        assert rows == [{"id": "r1", "title": "Great"}]

    def test_missing_product_id_raises_for_reviews(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(MissingProductIdError):
            _collect_rows(monkeypatch, {}, endpoint="reviews", product_id="")

    def test_missing_product_id_is_fine_for_endpoints_that_do_not_need_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = "https://data.g2.com/api/v2/vendors?page%5Bsize%5D=250"
        pages = {url: _page([_resource("v1")])}

        rows = _collect_rows(monkeypatch, pages, endpoint="vendors", product_id="")

        assert rows == [{"id": "v1"}]


class TestResumeStateSaving:
    def _drive_with_small_chunks(
        self, monkeypatch: pytest.MonkeyPatch, pages: dict[str, dict[str, Any]]
    ) -> _FakeResumeManager:
        real_batcher_cls = g2.Batcher

        def small_batcher(*args: Any, **kwargs: Any) -> Any:
            kwargs["chunk_size"] = 1
            return real_batcher_cls(*args, **kwargs)

        monkeypatch.setattr(g2, "Batcher", small_batcher)

        def fake_fetch(session: Any, url: str, headers: dict[str, str]) -> dict[str, Any]:
            return pages[url]

        monkeypatch.setattr(g2, "_fetch_page", fake_fetch)

        manager = _FakeResumeManager()
        for _table in get_rows(
            access_token="token-1",
            endpoint="products",
            product_id="",
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
        ):
            pass
        return manager

    def test_saves_state_only_while_a_later_page_remains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first_url = "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"
        second_url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=c1"
        pages = {
            first_url: _page([_resource("p1")], next_url=second_url),
            second_url: _page([_resource("p2")]),
        }

        manager = self._drive_with_small_chunks(monkeypatch, pages)

        # The first (non-terminal) page saves a checkpoint; the terminal page does not, so a
        # resumed run stops re-fetching once the sync actually finished.
        assert manager.saved == [G2ResumeConfig(next_url=second_url)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.g2.g2.make_tracked_session")
    def test_reports_the_probe_status(
        self, _name: str, status_code: int, expected: bool, mock_session_factory: mock.MagicMock
    ) -> None:
        mock_session_factory.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("token-1", "v2") == (expected, status_code)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.g2.g2.make_tracked_session")
    def test_transport_failure_does_not_raise(self, mock_session_factory: mock.MagicMock) -> None:
        mock_session_factory.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("token-1", "v2") == (False, None)


class TestG2Source:
    @parameterized.expand([(name, config.primary_keys) for name, config in G2_ENDPOINTS.items()])
    def test_primary_keys_match_settings(self, endpoint: str, primary_keys: list[str]) -> None:
        response = g2_source(
            access_token="token-1",
            endpoint=endpoint,
            product_id="prod-1",
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeResumeManager(),
        )
        assert response.primary_keys == primary_keys

    def test_sort_mode_is_unset(self) -> None:
        # No G2 list endpoint documents a `sort` param or default order, so no endpoint may claim
        # a verified direction (see settings.py).
        response = g2_source(
            access_token="token-1",
            endpoint="products",
            product_id="",
            api_version="v2",
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeResumeManager(),
        )
        assert response.sort_mode is None
