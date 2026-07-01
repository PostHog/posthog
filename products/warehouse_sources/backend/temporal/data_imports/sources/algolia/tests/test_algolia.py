from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia import (
    AlgoliaResumeConfig,
    InvalidApplicationIdError,
    _base_url,
    _endpoint_url,
    algolia_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.algolia.settings import ALGOLIA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _response(body: dict[str, Any], status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = body
    resp.text = str(body)
    return resp


def _rows(tables: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for table in tables:
        assert isinstance(table, pa.Table)
        out.extend(table.to_pylist())
    return out


class TestBaseUrl:
    def test_builds_per_application_host(self) -> None:
        assert _base_url("MYAPPID") == "https://MYAPPID.algolia.net"

    @pytest.mark.parametrize("bad", ["evil.com/", "app id", "app.algolia.net", "a/b", "app#x", ""])
    def test_rejects_non_alphanumeric_application_id(self, bad: str) -> None:
        # The application_id is interpolated into the request host, so anything that could
        # break out of *.algolia.net must be rejected before a request is made.
        with pytest.raises(InvalidApplicationIdError):
            _base_url(bad)


class TestEndpointUrl:
    def test_formats_index_into_path(self) -> None:
        url = _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], "my_index")
        assert url == "https://APP.algolia.net/1/indexes/my_index/browse"

    def test_quotes_index_name(self) -> None:
        url = _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], "my index/slash")
        assert url == "https://APP.algolia.net/1/indexes/my%20index%2Fslash/browse"

    def test_index_scoped_endpoint_requires_index(self) -> None:
        with pytest.raises(ValueError):
            _endpoint_url("APP", ALGOLIA_ENDPOINTS["records"], None)

    def test_app_level_endpoint_ignores_index(self) -> None:
        assert _endpoint_url("APP", ALGOLIA_ENDPOINTS["indices"], None) == "https://APP.algolia.net/1/indexes"


class _Driver:
    """Drives get_rows against a fake tracked session, capturing every request."""

    def __init__(self, responses: list[MagicMock]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def _request(self, method: str, url: str, **kwargs: Any) -> MagicMock:
        self.calls.append({"method": method, "url": url, "json": kwargs.get("json"), "params": kwargs.get("params")})
        return next(self.responses)

    def run(self, endpoint: str, manager: MagicMock) -> list[dict[str, Any]]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
        ) as mock_session_factory:
            session = mock_session_factory.return_value
            session.request.side_effect = self._request
            tables = list(
                get_rows(
                    endpoint=endpoint,
                    application_id="APP",
                    api_key="key",
                    index_name="idx",
                    logger=MagicMock(),
                    manager=manager,
                )
            )
            return _rows(tables)


def _fresh_manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestCursorPagination:
    def test_pages_until_cursor_absent(self) -> None:
        manager = _fresh_manager()
        driver = _Driver(
            [
                _response({"hits": [{"objectID": "1"}], "cursor": "c1"}),
                _response({"hits": [{"objectID": "2"}]}),
            ]
        )

        rows = driver.run("records", manager)

        assert [r["objectID"] for r in rows] == ["1", "2"]
        # First browse request carries no cursor; the second carries the cursor returned first.
        assert driver.calls[0]["json"] == {"hitsPerPage": 1000}
        assert driver.calls[1]["json"] == {"hitsPerPage": 1000, "cursor": "c1"}

    def test_saves_cursor_after_non_terminal_page(self) -> None:
        manager = _fresh_manager()
        driver = _Driver(
            [
                _response({"hits": [{"objectID": "1"}], "cursor": "c1"}),
                _response({"hits": [{"objectID": "2"}]}),
            ]
        )

        driver.run("records", manager)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AlgoliaResumeConfig(cursor="c1")]

    def test_single_terminal_page_saves_nothing(self) -> None:
        manager = _fresh_manager()
        driver = _Driver([_response({"hits": [{"objectID": "only"}]})])

        rows = driver.run("records", manager)

        assert [r["objectID"] for r in rows] == ["only"]
        manager.save_state.assert_not_called()

    def test_resume_seeds_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AlgoliaResumeConfig(cursor="resumed")
        driver = _Driver([_response({"hits": [{"objectID": "x"}]})])

        driver.run("records", manager)

        assert driver.calls[0]["json"] == {"hitsPerPage": 1000, "cursor": "resumed"}


