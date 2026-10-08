from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import Mock

import requests_mock
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.poplar import (
    poplar_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.settings import BASE_URL

CAMPAIGNS = [{"id": "camp-1", "name": "Welcome postcards"}, {"id": "camp-2", "name": "Winback letters"}]


def sync_items(response: SourceResponse) -> Iterable[Any]:
    items = response.items()
    assert isinstance(items, Iterable)
    return items


def mailing(identifier: str, campaign_id: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "campaign_id": campaign_id,
        "creative_id": "crea-1",
        "merge_tags": {},
        "state": "delivered",
        "front_url": "https://example.com/front.jpg",
        "total_cost": "0.65",
        "created_at": "2026-01-05T10:00:00Z",
        "address": {"name": "Test Recipient", "address_1": "1 Example Street", "city": "Springfield"},
    }


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="campaign_mailings",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=Mock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> Mock:
    return Mock(can_resume=Mock(return_value=False))


def test_mailings_fan_out_per_campaign_and_save_state_after_yield(inputs: SourceInputs, manager: Mock) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/campaigns", json=CAMPAIGNS)
        http.get(
            f"{BASE_URL}/campaign/camp-1/mailings",
            [
                {"json": [mailing("mail-1", "camp-1")], "headers": {"X-Next-Page": "2"}},
                {"json": [mailing("mail-2", "camp-1")], "headers": {"X-Next-Page": ""}},
            ],
        )
        http.get(
            f"{BASE_URL}/campaign/camp-2/mailings",
            json=[mailing("mail-1", "camp-2")],
            headers={"X-Next-Page": ""},
        )
        response = poplar_source("fake-token", inputs, manager)
        rows = iter(sync_items(response))
        first = next(rows)
        manager.save_state.assert_not_called()
        second = next(rows)
        assert manager.save_state.call_args.args[0].paginator_state == {
            "completed": [],
            "current": "campaign/camp-1/mailings",
            "child_state": {"page": 2},
        }
        third = next(rows)
        assert list(rows) == []

        assert [(page[0]["campaign_id"], page[0]["id"]) for page in (first, second, third)] == [
            ("camp-1", "mail-1"),
            ("camp-1", "mail-2"),
            ("camp-2", "mail-1"),
        ]
        assert first[0]["address"] == {"name": "Test Recipient", "address_1": "1 Example Street", "city": "Springfield"}
        assert response.primary_keys == ["campaign_id", "id"]
        assert response.sort_mode == "desc"
        assert [request.qs for request in http.request_history] == [
            {},
            {"page": ["1"], "per_page": ["100"]},
            {"page": ["2"], "per_page": ["100"]},
            {"page": ["1"], "per_page": ["100"]},
        ]
        assert all(request.headers["Authorization"] == "Bearer fake-token" for request in http.request_history)


@pytest.mark.parametrize(
    "incremental,cursor,last_synced_at,expected",
    [
        (False, None, None, {}),
        (False, "2026-01-05T10:00:00Z", datetime(2026, 1, 6, 8, 30, tzinfo=UTC), {}),
        (True, None, datetime(2026, 1, 6, 8, 30, tzinfo=UTC), {}),
        (True, "2026-01-05T10:00:00Z", None, {}),
        (
            True,
            "2026-01-05T10:00:00Z",
            datetime(2026, 1, 6, 8, 30, tzinfo=UTC),
            {"start_date": ["2026-01-06t08:30:00z"], "date_field": ["updated_at"]},
        ),
    ],
)
def test_mailings_window_on_updated_at_only_after_an_incremental_sync(
    inputs: SourceInputs,
    manager: Mock,
    incremental: bool,
    cursor: str | None,
    last_synced_at: datetime | None,
    expected: dict[str, list[str]],
) -> None:
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = cursor
    inputs.last_synced_at = last_synced_at
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/campaigns", json=CAMPAIGNS[:1])
        http.get(f"{BASE_URL}/campaign/camp-1/mailings", json=[], headers={"X-Next-Page": ""})
        assert list(sync_items(poplar_source("fake-token", inputs, manager))) == []
        assert http.request_history[0].qs == {}
        assert http.request_history[1].qs == {"page": ["1"], "per_page": ["100"], **expected}


def test_stats_walk_every_page_without_a_date_range(inputs: SourceInputs, manager: Mock) -> None:
    inputs.schema_name = "campaign_stats"

    def page(number: int, campaign_id: str) -> dict[str, Any]:
        return {
            "total_circulation": 300,
            "total_spend": 195.0,
            "page": number,
            "total_pages": 2,
            "campaigns": [
                {"campaign_id": campaign_id, "campaign_name": "Welcome postcards", "circulation": 150, "spend": 97.5}
            ],
        }

    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/stats/campaigns", [{"json": page(1, "camp-1")}, {"json": page(2, "camp-2")}])
        response = poplar_source("fake-token", inputs, manager)
        rows = [row for batch in sync_items(response) for row in batch]
        assert [row["campaign_id"] for row in rows] == ["camp-1", "camp-2"]
        assert rows[0]["circulation"] == 150
        assert response.primary_keys == ["campaign_id"]
        assert [request.qs for request in http.request_history] == [
            {"page": ["1"], "per_page": ["30"]},
            {"page": ["2"], "per_page": ["30"]},
        ]


@pytest.mark.parametrize(
    "endpoint,path,body",
    [
        ("campaigns", "campaigns", {"error": {"title": "ServerError", "message": "unexpected"}}),
        ("campaign_stats", "stats/campaigns", {"total_pages": 1, "items": []}),
    ],
)
def test_unexpected_response_shape_fails_instead_of_emptying_the_table(
    inputs: SourceInputs, manager: Mock, endpoint: str, path: str, body: dict[str, Any]
) -> None:
    inputs.schema_name = endpoint
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/{path}", json=body)
        with pytest.raises(ValueError):
            list(sync_items(poplar_source("fake-token", inputs, manager)))


@pytest.mark.parametrize(
    "status,expected_success,expected_message",
    [
        (200, True, None),
        (401, False, "production token"),
        (403, False, "production token"),
        (500, False, "HTTP 500"),
        (None, False, "Could not connect"),
    ],
)
def test_credential_status_messages(status: int | None, expected_success: bool, expected_message: str | None) -> None:
    with requests_mock.Mocker() as http:
        if status is None:
            http.get(f"{BASE_URL}/me", exc=ConnectionError)
        else:
            http.get(
                f"{BASE_URL}/me", status_code=status, json={"id": "org-1", "name": "Example Co", "mode": "production"}
            )
        success, message = validate_credentials("fake-token")
        assert success == expected_success
        if expected_message is None:
            assert message is None
        else:
            assert message is not None
            assert expected_message in message
        if status is not None:
            assert http.request_history[0].headers["Authorization"] == "Bearer fake-token"
