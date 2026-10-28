from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import validate_incremental_sync
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import PINGDOM_ENDPOINTS
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
            # Alert timestamps are immutable event times.
            assert config.partition_key == "time"
