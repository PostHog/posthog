from datetime import UTC, datetime

import pytest

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
    "status,expected", [(200, (True, None)), (401, (False, AUTH_ERROR)), (403, (False, PERMISSION_ERROR))]
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
