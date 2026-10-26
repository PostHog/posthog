from datetime import UTC, datetime

import pytest
import time_machine

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lodgify import (
    LodgifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.lodgify import (
    LodgifyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lodgify.source import LodgifySource


def driver() -> SourceDriver:
    return SourceDriver(LodgifySource(), LodgifySourceConfig(api_key="test-key"))


@pytest.mark.parametrize("endpoint", ["properties", "bookings"])
@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2026-01-01T00:00:00Z", None),
        (True, None, None),
        (True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
        (True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
    ],
)
def test_sync_parameters(
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    result = driver().run(
        endpoint,
        [ScriptedResponse(json={"items": [{"id": 1}]}), ScriptedResponse(json={"items": []})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.response is not None
    assert result.response.sort_mode == "desc"
    assert result.rows == [{"id": 1}]
    assert len(result.requests) == 2
    for request in result.requests:
        assert request.param("updatedSince") == expected
        if endpoint == "bookings":
            assert request.param("stayFilter") == "All"
            assert request.param("trash") == "All"
            assert request.param("includeTransactions") == "true"
            assert request.param("includeQuoteDetails") == "true"


@pytest.mark.parametrize("resume", [False, True])
def test_room_fanout(resume: bool) -> None:
    state = LodgifyResumeConfig(
        paginator_state={"completed": ["properties/10/rooms"], "current": None, "child_state": None}
    )
    result = driver().run(
        "rooms",
        [
            ScriptedResponse(json={"items": [{"id": 10}, {"id": 20}, {"id": 30}]}),
            *([] if resume else [ScriptedResponse(json=[{"id": 1, "name": "Room one"}])]),
            ScriptedResponse(json=[{"id": 1, "name": "Room two"}]),
            ScriptedResponse(json=[]),
            ScriptedResponse(json={"items": []}),
        ],
        resume_state=state if resume else None,
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
    )

    assert result.raised is None
    assert result.rows == [
        *([] if resume else [{"id": 1, "name": "Room one", "property_id": 10}]),
        {"id": 1, "name": "Room two", "property_id": 20},
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["property_id", "id"]
    assert result.paths == [
        "/v2/properties",
        *([] if resume else ["/v2/properties/10/rooms"]),
        "/v2/properties/20/rooms",
        "/v2/properties/30/rooms",
        "/v2/properties",
    ]
    assert all(request.param("updatedSince") is None for request in result.requests)
    assert result.saved_states[-1].paginator_state["completed"] == [
        "properties/10/rooms",
        "properties/20/rooms",
        "properties/30/rooms",
    ]


@pytest.mark.parametrize(
    "calendars,expected_rows",
    [
        ([], []),
        ([{"user_id": 5, "property_id": 10, "room_type_id": 11, "periods": None}], []),
        (
            [
                {
                    "user_id": 5,
                    "property_id": 10,
                    "room_type_id": 11,
                    "periods": [
                        {"start": "2026-03-01", "end": "2026-03-04", "available": 1, "bookings": []},
                        {"start": "2026-03-05", "end": "2026-03-07", "available": 0, "bookings": [{"id": 7}]},
                    ],
                },
                {"user_id": 5, "property_id": 20, "room_type_id": 21, "periods": []},
            ],
            [
                {
                    "user_id": 5,
                    "property_id": 10,
                    "room_type_id": 11,
                    "start": "2026-03-01",
                    "end": "2026-03-04",
                    "available": 1,
                    "bookings": [],
                },
                {
                    "user_id": 5,
                    "property_id": 10,
                    "room_type_id": 11,
                    "start": "2026-03-05",
                    "end": "2026-03-07",
                    "available": 0,
                    "bookings": [{"id": 7}],
                },
            ],
        ),
    ],
)
@time_machine.travel(datetime(2026, 3, 1, 23, 30, tzinfo=UTC), tick=False)
def test_availability_rows(calendars: list[dict], expected_rows: list[dict]) -> None:
    result = driver().run(
        "availability",
        [ScriptedResponse(json=calendars)],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
    )

    assert result.raised is None
    assert result.rows == expected_rows
    assert result.paths == ["/v2/availability"]
    assert result.queries == [
        {"start": ("2026-03-01",), "end": ("2027-03-01",), "includeDetails": ("true",)},
    ]


@pytest.mark.parametrize("resume", [False, True])
@time_machine.travel(datetime(2026, 3, 1, tzinfo=UTC), tick=False)
def test_rates_calendar_fanout(resume: bool) -> None:
    state = LodgifyResumeConfig(
        paginator_state={
            "completed": ["rates/calendar?HouseId=10&RoomTypeId=11"],
            "current": None,
            "child_state": None,
        },
        window_start="2026-02-27",
        window_end="2027-02-27",
    )
    result = driver().run(
        "rates_calendar",
        [
            ScriptedResponse(
                json=[
                    {"property_id": 10, "room_type_id": 11, "periods": []},
                    {"property_id": 20, "room_type_id": 21, "periods": None},
                    {"property_id": 30, "room_type_id": 31, "periods": []},
                ]
            ),
            *(
                []
                if resume
                else [ScriptedResponse(json={"calendar_items": [{"date": "2026-03-01", "is_default": True}]})]
            ),
            ScriptedResponse(
                json={
                    "calendar_items": [
                        {"date": None, "is_default": True, "prices": []},
                        {"date": "2026-03-02", "is_default": False, "prices": [{"min_stay": 2}]},
                    ],
                    "rate_settings": {"currency_code": "EUR"},
                }
            ),
            ScriptedResponse(json={"calendar_items": None}),
        ],
        resume_state=state if resume else None,
    )

    assert result.raised is None
    assert result.rows == [
        *([] if resume else [{"date": "2026-03-01", "is_default": True, "property_id": 10, "room_type_id": 11}]),
        {"date": "2026-03-02", "is_default": False, "prices": [{"min_stay": 2}], "property_id": 20, "room_type_id": 21},
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["property_id", "room_type_id", "date"]
    assert result.paths == ["/v2/availability"] + ["/v2/rates/calendar"] * (2 if resume else 3)
    assert result.params("HouseId") == [None, *([] if resume else ["10"]), "20", "30"]
    assert result.params("RoomTypeId") == [None, *([] if resume else ["11"]), "21", "31"]
    # A resumed sync keeps the window it started with, even after the date has moved on.
    assert set(result.params("StartDate")[1:]) == ({"2026-02-27"} if resume else {"2026-03-01"})
    assert set(result.params("EndDate")[1:]) == ({"2027-02-27"} if resume else {"2027-03-01"})
    assert result.saved_states[-1].window_start == ("2026-02-27" if resume else "2026-03-01")
    assert result.saved_states[-1].paginator_state["completed"] == [
        "rates/calendar?HouseId=10&RoomTypeId=11",
        "rates/calendar?HouseId=20&RoomTypeId=21",
        "rates/calendar?HouseId=30&RoomTypeId=31",
    ]


@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (False, "2026-01-01T00:00:00Z", None),
        (True, None, None),
        (True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00+00:00"),
    ],
)
def test_external_bookings_fanout(incremental: bool, watermark: str | None, expected: str | None) -> None:
    result = driver().run(
        "external_bookings",
        [
            ScriptedResponse(
                json={
                    "items": [
                        {"id": 100, "updated_at": "2026-02-01T10:00:00Z"},
                        {"id": 200, "updated_at": "2026-02-02T10:00:00Z"},
                    ]
                }
            ),
            ScriptedResponse(
                json={
                    "external_bookings": [
                        {"created_at": "2026-01-30T08:00:00Z", "content": "channel booking A"},
                        {"created_at": "2026-01-31T08:00:00Z", "content": "channel booking B"},
                    ]
                }
            ),
            ScriptedResponse(json={"external_bookings": []}),
            ScriptedResponse(json={"items": [{"id": 300, "updated_at": "2026-02-03T10:00:00Z"}]}),
            ScriptedResponse(json={"external_bookings": None}),
            ScriptedResponse(json={"items": []}),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.rows == [
        {
            "created_at": datetime(2026, 1, 30, 8, tzinfo=UTC),
            "content": "channel booking A",
            "booking_id": 100,
            "booking_updated_at": datetime(2026, 2, 1, 10, tzinfo=UTC),
        },
        {
            "created_at": datetime(2026, 1, 31, 8, tzinfo=UTC),
            "content": "channel booking B",
            "booking_id": 100,
            "booking_updated_at": datetime(2026, 2, 1, 10, tzinfo=UTC),
        },
    ]
    assert result.paths == [
        "/v2/reservations/bookings",
        "/v2/reservations/bookings/100/externalBookings",
        "/v2/reservations/bookings/200/externalBookings",
        "/v2/reservations/bookings",
        "/v2/reservations/bookings/300/externalBookings",
        "/v2/reservations/bookings",
    ]
    assert result.params("updatedSince") == [expected, None, None, expected, None, expected]
    assert result.params("page") == ["1", None, None, "2", None, "3"]


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
    ],
)
def test_credential_validation(status: int, expected: tuple[bool, str | None]) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"items": []})]) as network:
        assert validate_credentials("test-key") == expected

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["x-apikey"] == "test-key"
    assert request.query == {"page": ("1",), "size": ("1",)}


@pytest.mark.parametrize("status", [401, 403, 400, 404])
def test_permanent_errors(status: int) -> None:
    result = driver().run("properties", [ScriptedResponse(status=status, json={})])

    assert isinstance(result.raised, HTTPError)
    matches = [
        message
        for pattern, message in LodgifySource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert matches == ([AUTH_ERROR] if status == 401 else [PERMISSION_ERROR] if status == 403 else [])
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_validation_propagates_other_errors(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials("test-key")

    assert len(network.requests_log) == 1


@pytest.mark.parametrize(
    "endpoint,watermark,message",
    [
        ("unknown", None, "Unsupported Lodgify table"),
        ("properties", "invalid", "Invalid Lodgify sync timestamp"),
    ],
)
def test_invalid_inputs(endpoint: str, watermark: str | None, message: str) -> None:
    result = driver().run(
        endpoint,
        [],
        should_use_incremental_field=True,
        db_incremental_field_last_value=watermark,
    )

    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert result.requests == []


def test_missing_response_list_fails() -> None:
    result = driver().run("properties", [ScriptedResponse(json={"unexpected": []})])

    assert isinstance(result.raised, ValueError)
