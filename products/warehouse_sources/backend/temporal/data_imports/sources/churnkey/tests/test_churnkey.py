from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey import (
    ChurnkeyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
    CHURNKEY_ENDPOINTS,
    DEFAULT_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source import ChurnkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.churnkey import (
    ChurnkeySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ChurnkeySource(), ChurnkeySourceConfig(api_key="data_key", app_id="app_123"))


class TestValidateCredentials:
    def test_network_failure_returns_none_status(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key", "app") == (False, None)

        assert network.requests_log[0].path == "/v1/data/sessions"
        assert network.requests_log[0].param("limit") == "1"


class TestPagination:
    def test_fresh_run_pages_and_saves_after_each_non_terminal_page(self) -> None:
        pages = [
            [{"_id": "1"}, {"_id": "2"}],
            [{"_id": "3"}, {"_id": "4"}],
            [{"_id": "5"}],  # short page → terminal
        ]
        with patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2):
            result = _driver().run("Sessions", [ScriptedResponse(json=page) for page in pages])

        assert result.raised is None
        assert [row["_id"] for row in result.rows] == ["1", "2", "3", "4", "5"]
        # skip advances by the page size (2) each request, starting at 0.
        assert result.params("skip") == ["0", "2", "4"]
        assert result.params("limit") == ["2", "2", "2"]
        # State saved only after the two full (non-terminal) pages, never after the short one.
        assert result.saved_states == [ChurnkeyResumeConfig(skip=2), ChurnkeyResumeConfig(skip=4)]

    def test_resume_starts_from_saved_skip(self) -> None:
        with patch.object(CHURNKEY_ENDPOINTS["Sessions"], "page_size", 2):
            result = _driver().run(
                "Sessions",
                [ScriptedResponse(json=[{"_id": "5"}])],
                resume_state=ChurnkeyResumeConfig(skip=4),
            )

        assert result.raised is None
        assert [row["_id"] for row in result.rows] == ["5"]
        assert result.params("skip") == ["4"]

    def test_non_list_body_raises_loudly(self) -> None:
        # The endpoint returns a bare array — a non-list 200 body means the response shape
        # changed, so fail loud instead of syncing garbage.
        result = _driver().run("Sessions", [ScriptedResponse(json={"error": "unexpected envelope"})])

        assert isinstance(result.raised, ValueError)
        assert "Required a list response body" in str(result.raised)


class TestChurnkeySource:
    def test_default_page_size_within_api_cap(self) -> None:
        # The API rejects limit > 10,000.
        assert 0 < DEFAULT_PAGE_SIZE <= 10_000
