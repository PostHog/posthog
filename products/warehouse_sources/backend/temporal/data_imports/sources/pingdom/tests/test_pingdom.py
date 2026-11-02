from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pingdom import (
    PingdomSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom import (
    PingdomResumeConfig,
    _to_epoch,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    DAY_SECONDS,
    PINGDOM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.source import PingdomSource


def _nest(data_key: str, items: Any) -> dict[str, Any]:
    body: Any = items
    for key in reversed(data_key.split(".")):
        body = {key: body}
    return body


def _response(endpoint: str, items: Any) -> ScriptedResponse:
    return ScriptedResponse(json=_nest(PINGDOM_ENDPOINTS[endpoint].data_key, items))


def _driver() -> SourceDriver:
    return SourceDriver(PingdomSource(), PingdomSourceConfig(api_token="token"))


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestPagination:
    def test_paginates_until_short_page(self) -> None:
        page_size = PINGDOM_ENDPOINTS["alerts"].page_size
        full_page = [{"time": i} for i in range(page_size)]
        result = _driver().run("alerts", [_response("alerts", full_page), _response("alerts", [{"time": page_size}])])

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert result.params("offset") == ["0", str(page_size)]
        assert result.params("limit") == [str(page_size), str(page_size)]
        # Checkpoint saved once, after the first full page, pointing at the next offset.
        assert result.saved_states == [PingdomResumeConfig(offset=page_size)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "checks", [_response("checks", [{"id": 1}])], resume_state=PingdomResumeConfig(offset=50000)
        )

        assert result.raised is None
        assert result.params("offset") == ["50000"]

    def test_incremental_request_includes_from_filter(self) -> None:
        result = _driver().run(
            "alerts",
            [_response("alerts", [])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        assert result.params("from") == ["1700000000"]


NOW = 1_800_000_000


def _checks(*ids: int) -> ScriptedResponse:
    return _response("checks", [{"id": check_id, "name": f"check {check_id}"} for check_id in ids])


class TestPerCheckFanout:
    @time_machine.travel(NOW, tick=False)
    def test_results_walk_every_check_and_page_in_one_window(self) -> None:
        page_size = PINGDOM_ENDPOINTS["results"].page_size
        full_page = [{"probeid": 1, "time": NOW - i} for i in range(page_size)]
        result = _driver().run(
            "results",
            route(
                {
                    "/checks": [_checks(1, 2)],
                    "/results/1": [_response("results", full_page), _response("results", [{"probeid": 2, "time": 5}])],
                    "/results/2": [_response("results", [{"probeid": 3, "time": 7}])],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/3.1/checks", "/api/3.1/results/1", "/api/3.1/results/1", "/api/3.1/results/2"]
        assert result.params("offset") == ["0", "0", str(page_size), "0"]
        assert result.params("to") == [None, str(NOW), str(NOW), str(NOW)]
        assert result.params("from") == [None] + [str(NOW - 7 * DAY_SECONDS)] * 3
        assert len(result.rows) == page_size + 2
        assert [row["checkid"] for row in result.rows[-2:]] == [1, 2]
        assert all("_checks_id" not in row for row in result.rows)
        assert result.saved_states and all(state.window_end == NOW for state in result.saved_states)

    @pytest.mark.parametrize(
        "endpoint, watermark, expected_windows",
        [
            ("results", NOW - DAY_SECONDS, [(NOW - DAY_SECONDS, NOW)]),
            ("results", None, [(NOW - 7 * DAY_SECONDS, NOW)]),
            (
                "results",
                NOW - 10 * DAY_SECONDS,
                [(NOW - 10 * DAY_SECONDS, NOW - 3 * DAY_SECONDS), (NOW - 3 * DAY_SECONDS, NOW)],
            ),
            ("performance", NOW - 3600, [(NOW - 3600, NOW)]),
            (
                "performance",
                NOW - 15 * DAY_SECONDS,
                [
                    (NOW - 15 * DAY_SECONDS, NOW - 8 * DAY_SECONDS),
                    (NOW - 8 * DAY_SECONDS, NOW - DAY_SECONDS),
                    (NOW - DAY_SECONDS, NOW),
                ],
            ),
        ],
    )
    @time_machine.travel(NOW, tick=False)
    def test_incremental_sync_walks_bounded_windows_from_the_watermark(
        self, endpoint: str, watermark: int | None, expected_windows: list[tuple[int, int]]
    ) -> None:
        path = PINGDOM_ENDPOINTS[endpoint].path.replace("{checkid}", "1")
        result = _driver().run(
            endpoint,
            route(
                {
                    "/checks": [_checks(1)] * len(expected_windows),
                    path: [_response(endpoint, [])] * len(expected_windows),
                }
            ),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        child_requests = [request for request in result.requests if request.path.endswith(path)]
        assert [(r.param("from"), r.param("to")) for r in child_requests] == [
            (str(start), str(end)) for start, end in expected_windows
        ]

    def test_results_pagination_stops_within_the_offset_cap(self) -> None:
        full_page = _response("results", [{"probeid": 1, "time": i} for i in range(1000)])
        result = _driver().run("results", route({"/checks": [_checks(1)], "/results/1": [full_page] * 50}))

        assert result.raised is None
        assert max(int(offset) for offset in result.params("offset") if offset is not None) <= 43200

    def test_performance_and_outages_request_one_page_per_check(self) -> None:
        result = _driver().run(
            "performance",
            route(
                {
                    "/checks": [_checks(1)],
                    "/summary.performance/1": [
                        _response("performance", [{"starttime": 100, "avgresponse": 200, "uptime": 3600}])
                    ],
                }
            ),
        )

        assert result.raised is None
        request = result.requests[-1]
        assert (request.param("resolution"), request.param("includeuptime"), request.param("offset")) == (
            "hour",
            "true",
            None,
        )
        assert result.rows == [{"starttime": 100, "avgresponse": 200, "uptime": 3600, "checkid": 1}]

    def test_resume_skips_finished_checks_and_reuses_the_window(self) -> None:
        window_end = NOW - 600
        result = _driver().run(
            "outages",
            route({"/checks": [_checks(1, 2)], "/summary.outage/2": [_response("outages", [])]}),
            resume_state=PingdomResumeConfig(
                fanout_state={"completed": ["/summary.outage/1"], "current": None, "child_state": None},
                window_start=window_end - 365 * DAY_SECONDS,
                window_end=window_end,
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/3.1/checks", "/api/3.1/summary.outage/2"]
        assert result.params("to") == [None, str(window_end)]
        assert result.params("from") == [None, str(window_end - 365 * DAY_SECONDS)]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") is expected

        assert network.requests_log[0].path == "/api/3.1/checks"
        assert network.requests_log[0].param("limit") == "1"


class TestPingdomSourceResponse:
    def test_alerts_duplicate_composite_key_does_not_block_incremental_sync(self) -> None:
        # Alert rows' composite key (checkid, time, userid, via) can collide, but that's expected
        # for this data and must not block incremental syncing (the only incremental field this
        # endpoint offers is `time`) - regression test for the schema-wide incremental sync outage
        # this caused when has_duplicate_primary_keys was set unconditionally for this endpoint.
        result = _driver().run("alerts", [_response("alerts", [])])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert not response.has_duplicate_primary_keys
        validate_incremental_sync(True, response)

    @pytest.mark.parametrize("config", list(PINGDOM_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            # Event, interval-start and creation timestamps never change once written.
            assert config.partition_key in {"time", "timefrom", "starttime", "created_at"}
