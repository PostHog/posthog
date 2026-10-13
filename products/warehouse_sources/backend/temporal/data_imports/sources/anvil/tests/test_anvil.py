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
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.settings import ANVIL_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.anvil.source import AnvilSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anvil import AnvilSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(AnvilSource(), AnvilSourceConfig(api_key="key"))


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


def _org_eids(*eids: str) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"currentUser": {"organizations": [{"eid": eid} for eid in eids]}}})


def _org_page(page_field: str, items: list[dict[str, Any]], page: int = 1, page_count: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": {"organization": {page_field: {"page": page, "pageCount": page_count, "items": items}}}}
    )


def _weld_datas_page(items: list[dict[str, Any]], page: int = 1, page_count: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": {"weld": {"weldDatas": {"page": page, "pageCount": page_count, "items": items}}}}
    )


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
    def test_valid_key_authenticates_with_basic_auth(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": {"currentUser": {"eid": "u1"}}})]) as network:
            assert validate_credentials("key-1") == (True, None)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["authorization"] == "Basic a2V5LTE6"

    def test_rejected_key_returns_message(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={})]):
            is_valid, error = validate_credentials("bad-key")

        assert is_valid is False
        assert error == "Anvil rejected the API key"

    def test_graphql_error_returns_its_message(self) -> None:
        # Anvil responds HTTP 200 with an errors body when no auth header is readable.
        with scripted_network([ScriptedResponse(json={"errors": [{"message": "Must be authenticated"}]})]):
            is_valid, error = validate_credentials("key-1")

        assert is_valid is False
        assert error is not None and "Must be authenticated" in error

    def test_network_failure_returns_unreachable(self) -> None:
        with scripted_network([ConnectionResetError("boom")]):
            assert validate_credentials("key-1") == (False, "Could not reach the Anvil API")


class TestOrganizations:
    def test_single_query_yields_every_organization(self) -> None:
        result = _driver().run("organizations", [_org_eids("o1", "o2")])

        assert result.raised is None
        assert [row["eid"] for row in result.rows] == ["o1", "o2"]
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestOrganizationPagedEndpoints:
    def test_resumes_from_bookmarked_organization_and_offset(self) -> None:
        result = _driver().run(
            "casts",
            [_org_eids("o1", "o2"), _org_page("casts", [{"eid": "c9"}], page=3, page_count=3)],
            resume_state=AnvilResumeConfig(next_offset=3, parent_eid="o2"),
        )

        assert result.raised is None
        assert len(result.requests) == 2
        variables = result.requests[1].json()["variables"]
        assert variables["organizationEid"] == "o2"
        assert variables["offset"] == 3

    def test_deleted_organization_is_skipped(self) -> None:
        result = _driver().run(
            "casts",
            [
                _org_eids("o1", "o2"),
                ScriptedResponse(json={"data": {"organization": None}}),
                _org_page("casts", [{"eid": "c1"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"eid": "c1", "organizationEid": "o2"}]

    def test_non_advancing_page_raises_instead_of_looping(self) -> None:
        result = _driver().run(
            "casts",
            [
                _org_eids("o1"),
                _org_page("casts", [{"eid": "c1"}], page=1, page_count=2),
                _org_page("casts", [{"eid": "c1"}], page=1, page_count=2),
            ],
        )

        assert isinstance(result.raised, AnvilAPIError)
        assert "did not advance" in str(result.raised)


class TestWeldDatasFanOut:
    def test_fans_out_over_welds_across_organizations(self) -> None:
        result = _driver().run(
            "weld_datas",
            [
                _org_eids("o1", "o2"),
                _org_page("welds", [{"eid": "w1"}]),
                _org_page("welds", [{"eid": "w2"}]),
                _weld_datas_page([{"eid": "d1"}], page=1, page_count=2),
                _weld_datas_page([{"eid": "d2"}], page=2, page_count=2),
                _weld_datas_page([{"eid": "d3"}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"eid": "d1", "weldEid": "w1"},
            {"eid": "d2", "weldEid": "w1"},
            {"eid": "d3", "weldEid": "w2"},
        ]
        assert [request.json()["variables"]["weldEid"] for request in result.requests[3:]] == ["w1", "w1", "w2"]
        assert [(state.next_offset, state.parent_eid) for state in result.saved_states] == [(2, "w1"), (None, "w2")]


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
    def test_partition_wiring_per_endpoint(self, endpoint: str) -> None:
        config = ANVIL_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_org_eids()])

        assert result.raised is None
        response = result.response
        assert response is not None
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
