from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.baseten import (
    BasetenResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.settings import (
    BASETEN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.baseten.source import BasetenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baseten import (
    BasetenSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(BasetenSource(), BasetenSourceConfig(api_key="test-key"))


def _page(body: dict[str, Any], status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestTopLevelEndpoints:
    def test_instance_type_prices_flattened(self) -> None:
        body = {
            "instance_types": [
                # Nested object lifts into the root; root-level siblings win on collision.
                {"instance_type": {"id": "gpu-1", "name": "A100", "price": 999}, "price": 0.5},
                # Rows without the nested key pass through untouched.
                {"id": "plain"},
            ]
        }
        result = _driver().run("instance_type_prices", [_page(body)])

        assert result.raised is None
        assert result.rows == [{"id": "gpu-1", "name": "A100", "price": 0.5}, {"id": "plain"}]


class TestCursorPagination:
    def test_pages_until_has_more_false_and_saves_cursor(self) -> None:
        result = _driver().run(
            "users",
            [
                _page({"items": [{"user_id": "u1"}], "pagination": {"has_more": True, "cursor": "c1"}}),
                _page({"items": [{"user_id": "u2"}], "pagination": {"has_more": True, "cursor": "c2"}}),
                _page({"items": [{"user_id": "u3"}], "pagination": {"has_more": False, "cursor": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "u3"}]
        # First request has no cursor; later requests carry the prior page's cursor.
        assert result.params("cursor") == [None, "c1", "c2"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.saved_states == [BasetenResumeConfig(cursor="c1"), BasetenResumeConfig(cursor="c2")]

    def test_has_more_false_stops_even_if_cursor_echoed(self) -> None:
        # A cursor echoed on the terminal page must not cause a loop.
        result = _driver().run(
            "users", [_page({"items": [{"user_id": "u1"}], "pagination": {"has_more": False, "cursor": "stale"}})]
        )

        assert result.raised is None
        assert result.rows == [{"user_id": "u1"}]
        assert result.paths == ["/v1/users"]

    def test_resume_seeds_saved_cursor(self) -> None:
        result = _driver().run(
            "users",
            [_page({"items": [{"user_id": "u9"}], "pagination": {}})],
            resume_state=BasetenResumeConfig(cursor="resumed-cursor"),
        )

        assert result.raised is None
        assert result.requests[0].param("cursor") == "resumed-cursor"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("users", [_page({"items": [], "pagination": {}})])

        assert result.raised is None
        assert result.params("cursor") == [None]


class TestFanOut:
    def test_injects_parent_id_and_yields_per_parent(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),  # parent list
                _page({"deployments": [{"id": "d1"}]}),  # m1 children
                _page({"deployments": [{"id": "d2"}]}),  # m2 children
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]
        assert result.urls[1] == "https://api.baseten.co/v1/models/m1/deployments"
        assert result.urls[2] == "https://api.baseten.co/v1/models/m2/deployments"
        # The resolve param binds into the path, not the query string.
        assert result.requests[1].param("model_id") is None
        # A checkpoint marking m1 complete is saved before m2 is processed.
        assert (
            BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            )
            in result.saved_states
        )
        # Every checkpoint stays parseable as the resume dataclass (cursor/parent_id untouched).
        assert all(
            state.cursor is None and state.parent_id is None and isinstance(state.fanout_state, dict)
            for state in result.saved_states
        )

    def test_404_child_is_skipped(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "gone"}, {"id": "m2"}]}),
                _page({"code": "NOT_FOUND"}, status=404),  # parent deleted mid-sync
                _page({"deployments": [{"id": "d2"}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d2", "model_id": "m2"}]

    def test_parent_without_id_is_skipped(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"name": "orphan"}]}),  # second parent has no id
                _page({"deployments": [{"id": "d1"}]}),  # only m1's children are fetched
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}]
        # The id-less parent must not produce a request against a stringified "None" id.
        assert not any("/models/None/" in url for url in result.urls)

    def test_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),
                _page({"deployments": [{"id": "d2"}]}),  # only m2 is fetched
            ],
            resume_state=BasetenResumeConfig(
                fanout_state={"completed": ["/v1/models/m1/deployments"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "d2", "model_id": "m2"}]
        child_urls = [url for url in result.urls if url.endswith("/deployments") and "/models/" in url]
        assert child_urls == ["https://api.baseten.co/v1/models/m2/deployments"]

    def test_legacy_parent_id_state_restarts_fan_out(self) -> None:
        # Pre-migration states bookmarked the next parent id; they still parse but the fan-out
        # restarts from the top (full-refresh tables, so re-appending is bounded).
        result = _driver().run(
            "deployments",
            [
                _page({"models": [{"id": "m1"}, {"id": "m2"}]}),
                _page({"deployments": [{"id": "d1"}]}),
                _page({"deployments": [{"id": "d2"}]}),
            ],
            resume_state=BasetenResumeConfig(parent_id="m2"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "d1", "model_id": "m1"}, {"id": "d2", "model_id": "m2"}]


class TestValidateCredentials:
    def test_network_error_is_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/v1/users/me"}


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_partition_and_primary_keys_match_config(self, endpoint: str) -> None:
        config = BASETEN_ENDPOINTS[endpoint]
        if config.fan_out_parent:
            parent_config = BASETEN_ENDPOINTS[config.fan_out_parent]
            script = [_page({parent_config.data_key: []})]
        else:
            script = [_page({config.data_key: []})]

        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
