from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree import (
    PAGE_SIZE,
    BraintreeGraphQLError,
    BraintreeResumeConfig,
    _base_url,
    _build_query,
    _format_created_at,
    braintree_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.settings import (
    BRAINTREE_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree"


def _make_manager(resume_state: BraintreeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _search_response(search_field: str, edges: list[dict[str, Any]], has_next: bool = False) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {
        "data": {"search": {search_field: {"pageInfo": {"hasNextPage": has_next}, "edges": edges}}}
    }
    resp.status_code = 200
    resp.ok = True
    return resp


def _edge(node_id: str) -> dict[str, Any]:
    return {"cursor": f"cur-{node_id}", "node": {"id": node_id, "createdAt": "2024-01-01T00:00:00Z"}}


class TestBaseUrl:
    def test_production_and_sandbox_hosts(self):
        assert _base_url("production") == "https://payments.braintree-api.com/graphql"
        assert _base_url("sandbox") == "https://payments.sandbox.braintree-api.com/graphql"

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestBuildQuery:
    @pytest.mark.parametrize(
        "endpoint, input_type",
        [
            ("transactions", "TransactionSearchInput"),
            ("refunds", "RefundSearchInput"),
            ("disputes", "DisputeSearchInput"),
        ],
    )
    def test_query_uses_correct_input_type(self, endpoint, input_type):
        query = _build_query(BRAINTREE_ENDPOINTS[endpoint])
        assert f"$input: {input_type}" in query
        assert BRAINTREE_ENDPOINTS[endpoint].search_field in query


class TestFormatCreatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_created_at(value) == expected


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_on_pong(self, mock_session):
        resp = mock.MagicMock()
        resp.json.return_value = {"data": {"ping": "pong"}}
        resp.status_code = 200
        resp.ok = True
        mock_session.return_value.post.return_value = resp

        assert validate_credentials("production", "pub", "priv") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_graphql_error(self, mock_session):
        resp = mock.MagicMock()
        resp.json.return_value = {"errors": [{"message": "Invalid API key"}]}
        resp.status_code = 200
        resp.ok = True
        mock_session.return_value.post.return_value = resp

        assert validate_credentials("production", "pub", "priv") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("production", "pub", "priv") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_relay_cursors(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _search_response("transactions", [_edge("t1"), _edge("t2")], has_next=True),
            _search_response("transactions", [_edge("t3")], has_next=False),
        ]

        manager = _make_manager()
        batches = list(get_rows("production", "pub", "priv", "transactions", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["t1", "t2", "t3"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].after == "cur-t2"
        second_vars = mock_session.return_value.post.call_args_list[1].kwargs["json"]["variables"]
        assert second_vars["after"] == "cur-t2"
        assert second_vars["first"] == PAGE_SIZE

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_search_input_has_gte_filter(self, mock_session):
        mock_session.return_value.post.return_value = _search_response("transactions", [])

        manager = _make_manager()
        list(
            get_rows(
                "production",
                "pub",
                "priv",
                "transactions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert variables["input"] == {"createdAt": {"greaterThanOrEqualTo": "2024-01-02T00:00:00Z"}}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_scan_has_null_input(self, mock_session):
        mock_session.return_value.post.return_value = _search_response("transactions", [])

        manager = _make_manager()
        list(get_rows("production", "pub", "priv", "transactions", mock.MagicMock(), manager))

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert variables["input"] is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.post.return_value = _search_response("transactions", [])

        manager = _make_manager(BraintreeResumeConfig(after="cur-resume"))
        list(get_rows("production", "pub", "priv", "transactions", mock.MagicMock(), manager))

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert variables["after"] == "cur-resume"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_graphql_error_raises(self, mock_session):
        resp = mock.MagicMock()
        resp.json.return_value = {"errors": [{"message": "validation error"}]}
        resp.status_code = 200
        resp.ok = True
        mock_session.return_value.post.return_value = resp

        manager = _make_manager()
        with pytest.raises(BraintreeGraphQLError):
            list(get_rows("production", "pub", "priv", "transactions", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_uses_basic_auth_and_version_header(self, mock_session):
        mock_session.return_value.post.return_value = _search_response("transactions", [])

        manager = _make_manager()
        list(get_rows("production", "pub", "priv", "transactions", mock.MagicMock(), manager))

        assert mock_session.return_value.auth == ("pub", "priv")
        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Braintree-Version"]


class TestBraintreeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BRAINTREE_ENDPOINTS[endpoint]
        response = braintree_source("production", "pub", "priv", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Search ordering is undocumented — watermark commits only at run end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
