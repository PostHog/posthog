from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omnisend import (
    OmnisendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    OMNISEND_API_BASE_URL,
    OMNISEND_BASE_URL,
    UNSUPPORTED_ENDPOINT_ERROR,
    OmnisendResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    OMNISEND_2026_03_15,
    OMNISEND_ENDPOINTS,
    OMNISEND_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source import OmnisendSource


def _driver() -> SourceDriver:
    return SourceDriver(OmnisendSource(), OmnisendSourceConfig(api_key="test-key"))


def _page(items: list[dict[str, Any]], next_url: str | None = None, key: str = "contacts") -> ScriptedResponse:
    return ScriptedResponse(json={key: items, "paging": {"next": next_url}})


def _next_url(offset: int) -> str:
    return f"{OMNISEND_BASE_URL}/contacts?limit=250&offset={offset}"


def _cursor_page(
    items: list[dict[str, Any]], after: str | None, has_more: bool, key: str = "contacts"
) -> ScriptedResponse:
    return ScriptedResponse(
        json={key: items, "paging": {"limit": 250, "hasMore": has_more, "cursors": {"after": after}}}
    )


class TestPagination:
    def test_follows_paging_next_until_exhausted(self) -> None:
        result = _driver().run(
            "contacts",
            [_page([{"contactID": "1"}], next_url=_next_url(250)), _page([{"contactID": "2"}])],
            api_version=OMNISEND_V3,
        )

        # First request hits the limit-seeded base path; second follows paging.next verbatim.
        assert result.requests[0].param("limit") == "250"
        assert result.requests[0].param("offset") is None
        assert result.urls == [f"{OMNISEND_BASE_URL}/contacts?limit=250", _next_url(250)]
        assert result.rows == [{"contactID": "1"}, {"contactID": "2"}]
        assert result.raised is None

    def test_missing_paging_block_terminates(self) -> None:
        result = _driver().run(
            "contacts", [ScriptedResponse(json={"contacts": [{"contactID": "1"}]})], api_version=OMNISEND_V3
        )

        assert len(result.requests) == 1
        assert result.rows == [{"contactID": "1"}]
        assert result.saved_states == []
        assert result.raised is None

    @pytest.mark.parametrize("endpoint", ["contacts", "campaigns"])
    def test_2026_follows_after_cursor_and_saves_it(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _cursor_page([{"id": "1"}], after="c1", has_more=True, key=endpoint),
                _cursor_page([{"id": "2"}], after=None, has_more=False, key=endpoint),
            ],
            api_version=OMNISEND_2026_03_15,
        )

        assert result.requests[0].path == f"/api/{endpoint}"
        assert result.requests[0].param("after") is None
        assert result.requests[1].param("after") == "c1"
        assert result.rows == [{"id": "1"}, {"id": "2"}]
        assert result.saved_states == [OmnisendResumeConfig(cursor="c1")]
        assert result.raised is None

    def test_2026_stops_when_has_more_is_false_even_with_a_cursor(self) -> None:
        result = _driver().run(
            "contacts", [_cursor_page([{"id": "1"}], after="c1", has_more=False)], api_version=OMNISEND_2026_03_15
        )

        assert len(result.requests) == 1
        assert result.rows == [{"id": "1"}]
        assert result.raised is None

    def test_2026_products_follow_paging_next_on_the_api_base(self) -> None:
        next_url = f"{OMNISEND_API_BASE_URL}/products?limit=250&offset=250"
        result = _driver().run(
            "products",
            [_page([{"id": "p1"}], next_url=next_url, key="products"), _page([{"id": "p2"}], key="products")],
            api_version=OMNISEND_2026_03_15,
        )

        assert result.urls == [f"{OMNISEND_API_BASE_URL}/products?limit=250", next_url]
        assert result.rows == [{"id": "p1"}, {"id": "p2"}]
        assert result.raised is None