class TestPagePagination:
    def test_search_endpoint_stops_on_short_page(self) -> None:
        manager = _fresh_manager()
        # Fewer rows than the requested page size signals the last page for search endpoints.
        driver = _Driver([_response({"hits": [{"objectID": "s1"}], "nbHits": 1})])

        rows = driver.run("synonyms", manager)

        assert [r["objectID"] for r in rows] == ["s1"]
        assert len(driver.calls) == 1
        manager.save_state.assert_not_called()

    def test_search_endpoint_walks_multiple_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager = _fresh_manager()
        monkeypatch.setattr(ALGOLIA_ENDPOINTS["synonyms"], "page_size", 2)
        driver = _Driver(
            [
                _response({"hits": [{"objectID": "a"}, {"objectID": "b"}], "nbHits": 3}),
                _response({"hits": [{"objectID": "c"}], "nbHits": 3}),
            ]
        )

        rows = driver.run("synonyms", manager)

        assert [r["objectID"] for r in rows] == ["a", "b", "c"]
        assert [c["json"]["page"] for c in driver.calls] == [0, 1]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AlgoliaResumeConfig(page=1)]

    def test_indices_uses_nb_pages_to_terminate(self) -> None:
        manager = _fresh_manager()
        driver = _Driver(
            [
                _response({"items": [{"name": "i1"}], "nbPages": 2}),
                _response({"items": [{"name": "i2"}], "nbPages": 2}),
            ]
        )

        rows = driver.run("indices", manager)

        assert [r["name"] for r in rows] == ["i1", "i2"]
        # GET endpoints page via query params, and must request the configured page size so the
        # listing doesn't fall back to Algolia's small server-side default.
        assert [c["params"]["page"] for c in driver.calls] == [0, 1]
        assert all(c["params"]["hitsPerPage"] == ALGOLIA_ENDPOINTS["indices"].page_size for c in driver.calls)

    def test_resume_seeds_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AlgoliaResumeConfig(page=3)
        driver = _Driver([_response({"items": [{"name": "i"}], "nbPages": 4})])

        driver.run("indices", manager)

        assert driver.calls[0]["params"]["page"] == 3


class TestAlgoliaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ALGOLIA_ENDPOINTS.keys()))
    def test_primary_keys_match_settings(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = algolia_source(
            endpoint=endpoint,
            application_id="APP",
            api_key="key",
            index_name="idx",
            logger=MagicMock(),
            manager=manager,
        )
        assert response.name == endpoint
        assert response.primary_keys == ALGOLIA_ENDPOINTS[endpoint].primary_keys

    def test_items_is_lazy(self) -> None:
        # Building the SourceResponse must not issue any request; only iterating items should.
        manager = MagicMock(spec=ResumableSourceManager)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
        ) as factory:
            algolia_source(
                endpoint="records",
                application_id="APP",
                api_key="key",
                index_name="idx",
                logger=MagicMock(),
                manager=manager,
            )
            factory.assert_not_called()


class TestValidateCredentials:
    def _run(self, response: MagicMock, **kwargs: Any) -> tuple[bool, str | None]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
        ) as factory:
            session = factory.return_value
            session.get.return_value = response
            session.post.return_value = response
            return validate_credentials(application_id="APP", api_key="key", **kwargs)

    def test_ok(self) -> None:
        valid, error = self._run(_response({}, status_code=200), index_name="idx")
        assert valid is True
        assert error is None

    def test_invalid_credentials(self) -> None:
        resp = _response({"message": "Invalid Application-ID or API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx")
        assert valid is False
        assert error is not None and "Invalid Algolia Application ID or API key" in error

    def test_missing_acl_accepted_at_source_create(self) -> None:
        # A genuine key lacking the ACL for the probe returns a different 403; at source
        # create (no schema_name) we accept it.
        resp = _response({"message": "Method not allowed with this API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx")
        assert valid is True
        assert error is None

    def test_missing_acl_rejected_for_specific_schema(self) -> None:
        resp = _response({"message": "Method not allowed with this API key", "status": 403}, status_code=403)
        valid, error = self._run(resp, index_name="idx", schema_name="synonyms")
        assert valid is False
        assert error is not None

    def test_invalid_application_id_rejected_before_request(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
        ) as factory:
            valid, error = validate_credentials(application_id="evil.com/", api_key="key", index_name="idx")
        assert valid is False
        assert error is not None
        factory.return_value.get.assert_not_called()
        factory.return_value.post.assert_not_called()

    def test_network_error_returns_message(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.algolia.algolia.make_tracked_session"
        ) as factory:
            factory.return_value.get.side_effect = requests.ConnectionError("boom")
            valid, error = validate_credentials(application_id="APP", api_key="key")
        assert valid is False
        assert error is not None and "boom" in error

    def test_unexpected_status_returns_message(self) -> None:
        valid, error = self._run(_response({}, status_code=500), index_name="idx")
        assert valid is False
        assert error is not None and "500" in error
