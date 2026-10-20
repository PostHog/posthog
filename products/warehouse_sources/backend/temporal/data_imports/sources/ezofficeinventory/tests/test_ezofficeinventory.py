from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.ezofficeinventory import (
    EZOfficeInventoryResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_API_VERSION_V1,
    EZOFFICEINVENTORY_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source import (
    EZOfficeInventorySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ezofficeinventory import (
    EZOfficeInventorySourceConfig,
)


def _driver() -> SourceDriver:
    config = cast(EZOfficeInventorySourceConfig, EZOfficeInventorySourceConfig(subdomain="acme", api_key="tok"))
    return SourceDriver(EZOfficeInventorySource(), config)


class TestPagination:
    def test_paginates_until_total_pages(self) -> None:
        result = _driver().run(
            "assets",
            [
                ScriptedResponse(json={"assets": [{"identifier": 1}], "total_pages": 2}),
                ScriptedResponse(json={"assets": [{"identifier": 2}], "total_pages": 2}),
            ],
            api_version=EZOFFICEINVENTORY_API_VERSION_V1,
        )

        assert result.raised is None
        assert result.rows == [{"identifier": 1}, {"identifier": 2}]
        assert result.params("page") == ["1", "2"]
        # State saved once (after page 1), pointing at page 2 — never after the terminal page.
        assert result.saved_states == [EZOfficeInventoryResumeConfig(next_page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "assets",
            [ScriptedResponse(json={"assets": [{"identifier": 30}], "total_pages": 3})],
            resume_state=EZOfficeInventoryResumeConfig(next_page=3),
            api_version=EZOFFICEINVENTORY_API_VERSION_V1,
        )

        assert result.raised is None
        assert result.rows == [{"identifier": 30}]
        # Picks up at page 3 (the saved cursor), not page 1.
        assert result.params("page") == ["3"]
        assert result.saved_states == []


class TestUnwrap:
    @pytest.mark.parametrize(
        ("endpoint", "body", "expected"),
        [
            (
                "groups",
                {"groups": [{"group": {"id": 1}}, {"group": {"id": 2}}], "total_pages": 1},
                [{"id": 1}, {"id": 2}],
            ),
            ("vendors", {"vendors": [{"vendor": {"id": 9}}], "total_pages": 1}, [{"id": 9}]),
            # A row already shaped like the unwrapped object passes through untouched.
            ("groups", {"groups": [{"id": 5}], "total_pages": 1}, [{"id": 5}]),
        ],
    )
    def test_unwraps_single_key_items(
        self, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)], api_version=EZOFFICEINVENTORY_API_VERSION_V1)

        assert result.raised is None
        assert result.rows == expected


class TestRetryableFetch:
    def test_client_error_fails_loud(self) -> None:
        result = _driver().run(
            "assets",
            [ScriptedResponse(status=401, json={"error": "unauthorized"})],
            api_version=EZOFFICEINVENTORY_API_VERSION_V1,
        )

        assert isinstance(result.raised, Exception)


class TestValidateCredentials:
    @pytest.mark.parametrize("bad_subdomain", ["", "has space", "bad/slash", "a.b", "http://x"])
    def test_rejects_unsafe_subdomain_without_network(self, bad_subdomain: str) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("tok", bad_subdomain, EZOFFICEINVENTORY_API_VERSION_V1) == (False, None)

        assert network.requests_log == []
        assert network.session_options == []

    @pytest.mark.parametrize(
        ("api_version", "expected_url", "expected_header"),
        [
            (
                EZOFFICEINVENTORY_API_VERSION_V1,
                "https://acme.ezofficeinventory.com/assets.api?page=1",
                ("token", "tok"),
            ),
            (
                EZOFFICEINVENTORY_API_VERSION_V2,
                "https://acme.ezofficeinventory.com/api/v2/assets",
                ("Authorization", "Bearer tok"),
            ),
        ],
    )
    def test_probes_versioned_path_and_auth(
        self, api_version: str, expected_url: str, expected_header: tuple[str, str]
    ) -> None:
        # A passing probe must exercise the same base path and auth scheme the sync will use for
        # that version — otherwise the probe validates a path the pinned sync never calls.
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            is_valid, _ = validate_credentials("tok", "acme", api_version)

        assert is_valid is True
        assert network.requests_log[0].url == expected_url
        header_name, header_value = expected_header
        assert network.requests_log[0].headers[header_name.lower()] == header_value

    def test_rate_limit_returns_specific_message(self) -> None:
        with scripted_network([ScriptedResponse(status=429, json={})]):
            is_valid, error = validate_credentials("tok", "acme", EZOFFICEINVENTORY_API_VERSION_V1)

        assert is_valid is False
        assert error is not None
        assert "rate limit" in error.lower()

    def test_validation_session_disables_redirects_and_urllib3_retries(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            validate_credentials("tok", "acme", EZOFFICEINVENTORY_API_VERSION_V1)

        assert network.session_options[0]["allow_redirects"] is False
        # Single-shot validation handles status codes itself; urllib3 retries stay off.
        assert network.session_options[0]["retry"].total == 0


class TestV2Pagination:
    def test_follows_metadata_next_page_and_saves_cursor(self) -> None:
        next_url = "https://acme.ezofficeinventory.com/api/v2/assets?page=2"
        result = _driver().run(
            "assets",
            [
                ScriptedResponse(json={"assets": [{"identifier": 1}], "metadata": {"next_page": next_url}}),
                ScriptedResponse(json={"assets": [{"identifier": 2}], "metadata": {"next_page": None}}),
            ],
            api_version=EZOFFICEINVENTORY_API_VERSION_V2,
        )

        assert result.raised is None
        assert result.rows == [{"identifier": 1}, {"identifier": 2}]
        assert result.paths == ["/api/v2/assets", "/api/v2/assets"]
        assert result.params("page") == [None, "2"]
        # Checkpoint carries the next-page URL, not a page number — the v2 resume shape.
        assert result.saved_states == [EZOfficeInventoryResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_cursor(self) -> None:
        next_url = "https://acme.ezofficeinventory.com/api/v2/assets?page=2"
        result = _driver().run(
            "assets",
            [ScriptedResponse(json={"assets": [{"identifier": 2}], "metadata": {"next_page": None}})],
            resume_state=EZOfficeInventoryResumeConfig(next_url=next_url),
            api_version=EZOFFICEINVENTORY_API_VERSION_V2,
        )

        assert result.raised is None
        assert result.rows == [{"identifier": 2}]
        # One request only: the saved cursor is the starting point, not page 1 followed by it.
        assert result.urls == [next_url]
        assert result.saved_states == []


class TestHistoryFanout:
    """The history tables are per-item sub-resources fanned out over their list endpoint."""

    def test_fetches_each_parent_and_injects_parent_id(self) -> None:
        result = _driver().run(
            "asset_checkout_history",
            [
                ScriptedResponse(
                    json={"assets": [{"id": 1, "identifier": "A1"}, {"id": 2, "identifier": "A2"}], "metadata": {}}
                ),
                ScriptedResponse(json={"histories": [{"id": 10}], "metadata": {}}),
                ScriptedResponse(json={"histories": [{"id": 20}], "metadata": {}}),
            ],
            api_version=EZOFFICEINVENTORY_API_VERSION_V2,
        )

        assert result.raised is None
        # The child path binds the parent's record id, not its identification number.
        assert result.paths[1:] == ["/api/v2/assets/1/history", "/api/v2/assets/2/history"]
        # A history row carries no back-reference to its asset, so the parent id is injected —
        # without it the composite primary key would collapse every asset's history together.
        assert result.rows == [{"id": 10, "asset_id": 1}, {"id": 20, "asset_id": 2}]

    def test_child_pages_are_followed_per_parent(self) -> None:
        next_url = "https://acme.ezofficeinventory.com/api/v2/assets/1/history?page=2"
        result = _driver().run(
            "asset_checkout_history",
            [
                ScriptedResponse(json={"assets": [{"id": 1}], "metadata": {}}),
                ScriptedResponse(json={"histories": [{"id": 10}], "metadata": {"next_page": next_url}}),
                ScriptedResponse(json={"histories": [{"id": 11}], "metadata": {"next_page": None}}),
            ],
            api_version=EZOFFICEINVENTORY_API_VERSION_V2,
        )

        assert result.raised is None
        assert result.rows == [{"id": 10, "asset_id": 1}, {"id": 11, "asset_id": 1}]
        assert result.urls[2] == next_url
        # A fan-out run is full refresh with no resumable cursor: a mid-run checkpoint would
        # point at a child page without recording which parents were already walked.
        assert result.saved_states == []
