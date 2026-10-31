from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oura import OuraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.oura import (
    DEFAULT_START_DATE,
    DEFAULT_START_DATETIME,
    OuraResumeConfig,
    _format_date,
    _format_datetime,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.source import OuraSource


def _collection(
    items: list[dict[str, Any]], next_token: str | None = None, *, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {"next_token": next_token}
    if not drop_data:
        body["data"] = items
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(OuraSource(), OuraSourceConfig(access_token="tok"))


class TestFormatHelpers:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 5, 1, 12, 30, tzinfo=UTC), "2021-05-01"),
            ("date", date(2021, 5, 1), "2021-05-01"),
            ("iso_string", "2021-05-01T00:00:00+00:00", "2021-05-01"),
        ]
    )
    def test_format_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_date(value) == expected

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2021, 5, 1, 12, 0, tzinfo=UTC), "2021-05-01T12:00:00+00:00"),
            ("naive_datetime_assumed_utc", datetime(2021, 5, 1, 12, 0), "2021-05-01T12:00:00+00:00"),
            ("date_to_midnight", date(2021, 5, 1), "2021-05-01T00:00:00+00:00"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestDateWindowParams:
    """The server-side date window is injected as a request param before pagination begins."""

    def test_datetime_endpoint_first_sync_uses_default(self) -> None:
        result = _driver().run("heartrate", [_collection([{"timestamp": "t", "source": "s"}])])
        assert result.raised is None
        assert result.params("start_datetime") == [DEFAULT_START_DATETIME]


class TestPagination:
    def test_follows_next_token_pagination(self) -> None:
        result = _driver().run(
            "daily_sleep",
            [
                _collection([{"id": "a"}, {"id": "b"}], next_token="tok1"),
                _collection([{"id": "c"}], next_token=None),
            ],
        )
        assert result.raised is None
        assert result.items == [[{"id": "a"}, {"id": "b"}], [{"id": "c"}]]
        assert result.params("next_token") == [None, "tok1"]
        # The date window is carried forward on every page.
        assert result.params("start_date") == [DEFAULT_START_DATE, DEFAULT_START_DATE]

    def test_resumes_from_saved_next_token(self) -> None:
        result = _driver().run(
            "daily_sleep", [_collection([{"id": "z"}])], resume_state=OuraResumeConfig(next_token="saved")
        )
        assert result.raised is None
        assert result.rows == [{"id": "z"}]
        assert result.params("next_token") == ["saved"]

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("daily_sleep", [_collection([], drop_data=True)])
        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestProbeEndpoint:
    @parameterized.expand([(200,), (401,), (403,), (404,)])
    def test_returns_status_code(self, status: int) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert probe_endpoint("tok", "/usercollection/personal_info") == status
        assert network.requests_log[0].path == "/v2/usercollection/personal_info"


class TestOuraSourceResponse:
    @parameterized.expand([("personal_info",), ("ring_configuration",)])
    def test_full_refresh_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        body: dict[str, Any] = (
            {"id": "a"} if endpoint == "personal_info" else {"data": [{"id": "a"}], "next_token": None}
        )
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_keys is None
        assert response.partition_mode is None
