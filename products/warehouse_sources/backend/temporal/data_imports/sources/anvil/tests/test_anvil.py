from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.anvil import (
    AnvilAPIError,
    AnvilResumeConfig,
    _build_organization_page_query,
    _build_weld_datas_query,
    _execute,
    anvil_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.settings import (
    ANVIL_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.anvil.anvil"


def _make_manager(resume_state: AnvilResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = payload
    resp.status_code = status_code
    resp.ok = status_code < 400
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: Unauthorized for url: https://graphql.useanvil.com",
            response=resp,
        )
    return resp


def _org_eids(*eids: str) -> mock.MagicMock:
    return _response({"data": {"currentUser": {"organizations": [{"eid": eid} for eid in eids]}}})


def _org_page(page_field: str, items: list[dict[str, Any]], page: int = 1, page_count: int = 1) -> mock.MagicMock:
    return _response({"data": {"organization": {page_field: {"page": page, "pageCount": page_count, "items": items}}}})


def _weld_datas_page(items: list[dict[str, Any]], page: int = 1, page_count: int = 1) -> mock.MagicMock:
    return _response({"data": {"weld": {"weldDatas": {"page": page, "pageCount": page_count, "items": items}}}})


def _mock_session(mock_make_session: mock.MagicMock, responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.post.side_effect = responses
    mock_make_session.return_value = session
    return session


class TestExecute:
    def test_graphql_errors_raise_with_joined_messages(self):
        session = mock.MagicMock()
        session.post.return_value = _response(
            {"errors": [{"message": "Must be authenticated"}, {"message": "Weld not found"}], "data": None}
        )

        with pytest.raises(AnvilAPIError) as exc_info:
            _execute(session, "query {}", {}, mock.MagicMock())

        assert "Must be authenticated" in str(exc_info.value)
        assert "Weld not found" in str(exc_info.value)

    def test_http_error_raises_after_logging(self):
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=401)

        with pytest.raises(requests.HTTPError) as exc_info:
            _execute(session, "query {}", {}, mock.MagicMock())

        assert "401" in str(exc_info.value)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_key_authenticates_with_basic_auth(self, mock_make_session):
        session = _mock_session(mock_make_session, [_response({"data": {"currentUser": {"eid": "u1"}}})])

        assert validate_credentials("key-1") == (True, None)
        assert session.auth == ("key-1", "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejected_key_returns_message(self, mock_make_session):
        _mock_session(mock_make_session, [_response({}, status_code=401)])

        is_valid, error = validate_credentials("bad-key")
        assert is_valid is False
        assert error == "Anvil rejected the API key"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_graphql_error_returns_its_message(self, mock_make_session):
        # Anvil responds HTTP 200 with an errors body when no auth header is readable.
        _mock_session(mock_make_session, [_response({"errors": [{"message": "Must be authenticated"}]})])

        is_valid, error = validate_credentials("key-1")
        assert is_valid is False
        assert error is not None and "Must be authenticated" in error

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_failure_returns_unreachable(self, mock_make_session):
        mock_make_session.return_value.post.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("key-1") == (False, "Could not reach the Anvil API")


class TestOrganizations:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_query_yields_every_organization(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [_response({"data": {"currentUser": {"organizations": [{"eid": "o1"}, {"eid": "o2"}]}}})],
        )

        manager = _make_manager()
        batches = list(get_rows("key", "organizations", mock.MagicMock(), manager))

        assert [row["eid"] for batch in batches for row in batch] == ["o1", "o2"]
        assert session.post.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_no_organizations_yields_no_batches(self, mock_make_session):
        _mock_session(mock_make_session, [_response({"data": {"currentUser": {"organizations": []}}})])

        assert list(get_rows("key", "organizations", mock.MagicMock(), _make_manager())) == []


class TestOrganizationPagedEndpoints:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_by_page_number_and_tags_rows(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [
                _org_eids("o1", "o2"),
                _org_page("casts", [{"eid": "c1"}], page=1, page_count=2),
                _org_page("casts", [{"eid": "c2"}], page=2, page_count=2),
                _org_page("casts", [{"eid": "c3"}]),
            ],
        )

        manager = _make_manager()
        batches = list(get_rows("key", "casts", mock.MagicMock(), manager))

        assert [row for batch in batches for row in batch] == [
            {"eid": "c1", "organizationEid": "o1"},
            {"eid": "c2", "organizationEid": "o1"},
            {"eid": "c3", "organizationEid": "o2"},
        ]
        page_calls = [call.kwargs["json"]["variables"] for call in session.post.call_args_list[1:]]
        # The first request per organization omits `offset` so the server's own first-page
        # number seeds the walk; the follow-up asks for the returned page + 1.
        assert "offset" not in page_calls[0]
        assert page_calls[0]["limit"] == PAGE_SIZE
        assert page_calls[1]["offset"] == 2
        assert [call["organizationEid"] for call in page_calls] == ["o1", "o1", "o2"]
        # Mid-organization page checkpoint, then a bookmark advancing to the next organization.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [(state.next_offset, state.parent_eid) for state in saved] == [(2, "o1"), (None, "o2")]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_bookmarked_organization_and_offset(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [
                _org_eids("o1", "o2"),
                _org_page("casts", [{"eid": "c9"}], page=3, page_count=3),
            ],
        )

        manager = _make_manager(AnvilResumeConfig(next_offset=3, parent_eid="o2"))
        list(get_rows("key", "casts", mock.MagicMock(), manager))

        page_calls = session.post.call_args_list[1:]
        assert len(page_calls) == 1
        variables = page_calls[0].kwargs["json"]["variables"]
        assert variables["organizationEid"] == "o2"
        assert variables["offset"] == 3

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_deleted_organization_is_skipped(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [
                _org_eids("o1", "o2"),
                _response({"data": {"organization": None}}),
                _org_page("casts", [{"eid": "c1"}]),
            ],
        )

        batches = list(get_rows("key", "casts", mock.MagicMock(), _make_manager()))

        assert [row for batch in batches for row in batch] == [{"eid": "c1", "organizationEid": "o2"}]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_advancing_page_raises_instead_of_looping(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [
                _org_eids("o1"),
                _org_page("casts", [{"eid": "c1"}], page=1, page_count=2),
                _org_page("casts", [{"eid": "c1"}], page=1, page_count=2),
            ],
        )

        with pytest.raises(AnvilAPIError) as exc_info:
            list(get_rows("key", "casts", mock.MagicMock(), _make_manager()))

        assert "did not advance" in str(exc_info.value)


class TestWeldDatasFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fans_out_over_welds_across_organizations(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [
                _org_eids("o1", "o2"),
                _org_page("welds", [{"eid": "w1"}]),
                _org_page("welds", [{"eid": "w2"}]),
                _weld_datas_page([{"eid": "d1"}], page=1, page_count=2),
                _weld_datas_page([{"eid": "d2"}], page=2, page_count=2),
                _weld_datas_page([{"eid": "d3"}]),
            ],
        )

        manager = _make_manager()
        batches = list(get_rows("key", "weld_datas", mock.MagicMock(), manager))

        assert [row for batch in batches for row in batch] == [
            {"eid": "d1", "weldEid": "w1"},
            {"eid": "d2", "weldEid": "w1"},
            {"eid": "d3", "weldEid": "w2"},
        ]
        weld_data_calls = [call.kwargs["json"]["variables"] for call in session.post.call_args_list[3:]]
        assert [call["weldEid"] for call in weld_data_calls] == ["w1", "w1", "w2"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert [(state.next_offset, state.parent_eid) for state in saved] == [(2, "w1"), (None, "w2")]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_deleted_weld_is_skipped(self, mock_make_session):
        _mock_session(
            mock_make_session,
            [
                _org_eids("o1"),
                _org_page("welds", [{"eid": "w1"}, {"eid": "w2"}]),
                _response({"data": {"weld": None}}),
                _weld_datas_page([{"eid": "d1"}]),
            ],
        )

        batches = list(get_rows("key", "weld_datas", mock.MagicMock(), _make_manager()))

        assert [row for batch in batches for row in batch] == [{"eid": "d1", "weldEid": "w2"}]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_bookmarked_weld(self, mock_make_session):
        session = _mock_session(
            mock_make_session,
            [
                _org_eids("o1"),
                _org_page("welds", [{"eid": "w1"}, {"eid": "w2"}]),
                _weld_datas_page([{"eid": "d9"}]),
            ],
        )

        manager = _make_manager(AnvilResumeConfig(next_offset=2, parent_eid="w2"))
        list(get_rows("key", "weld_datas", mock.MagicMock(), manager))

        weld_data_calls = session.post.call_args_list[2:]
        assert len(weld_data_calls) == 1
        variables = weld_data_calls[0].kwargs["json"]["variables"]
        assert variables["weldEid"] == "w2"
        assert variables["offset"] == 2


class TestQueryDocuments:
    @pytest.mark.parametrize(
        "endpoint",
        [name for name in ENDPOINTS if ANVIL_ENDPOINTS[name].organization_page_field],
    )
    def test_organization_page_query_declares_its_variables(self, endpoint):
        config = ANVIL_ENDPOINTS[endpoint]
        assert config.organization_page_field is not None
        query = _build_organization_page_query(config.organization_page_field, config.item_fields)

        for declaration in ("$organizationEid: String!", "$limit: Int", "$offset: Int"):
            assert declaration in query
        assert f"{config.organization_page_field}(limit: $limit, offset: $offset)" in query

    def test_weld_datas_query_declares_its_variables(self):
        query = _build_weld_datas_query(ANVIL_ENDPOINTS["weld_datas"].item_fields)

        for declaration in ("$weldEid: String!", "$limit: Int", "$offset: Int"):
            assert declaration in query
        assert "weld(eid: $weldEid)" in query


class TestAnvilSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_wiring_per_endpoint(self, endpoint):
        config = ANVIL_ENDPOINTS[endpoint]
        response = anvil_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # List ordering is undocumented, so the watermark commits only at run end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
