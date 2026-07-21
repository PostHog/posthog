import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.settings import WEBFLOW_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow import (
    WebflowResumeConfig,
    _extract_items,
    _resolve_collection_id,
    validate_credentials,
    webflow_source,
)

# The sync transport builds its session via make_tracked_session inside the shared rest_client.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials / list_collections build their own tracked session in the webflow module.
WEBFLOW_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow.make_tracked_session"
)


def _make_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _make_manager(resume_state: WebflowResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; return (urls, params) snapshotted AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy
    when each request is prepared rather than reading the final state after the run.
    """
    session.headers = {}
    urls: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        urls.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return urls, param_snapshots


def _drive(
    manager: MagicMock, responses: list[Response], schema_name: str = "pages"
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    with patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        urls, params = _wire(session, responses)
        response = webflow_source(
            api_token="token",
            site_id="site-1",
            schema_name=schema_name,
            team_id=1,
            job_id="j",
            resumable_source_manager=manager,
        )
        rows = [row for page in cast("Iterable[Any]", response.items()) for row in page]
    return rows, urls, params


class TestExtractItems:
    @parameterized.expand(
        [
            ("configured_key", {"items": [{"id": 1}]}, "items", [{"id": 1}]),
            ("named_envelope", {"sites": [{"id": 1}]}, "sites", [{"id": 1}]),
            ("bare_list", [{"id": 1}], "items", [{"id": 1}]),
            ("missing_key_fallback", {"weird": [{"id": 7}], "pagination": {}}, "items", [{"id": 7}]),
            ("pagination_skipped", {"pagination": [1, 2], "orders": [{"id": 9}]}, "orders", [{"id": 9}]),
            ("nothing", {"pagination": {}}, "items", []),
            ("not_a_dict", 5, "items", []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: str, expected: list[dict[str, Any]]) -> None:
        assert _extract_items(data, data_key) == expected


class TestGetRows:
    def test_fresh_run_paginates_until_total_and_saves_after_each_page(self) -> None:
        manager = _make_manager()
        # Full pages until the grand total (pagination.total) is reached; offset advances by page size.
        page1 = [{"id": f"a{i}"} for i in range(100)]
        page2 = [{"id": f"b{i}"} for i in range(100)]
        page3 = [{"id": f"c{i}"} for i in range(50)]
        responses = [
            _make_response({"pages": page1, "pagination": {"total": 250, "offset": 0}}),
            _make_response({"pages": page2, "pagination": {"total": 250, "offset": 100}}),
            _make_response({"pages": page3, "pagination": {"total": 250, "offset": 200}}),
        ]
        rows, _urls, params = _drive(manager, responses)

        assert len(rows) == 250
        assert [p["offset"] for p in params] == [0, 100, 200]
        assert [p["limit"] for p in params] == [100, 100, 100]
        # A checkpoint (pointing at the next page) is saved after each non-terminal page; the
        # final page terminates via total and saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WebflowResumeConfig(offset=100), WebflowResumeConfig(offset=200)]

    def test_resume_starts_from_saved_offset(self) -> None:
        manager = _make_manager(WebflowResumeConfig(offset=200))
        responses = [_make_response({"pages": [{"id": "c"}], "pagination": {"total": 250, "offset": 200}})]

        rows, _urls, params = _drive(manager, responses)

        assert rows == [{"id": "c"}]
        assert params[0]["offset"] == 200
        manager.load_state.assert_called_once()

    def test_terminates_on_short_page(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "only"}]})]

        rows, _urls, _params = _drive(manager, responses)

        assert rows == [{"id": "only"}]
        manager.save_state.assert_not_called()

    def test_single_object_endpoint_wraps_one_row_and_fetches_once(self) -> None:
        manager = _make_manager()
        # /sites/{site_id} returns a single site object, not a list envelope.
        responses = [_make_response({"id": "s1", "displayName": "My site"})]

        rows, urls, params = _drive(manager, responses, schema_name="sites")

        assert rows == [{"id": "s1", "displayName": "My site"}]
        assert urls == ["https://api.webflow.com/v2/sites/site-1"]
        # Not paginated: no offset/limit params are injected.
        assert "offset" not in params[0]
        manager.save_state.assert_not_called()

    def test_products_endpoint_flattens_nested_product(self) -> None:
        manager = _make_manager()
        responses = [
            _make_response(
                {
                    "items": [
                        {"product": {"id": "p1", "createdOn": "2026-01-01"}, "skus": [{"id": "s1"}]},
                    ]
                }
            )
        ]

        rows, _urls, _params = _drive(manager, responses, schema_name="products")

        assert rows == [{"id": "p1", "createdOn": "2026-01-01", "skus": [{"id": "s1"}]}]

    def test_collection_items_request_includes_stable_sort(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"items": [{"id": "i1"}]})]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
            return_value="col-99",
        ):
            rows, urls, params = _drive(manager, responses, schema_name="collection_blog")

        assert rows == [{"id": "i1"}]
        assert urls[0] == "https://api.webflow.com/v2/collections/col-99/items"
        assert params[0]["sortBy"] == "createdOn"
        assert params[0]["sortOrder"] == "asc"

    def test_site_id_with_path_delimiters_is_encoded_into_a_single_segment(self) -> None:
        # A site_id containing path/query delimiters must not redirect the request to an
        # account-level (or otherwise unintended) Webflow endpoint.
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "a"}]})]
        with patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            urls, _params = _wire(session, responses)
            response = webflow_source(
                api_token="token",
                site_id="../../sites",
                schema_name="pages",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
            list(cast("Iterable[Any]", response.items()))

        assert urls[0] == "https://api.webflow.com/v2/sites/..%2F..%2Fsites/pages"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()
        responses = [_make_response({"pages": [{"id": "a"}]})]

        _drive(manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_token", 401, None, False),
            ("missing_scope_at_create", 403, None, True),
            ("missing_scope_for_schema", 403, "products", False),
            ("invalid_site_id", 400, None, False),
            ("site_not_found", 404, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"message": "nope"}, status_code=status_code)
            ok, _error = validate_credentials("token", "site-1", schema_name)
        assert ok is expected_ok

    def test_invalid_site_id_400_does_not_leak_raw_envelope(self) -> None:
        # A malformed Site ID gets a 400 with Webflow's raw "Validation Error: ..." envelope, which
        # must not surface to the user.
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"message": "Validation Error: Provided IDs are invalid: Site ID"}, status_code=400
            )
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert "Site ID isn't valid" in (error or "")
        assert "Validation Error" not in (error or "")

    def test_request_exception_returns_error(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
            ok, error = validate_credentials("token", "site-1")
        assert ok is False
        assert error == "boom"


class TestResolveCollectionId:
    def test_resolves_by_slug(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response(
                {"collections": [{"id": "c1", "slug": "blog"}, {"id": "c2", "slug": "authors"}]}
            )
            assert _resolve_collection_id("token", "site-1", "collection_authors") == "c2"

    def test_raises_when_collection_missing(self) -> None:
        with patch(WEBFLOW_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({"collections": [{"id": "c1", "slug": "blog"}]})
            with pytest.raises(ValueError):
                _resolve_collection_id("token", "site-1", "collection_missing")


class TestWebflowSource:
    @parameterized.expand(
        [
            ("pages", "pages", ["id"]),
            ("orders", "orders", ["orderId"]),
            ("products", "products", ["id"]),
        ]
    )
    def test_source_response_primary_keys(self, _name: str, schema_name: str, expected_pks: list[str]) -> None:
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH):
            response = webflow_source(
                "token", "site-1", schema_name, team_id=1, job_id="j", resumable_source_manager=manager
            )
        assert response.name == schema_name
        assert response.primary_keys == expected_pks
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [WEBFLOW_ENDPOINTS[schema_name].partition_key]

    def test_forms_endpoint_has_no_partitioning(self) -> None:
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH):
            response = webflow_source(
                "token", "site-1", "forms", team_id=1, job_id="j", resumable_source_manager=manager
            )
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_collection_schema_resolves_collection_id(self) -> None:
        manager = _make_manager()
        with (
            patch(CLIENT_SESSION_PATCH),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.webflow.webflow._resolve_collection_id",
                return_value="c1",
            ) as mock_resolve,
        ):
            response = webflow_source(
                "token", "site-1", "collection_blog", team_id=1, job_id="j", resumable_source_manager=manager
            )
        mock_resolve.assert_called_once_with("token", "site-1", "collection_blog")
        assert response.name == "collection_blog"
        assert response.primary_keys == ["id"]

    def test_items_callable_lazy(self) -> None:
        # Building the SourceResponse must not send any request; only iterating items() should.
        manager = _make_manager()
        with patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.send.side_effect = AssertionError("no request should be sent while building the SourceResponse")
            response = webflow_source(
                "token", "site-1", "pages", team_id=1, job_id="j", resumable_source_manager=manager
            )
            assert callable(response.items)
            assert isinstance(response.items(), Iterable)
