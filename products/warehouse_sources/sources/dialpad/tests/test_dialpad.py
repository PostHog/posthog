from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.dialpad._config import DialpadSourceConfig
from products.warehouse_sources.sources.dialpad.dialpad import DialpadResumeConfig, to_epoch_millis
from products.warehouse_sources.sources.dialpad.source import DialpadSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver

# 2026-07-21T12:00:00Z, and the same moment less the three-hour lookback.
WATERMARK = datetime(2026, 7, 21, 12, tzinfo=UTC)
WATERMARK_MS = 1784635200000
LOOKBACK_START_MS = WATERMARK_MS - 3 * 60 * 60 * 1000


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)


def _driver() -> SourceDriver:
    return SourceDriver(DialpadSource(), DialpadSourceConfig(api_key="dp_test_key"))


def _page(items: Any, cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"items": items}
    if cursor is not None:
        body["cursor"] = cursor
    return ScriptedResponse(json=body)


def test_list_walks_cursor_pages_to_the_last_page() -> None:
    result = _driver().run(
        "users",
        [
            _page([{"id": "1"}, {"id": "2"}], cursor="c2"),
            # The Dialpad spec allows `items: null` on a page.
            _page(None, cursor="c3"),
            _page([{"id": "3"}]),
        ],
    )

    assert result.raised is None
    assert result.paths == ["/api/v2/users"] * 3
    assert result.params("cursor") == [None, "c2", "c3"]
    assert result.params("state") == ["all"] * 3
    assert result.requests[0].headers["authorization"] == "Bearer dp_test_key"
    assert [row["id"] for row in result.rows] == ["1", "2", "3"]
    assert result.committed_states == [DialpadResumeConfig(cursor="c2"), DialpadResumeConfig(cursor="c3")]


def test_resume_continues_from_the_saved_cursor() -> None:
    result = _driver().run(
        "contacts",
        [_page([{"id": "c_9"}])],
        resume_state=DialpadResumeConfig(cursor="saved"),
    )

    assert result.raised is None
    assert result.params("cursor") == ["saved"]
    assert result.params("include_local") == ["true"]


@parameterized.expand(
    [
        ("incremental_with_watermark", "date_started", True, WATERMARK, str(LOOKBACK_START_MS)),
        ("first_incremental_sync", "date_started", True, None, None),
        ("full_refresh", "date_started", False, WATERMARK, None),
    ]
)
def test_calls_request_shaping(
    _name: str,
    incremental_field: str,
    should_use_incremental_field: bool,
    last_value: datetime | None,
    expected_started_after: str | None,
) -> None:
    result = _driver().run(
        "calls",
        [_page([{"call_id": "1"}], cursor="next"), _page([{"call_id": "2"}])],
        incremental_field=incremental_field,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.params("started_after") == [expected_started_after] * 2
    assert result.params("include_anonymized") == ["true"] * 2
    assert result.params("cursor") == [None, "next"]
    assert result.response is not None
    assert result.response.sort_mode == "desc"


def test_calls_convert_epoch_millisecond_timestamps_to_utc_datetimes() -> None:
    result = _driver().run(
        "calls",
        [
            _page(
                [
                    {
                        "call_id": "1",
                        "date_started": WATERMARK_MS,
                        "date_ended": str(WATERMARK_MS + 1500),
                        "date_connected": None,
                        "date_rang": "",
                        "duration": 1500.0,
                    }
                ]
            )
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {
            "call_id": "1",
            "date_started": WATERMARK,
            "date_ended": datetime(2026, 7, 21, 12, 0, 1, 500000, tzinfo=UTC),
            "date_connected": None,
            "date_rang": "",
            "duration": 1500.0,
        }
    ]


@parameterized.expand(
    [
        ("labels", {"labels": ["Sale", "Follow up"]}, [{"label": "Sale"}, {"label": "Follow up"}]),
        ("null_labels", {"labels": None}, []),
    ]
)
def test_call_labels_become_one_row_per_label(_name: str, body: dict[str, Any], expected: list[dict]) -> None:
    result = _driver().run("call_labels", [ScriptedResponse(json=body)])

    assert result.raised is None
    assert result.paths == ["/api/v2/calllabels"]
    assert result.rows == expected


@parameterized.expand(
    [
        ("aware_datetime", WATERMARK, LOOKBACK_START_MS),
        ("naive_datetime_is_utc", datetime(2026, 7, 21, 12), LOOKBACK_START_MS),
        ("date", date(2026, 7, 21), WATERMARK_MS - 15 * 60 * 60 * 1000),
        ("iso_string", "2026-07-21T12:00:00+00:00", LOOKBACK_START_MS),
        ("epoch_millis", WATERMARK_MS, LOOKBACK_START_MS),
        ("none", None, None),
    ]
)
def test_to_epoch_millis_applies_the_lookback(_name: str, value: Any, expected: int | None) -> None:
    assert to_epoch_millis(value) == expected
