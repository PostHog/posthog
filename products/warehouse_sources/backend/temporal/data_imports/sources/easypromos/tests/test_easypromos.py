from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.easypromos import (
    EasypromosResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import EASYPROMOS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.source import EasypromosSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easypromos import (
    EasypromosSourceConfig,
)


def _body(items: list[dict[str, Any]], next_cursor: int | None) -> dict[str, Any]:
    return {"items": items, "paging": {"next_cursor": next_cursor, "items_page": 100}}


def _page(items: list[dict[str, Any]], next_cursor: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(json=_body(items, next_cursor))


def _driver() -> SourceDriver:
    return SourceDriver(EasypromosSource(), EasypromosSourceConfig(access_token="tok"))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        response = ScriptedResponse(status=status_code)
        script = always(response) if status_code >= 500 else [response]
        with scripted_network(script) as network:
            ok, error = validate_credentials("tok")
        assert network.requests_log[0].path == "/v2/promotions"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"
        assert ok is expected_ok
        if expected_msg is None:
            assert error is None
        else:
            assert error is not None and expected_msg in error

    def test_request_exception_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            ok, error = validate_credentials("tok")
        assert {request.path for request in network.requests_log} == {"/v2/promotions"}
        assert ok is False
        assert error is not None


class TestTopLevelPagination:
    def test_does_not_inject_promotion_id_for_top_level(self) -> None:
        result = _driver().run("organizing_brands", [_page([{"id": 7, "name": "Acme"}])])
        assert result.raised is None
        assert result.rows == [{"id": 7, "name": "Acme"}]
        assert "promotion_id" not in result.rows[0]

    def test_resumes_from_saved_cursor(self) -> None:
        # The first request must use the saved cursor.
        result = _driver().run("promotions", [_page([{"id": 3}])], resume_state=EasypromosResumeConfig(cursor=100))
        assert result.raised is None
        assert result.rows == [{"id": 3}]
        assert result.paths == ["/v2/promotions"]
        assert result.params("next_cursor") == ["100"]

    def test_checkpoints_next_cursor_while_a_page_remains(self) -> None:
        result = _driver().run("promotions", [_page([{"id": 1}], 100), _page([{"id": 2}])])
        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.params("next_cursor") == [None, "100"]
        # The final page has no next cursor and is not checkpointed.
        assert result.saved_states == [EasypromosResumeConfig(cursor=100)]


class TestFanOut:
    def test_fans_out_over_promotions_and_injects_promotion_id(self) -> None:
        result = _driver().run(
            "users",
            [
                _page([{"id": 10}, {"id": 20}]),
                _page([{"id": 1}, {"id": 2}]),
                _page([{"id": 1}]),
            ],
        )
        assert result.raised is None
        assert result.paths == ["/v2/promotions", "/v2/users/10", "/v2/users/20"]
        assert result.rows == [
            {"id": 1, "promotion_id": 10},
            {"id": 2, "promotion_id": 10},
            {"id": 1, "promotion_id": 20},
        ]

    def test_checkpoint_records_fanout_progress(self) -> None:
        result = _driver().run("prizes", [_page([{"id": 10}]), _page([{"id": 1}])])
        assert result.raised is None
        assert result.paths == ["/v2/promotions", "/v2/prizes/10"]
        # The final checkpoint marks the child path complete so a restart skips it.
        assert result.saved_states[-1] == EasypromosResumeConfig(
            fanout_state={"completed": ["/prizes/10"], "current": None, "child_state": None}
        )

    def test_resume_skips_the_promotions_already_completed(self) -> None:
        result = _driver().run(
            "users",
            [_page([{"id": 10}, {"id": 20}]), _page([{"id": 1}])],
            resume_state=EasypromosResumeConfig(
                fanout_state={"completed": ["/users/10"], "current": None, "child_state": None}
            ),
        )
        assert result.raised is None
        assert result.paths == ["/v2/promotions", "/v2/users/20"]
        assert result.rows == [{"id": 1, "promotion_id": 20}]


class TestSourceResponse:
    @parameterized.expand(list(EASYPROMOS_ENDPOINTS.keys()))
    def test_primary_keys_and_partitioning_match_settings(self, endpoint: str) -> None:
        config = EASYPROMOS_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([])])
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

    def test_fan_out_children_carry_promotion_id_in_primary_key(self) -> None:
        for endpoint, config in EASYPROMOS_ENDPOINTS.items():
            if config.fan_out_over_promotions:
                assert "promotion_id" in config.primary_keys, endpoint
