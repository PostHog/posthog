from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.opn_payments._config import OpnPaymentsSourceConfig
from products.warehouse_sources.sources.opn_payments.opn_payments import (
    OpnPaymentsResumeConfig,
    _to_iso8601,
    validate_credentials,
)
from products.warehouse_sources.sources.opn_payments.source import OpnPaymentsSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _envelope(data: list[dict[str, Any]], offset: int, total: int, limit: int = 100) -> dict[str, Any]:
    return {"object": "list", "data": data, "offset": offset, "limit": limit, "total": total}


def _page(size: int, start_id: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"chrg_{start_id + i}"} for i in range(size)]


def _driver() -> SourceDriver:
    return SourceDriver(OpnPaymentsSource(), OpnPaymentsSourceConfig(secret_key="skey_test_123"))


class TestToIso8601:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _to_iso8601(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool, expected_message: str | None) -> None:
        answer = ScriptedResponse(status=status_code, json={})
        script = always(answer) if status_code == 500 else [answer]
        with scripted_network(script) as network:
            valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is expected_valid
        assert message == expected_message
        assert {request.path for request in network.requests_log} == {"/account"}

    def test_swallows_request_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, message = validate_credentials("skey_test_123", "2019-05-29")

        assert valid is False
        assert message == "Could not reach the Opn Payments API."
        assert {request.path for request in network.requests_log} == {"/account"}


class TestOpnPaymentsSourcePagination:
    def test_walks_full_pages_by_offset_until_a_short_page(self) -> None:
        result = _driver().run(
            "Charges",
            [
                ScriptedResponse(json=_envelope(_page(100), offset=0, total=150)),
                ScriptedResponse(json=_envelope(_page(50, start_id=100), offset=100, total=150)),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 150
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        assert result.response is not None
        assert result.response.sort_mode == "asc"


class TestOpnPaymentsSourceIncremental:
    def test_full_refresh_never_sends_from_filter(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([{"id": "chrg_1"}], offset=0, total=1))],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("from") is None

    def test_incremental_defaults_to_epoch_on_first_sync(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([], offset=0, total=0))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("from") == "1970-01-01T00:00:00Z"


class TestOpnPaymentsSourceResume:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "Charges",
            [ScriptedResponse(json=_envelope([{"id": "9"}], offset=200, total=201))],
            resume_state=OpnPaymentsResumeConfig(offset=200),
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]


class TestOpnPaymentsSourceFanout:
    @parameterized.expand(
        [
            ("cards", "Cards", "/customers", "cust_test", "cards", "customer_id"),
            ("occurrences", "Occurrences", "/schedules", "schd_test", "occurrences", "schedule_id"),
        ]
    )
    def test_walks_every_parent_and_tags_rows_with_the_parent_id(
        self, _name: str, schema: str, parent_path: str, parent_prefix: str, child: str, parent_column: str
    ) -> None:
        first, second, gone = f"{parent_prefix}_a1", f"{parent_prefix}_b2", f"{parent_prefix}_c3"
        result = _driver().run(
            schema,
            route(
                {
                    f"{parent_path}/{first}/{child}": [
                        ScriptedResponse(json=_envelope(_page(100), offset=0, total=101)),
                        ScriptedResponse(json=_envelope(_page(1, start_id=100), offset=100, total=101)),
                    ],
                    f"{parent_path}/{second}/{child}": [
                        ScriptedResponse(json=_envelope([{"id": "row_b"}], offset=0, total=1)),
                    ],
                    f"{parent_path}/{gone}/{child}": [ScriptedResponse(status=404, json={"code": "not_found"})],
                    parent_path: [
                        ScriptedResponse(
                            json=_envelope([{"id": first}, {"id": second}, {"id": gone}], offset=0, total=3)
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            parent_path,
            f"{parent_path}/{first}/{child}",
            f"{parent_path}/{first}/{child}",
            f"{parent_path}/{second}/{child}",
            f"{parent_path}/{gone}/{child}",
        ]
        assert result.params("offset") == ["0", "0", "100", "0", "0"]
        assert [row[parent_column] for row in result.rows] == [first] * 101 + [second]
        assert all(f"_{parent_path[1:].capitalize()}_id" not in row for row in result.rows)
        assert result.requests[1].param("from") is None
        assert result.response is not None
        assert result.response.sort_mode is None

    def test_resumes_after_the_parents_it_already_finished(self) -> None:
        customers = ScriptedResponse(
            json=_envelope([{"id": "cust_test_a1"}, {"id": "cust_test_b2"}], offset=0, total=2)
        )
        first_cards = ScriptedResponse(json=_envelope([{"id": "card_a"}], offset=0, total=1))
        second_cards = ScriptedResponse(json=_envelope([{"id": "card_b"}], offset=0, total=1))

        interrupted = _driver().run(
            "Cards",
            route(
                {
                    "/customers/cust_test_a1/cards": [first_cards],
                    "/customers/cust_test_b2/cards": [
                        ScriptedResponse(status=401, json={"code": "authentication_failure"})
                    ],
                    "/customers": [customers],
                }
            ),
        )
        assert interrupted.raised is not None
        assert isinstance(interrupted.final_state, OpnPaymentsResumeConfig)
        assert interrupted.final_state.fanout_state is not None

        resumed = _driver().run(
            "Cards",
            route({"/customers/cust_test_b2/cards": [second_cards], "/customers": [customers]}),
            resume_state=interrupted.final_state,
        )

        assert resumed.raised is None
        assert "/customers/cust_test_a1/cards" not in resumed.paths
        assert [row["id"] for row in resumed.rows] == ["card_b"]
