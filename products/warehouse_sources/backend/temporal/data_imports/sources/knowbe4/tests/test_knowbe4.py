from typing import Any, cast

import pytest

from parameterized import parameterized
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.knowbe4 import (
    Knowbe4SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.knowbe4 import (
    build_base_url,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.settings import KNOWBE4_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.knowbe4.source import Knowbe4Source


class TestKnowBe4Transport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(Knowbe4Source(), Knowbe4SourceConfig(api_key="tok", region="us"))

    @parameterized.expand(
        [
            ("us", "us", "https://us.api.knowbe4.com"),
            ("eu", "eu", "https://eu.api.knowbe4.com"),
            ("ca", "ca", "https://ca.api.knowbe4.com"),
            ("uk", "uk", "https://uk.api.knowbe4.com"),
            ("de", "de", "https://de.api.knowbe4.com"),
            ("case_insensitive", "US", "https://us.api.knowbe4.com"),
            ("whitespace_trimmed", "  us  ", "https://us.api.knowbe4.com"),
        ]
    )
    def test_build_base_url(self, _name: str, region: str, expected: str) -> None:
        assert build_base_url(region) == expected

    def test_build_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            build_base_url("apac")

    @parameterized.expand(
        [
            ("unauthorized", 401, None, False),
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "users", False),
            ("ok", 200, None, True),
            ("unexpected", 500, None, False),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, schema_name: str | None, expected_ok: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, _message = validate_credentials(api_key="tok", region="us", schema_name=schema_name)

        assert is_valid is expected_ok
        assert {request.path for request in network.requests_log} == {"/v1/account"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer tok"}
        assert network.session_options[0]["redact_values"] == ("tok",)

    def test_validate_credentials_rejects_bad_region_before_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials(api_key="tok", region="apac")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_validate_credentials_handles_request_exception(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials(api_key="tok", region="us")

        assert is_valid is False
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/v1/account"}

    def test_get_resource_account_is_single_unpaginated_request(self) -> None:
        # `/v1/account` returns one object; a page paginator would refetch it forever because
        # the response never becomes an empty array.
        resource = cast(dict[str, Any], get_resource(KNOWBE4_ENDPOINTS["account"]))
        assert resource["endpoint"]["params"] == {}
        assert isinstance(resource["endpoint"]["paginator"], SinglePagePaginator)

    def test_get_resource_account_risk_score_history_requests_full_history(self) -> None:
        # Without full=true KnowBe4 returns only the last six months.
        resource = cast(dict[str, Any], get_resource(KNOWBE4_ENDPOINTS["account_risk_score_history"]))
        assert resource["endpoint"]["params"] == {"per_page": 500, "full": "true"}
        assert isinstance(resource["endpoint"]["paginator"], PageNumberPaginator)

    def test_knowbe4_source_users_top_level(self) -> None:
        result = self._driver().run("users", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "users"
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == "asc"

    @parameterized.expand(
        [
            (
                "group_members",
                "groups",
                {"id": "user_1", "email": "a@b.com", "_groups_id": "grp_1"},
                {"id": "user_1", "email": "a@b.com", "group_id": "grp_1"},
                ["group_id", "id"],
            ),
            (
                "group_risk_score_history",
                "groups",
                {"risk_score": 37.3, "date": "2021-02-07", "_groups_id": "grp_1"},
                {"risk_score": 37.3, "date": "2021-02-07", "group_id": "grp_1"},
                ["group_id", "date"],
            ),
            (
                "user_risk_score_history",
                "users",
                {"risk_score": 37.3, "date": "2021-02-07", "_users_id": "user_1"},
                {"risk_score": 37.3, "date": "2021-02-07", "user_id": "user_1"},
                ["user_id", "date"],
            ),
        ]
    )
    def test_knowbe4_source_fanout_injects_and_renames_parent_id(
        self,
        endpoint: str,
        parent_name: str,
        raw_child_row: dict[str, Any],
        expected_row: dict[str, Any],
        expected_primary_keys: list[str],
    ) -> None:
        parent_id = expected_row[expected_primary_keys[0]]
        parent_path = KNOWBE4_ENDPOINTS[parent_name].path
        child_path = KNOWBE4_ENDPOINTS[endpoint].path.format(**{expected_primary_keys[0]: parent_id})
        child_row = {key: value for key, value in raw_child_row.items() if not key.startswith("_")}
        child_responses = [ScriptedResponse(json=[child_row])]
        if KNOWBE4_ENDPOINTS[endpoint].paginated:
            child_responses.append(ScriptedResponse(json=[]))

        result = self._driver().run(
            endpoint,
            route(
                {
                    parent_path: [ScriptedResponse(json=[{"id": parent_id}]), ScriptedResponse(json=[])],
                    child_path: child_responses,
                }
            ),
        )

        # The parent id is renamed so it can't collide with a child `id`, and it anchors the key
        # because the child rows from every parent land in one table.
        assert result.raised is None
        assert result.rows == [expected_row]
        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys
        assert child_path in result.paths

    def test_knowbe4_source_fanout_uses_per_page_and_page_paginator(self) -> None:
        result = self._driver().run(
            "group_members",
            route(
                {
                    "/v1/groups": [ScriptedResponse(json=[{"id": "grp_1"}]), ScriptedResponse(json=[])],
                    "/v1/groups/grp_1/members": [ScriptedResponse(json=[{"id": "user_1"}]), ScriptedResponse(json=[])],
                }
            ),
        )

        assert result.raised is None
        assert result.params("per_page") == ["500", "500", "500", "500"]
        assert result.params("page") == ["1", "1", "2", "2"]
        assert result.rows == [{"id": "user_1", "group_id": "grp_1"}]

    @parameterized.expand(
        [
            ("group_members", 500, 500, PageNumberPaginator, {}),
            ("group_risk_score_history", 500, 500, PageNumberPaginator, {"full": "true"}),
            # Documented as unpaginated (up to 1000 records), so no per_page that could truncate it.
            ("user_risk_score_history", 500, None, SinglePagePaginator, {"full": "true"}),
        ]
    )
    def test_knowbe4_source_fanout_request_shaping(
        self,
        endpoint: str,
        expected_parent_per_page: int,
        expected_child_per_page: int | None,
        expected_child_paginator: type[BasePaginator],
        expected_child_extra_params: dict[str, str],
    ) -> None:
        config = KNOWBE4_ENDPOINTS[endpoint]
        assert config.fanout is not None
        parent_path = KNOWBE4_ENDPOINTS[config.fanout.parent_name].path
        parent_id = "grp_1" if config.fanout.parent_name == "groups" else "user_1"
        child_path = config.path.format(**{config.fanout.resolve_param: parent_id})
        child_responses = [ScriptedResponse(json=[{"date": "2021-02-07"}])]
        if expected_child_paginator is PageNumberPaginator:
            child_responses.append(ScriptedResponse(json=[]))
        result = self._driver().run(
            endpoint,
            route(
                {
                    parent_path: [ScriptedResponse(json=[{"id": parent_id}]), ScriptedResponse(json=[])],
                    child_path: child_responses,
                }
            ),
        )

        assert result.raised is None
        parent_requests = [request for request in result.requests if request.path == parent_path]
        child_requests = [request for request in result.requests if request.path == child_path]
        assert [request.param("per_page") for request in parent_requests] == [
            str(expected_parent_per_page),
            str(expected_parent_per_page),
        ]
        assert [request.param("page") for request in parent_requests] == ["1", "2"]
        assert [request.param("per_page") for request in child_requests] == [
            str(expected_child_per_page) if expected_child_per_page is not None else None
        ] * len(child_requests)
        assert [request.param("page") for request in child_requests] == (
            ["1", "2"] if expected_child_paginator is PageNumberPaginator else [None]
        )
        for request in child_requests:
            for key, value in expected_child_extra_params.items():
                assert request.param(key) == value
