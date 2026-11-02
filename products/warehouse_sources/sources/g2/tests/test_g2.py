from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.g2 import (
    G2ResumeConfig,
    MissingProductIdError,
    _build_url,
    _ensure_g2_url,
    _extract_error_detail,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.settings import G2_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.source import G2Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.g2 import G2SourceConfig


def _driver(product_id: str = "prod-1") -> SourceDriver:
    return SourceDriver(G2Source(), G2SourceConfig(access_token="token-1", product_id=product_id))


def _page(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "links": {"self": "irrelevant", "next": next_url, "prev": None}})


def _resource(item_id: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": item_id, "type": "products", "attributes": attributes or {}}


class TestBuildUrl:
    def test_no_params_returns_bare_url(self) -> None:
        assert _build_url("https://data.g2.com/api/v2/products", {}) == "https://data.g2.com/api/v2/products"


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
    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=cursor-9"
        result = _driver().run("products", [_page([_resource("p9")])], resume_state=G2ResumeConfig(next_url=resume_url))

        assert result.raised is None
        assert result.urls == [resume_url]
        assert [row for table in result.items for row in table.to_pylist()] == [{"id": "p9"}]

    def test_refuses_a_links_next_pointing_off_the_g2_origin(self) -> None:
        first_url = "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"
        result = _driver().run("products", [_page([_resource("p1")], next_url="https://evil.example.com/steal-token")])

        assert isinstance(result.raised, ValueError)
        assert result.urls == [first_url]

    def test_refuses_a_saved_resume_url_pointing_off_the_g2_origin(self) -> None:
        poisoned_url = "https://evil.example.com/steal-token"
        result = _driver().run("products", [], resume_state=G2ResumeConfig(next_url=poisoned_url))

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    def test_missing_product_id_raises_for_reviews(self) -> None:
        result = _driver(product_id="").run("reviews", [])

        assert isinstance(result.raised, MissingProductIdError)
        assert result.requests == []


class TestResumeStateSaving:
    def test_saves_state_only_while_a_later_page_remains(self) -> None:
        first_url = "https://data.g2.com/api/v2/products?page%5Bsize%5D=250"
        second_url = "https://data.g2.com/api/v2/products?page%5Bafter%5D=c1"
        result = _driver().run(
            "products",
            [
                _page([_resource(f"p{i}") for i in range(2000)], next_url=second_url),
                _page([_resource("p2000")]),
            ],
        )

        # The first (non-terminal) page saves a checkpoint; the terminal page does not, so a
        # resumed run stops re-fetching once the sync actually finished.
        assert result.raised is None
        assert result.urls == [first_url, second_url]
        assert result.params("page[size]") == ["250", None]
        assert len(result.items) == 2
        assert sum(table.num_rows for table in result.items) == 2001
        assert result.saved_states == [G2ResumeConfig(next_url=second_url)]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden", 403, False),
        ]
    )
    def test_reports_the_probe_status(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            result = validate_credentials("token-1", "v2")

        assert result == (expected, status_code)
        assert network.requests_log[0].path == "/api/v2/categories"
        assert network.requests_log[0].param("page[size]") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token-1"


class TestG2Source:
    @parameterized.expand([(name, config.primary_keys) for name, config in G2_ENDPOINTS.items()])
    def test_primary_keys_match_settings(self, endpoint: str, primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == primary_keys