class TestResume:
    def test_resume_seeds_starting_url(self) -> None:
        result = _driver().run(
            "contacts",
            [_page([{"contactID": "6"}])],
            resume_state=OmnisendResumeConfig(next_url=_next_url(500)),
            api_version=OMNISEND_V3,
        )

        assert result.urls == [_next_url(500)]
        assert result.raised is None

    def test_resume_seeds_cursor_on_2026(self) -> None:
        result = _driver().run(
            "contacts",
            [_cursor_page([{"id": "6"}], after=None, has_more=False)],
            resume_state=OmnisendResumeConfig(cursor="c5"),
            api_version=OMNISEND_2026_03_15,
        )

        assert result.requests[0].param("after") == "c5"
        assert result.raised is None

    def test_v3_next_url_is_not_followed_under_2026(self) -> None:
        result = _driver().run(
            "products",
            [_page([{"id": "p1"}], key="products")],
            resume_state=OmnisendResumeConfig(next_url=f"{OMNISEND_BASE_URL}/products?limit=250&offset=500"),
            api_version=OMNISEND_2026_03_15,
        )

        assert result.requests[0].path == "/api/products"
        assert result.requests[0].param("offset") is None
        assert result.raised is None

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("contacts", [_page([{"contactID": "1"}])], api_version=OMNISEND_V3)

        assert result.requests[0].path == "/v3/contacts"
        assert result.requests[0].param("offset") is None
        assert result.raised is None


class TestErrors:
    @pytest.mark.parametrize("status_code", [401, 403, 422])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run(
            "contacts", [ScriptedResponse(status=status_code, json={"error": "Forbidden"})], api_version=OMNISEND_V3
        )

        assert isinstance(result.raised, HTTPError)

    def test_off_host_paging_next_is_not_followed(self) -> None:
        result = _driver().run(
            "contacts",
            [_page([{"contactID": "1"}], next_url="https://attacker.example.com/contacts?offset=250")],
            api_version=OMNISEND_V3,
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert len(result.requests) == 1

    def test_missing_envelope_key_raises(self) -> None:
        # 200 OK with an unexpected body shape must fail loudly, not sync zero rows.
        result = _driver().run(
            "contacts", [ScriptedResponse(json={"unexpected": [], "paging": {"next": None}})], api_version=OMNISEND_V3
        )

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestAuthAndRedaction:
    @pytest.mark.parametrize(
        ("api_version", "base_url", "auth_header", "auth_value", "version_header"),
        [
            (OMNISEND_V3, OMNISEND_BASE_URL, "X-API-KEY", "test-key", None),
            (OMNISEND_2026_03_15, OMNISEND_API_BASE_URL, "Authorization", "Omnisend-API-Key test-key", "2026-03-15"),
        ],
    )
    def test_api_key_is_redacted_and_sent_as_header_auth(
        self, api_version: str, base_url: str, auth_header: str, auth_value: str, version_header: str | None
    ) -> None:
        result = _driver().run("contacts", [_page([{"id": "1"}])], api_version=api_version)

        # The client's session is built with the sent credential in redact_values so it's masked in
        # logs and raised errors.
        assert any(auth_value in options.get("redact_values", ()) for options in result.session_options)

        # The key rides in the version-specific header.
        request = result.requests[0]
        assert request.headers[auth_header.lower()] == auth_value
        assert request.path == f"/{'v3' if api_version == OMNISEND_V3 else 'api'}/contacts"
        assert request.url.startswith(f"{base_url}/contacts")
        assert request.headers.get("omnisend-version") == version_header
        assert result.raised is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("api_version", "expected_url", "expected_headers"),
        [
            (OMNISEND_V3, f"{OMNISEND_BASE_URL}/contacts?limit=1", {"X-API-KEY": "test-key"}),
            (
                OMNISEND_2026_03_15,
                f"{OMNISEND_API_BASE_URL}/contacts?limit=1",
                {"Authorization": "Omnisend-API-Key test-key", "Omnisend-Version": "2026-03-15"},
            ),
        ],
    )
    def test_probe_uses_the_versioned_wire(
        self, api_version: str, expected_url: str, expected_headers: dict[str, str]
    ) -> None:
        with scripted_network([ScriptedResponse(json={"contacts": []})]) as network:
            validate_credentials("test-key", api_version)

        request = network.requests_log[0]
        assert request.url == expected_url
        for name, value in expected_headers.items():
            assert request.headers[name.lower()] == value


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", ["carts", "orders"])
    def test_endpoints_without_a_2026_list_endpoint_raise(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [], api_version=OMNISEND_2026_03_15)

        assert isinstance(result.raised, ValueError)
        assert UNSUPPORTED_ENDPOINT_ERROR in str(result.raised)

    def test_every_endpoint_partition_key_is_stable(self) -> None:
        # Partition keys must be creation-time fields, never mutable ones.
        for config in OMNISEND_ENDPOINTS.values():
            if config.partition_key is not None:
                assert config.partition_key == "createdAt"
