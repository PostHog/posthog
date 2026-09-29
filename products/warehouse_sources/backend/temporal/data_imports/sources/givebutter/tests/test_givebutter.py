from collections.abc import Generator, Iterable, Iterator
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

from django.test import override_settings

import structlog
from fakeredis import FakeRedis
from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.givebutter import (
    GivebutterResumeConfig,
    givebutter_source,
)

API = "https://api.givebutter.com/v1/"


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="transactions",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2099-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field="updated_at",
        incremental_field_type=None,
        job_id="job-test",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager(inputs: SourceInputs) -> Iterator[ResumableSourceManager[GivebutterResumeConfig]]:
    with (
        override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=FakeRedis(),
        ),
    ):
        yield ResumableSourceManager(inputs, GivebutterResumeConfig)


def pages(response: SourceResponse) -> Generator[list[dict[str, Any]]]:
    items = cast(Iterable[list[dict[str, Any]]], response.items())
    return cast(Generator[list[dict[str, Any]]], iter(items))


def test_pagination_and_resume_after_yield(
    requests_mock: Mocker,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GivebutterResumeConfig],
) -> None:
    next_url = API + "transactions?page=2&per_page=100"
    first = {"id": "txn-one", "created_at": "2025-01-01T00:00:00Z", "amount": 25}
    last = [{"id": "txn-two", "created_at": "2025-01-02T00:00:00Z", "amount": 10}]
    requests_mock.get(API + "transactions", json={"data": [first], "links": {"next": next_url}})
    requests_mock.get(next_url, json={"data": last, "links": {"next": None}})

    iterator = pages(givebutter_source("test-api-key", inputs, manager))
    assert next(iterator) == [first]
    assert not manager.has_staged_state()
    assert next(iterator) == last
    manager.commit()
    saved = manager.load_state()
    assert saved is not None
    assert saved.paginator_state == {"next_url": next_url}
    iterator.close()

    assert list(pages(givebutter_source("test-api-key", inputs, manager))) == [last]
    manager.commit()
    assert list(pages(givebutter_source("test-api-key", inputs, manager))) == []
    assert len(requests_mock.request_history) == 3
    first_request = requests_mock.request_history[0]
    assert first_request.headers["Authorization"] == "Bearer test-api-key"
    assert parse_qs(urlsplit(first_request.url).query) == {"per_page": ["100"]}
    assert requests_mock.request_history[-1].url == next_url


@pytest.mark.parametrize("has_first_page", [False, True])
def test_empty_collection_is_not_a_missing_data_envelope(
    requests_mock: Mocker,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GivebutterResumeConfig],
    has_first_page: bool,
) -> None:
    first = [{"id": "txn-one"}] if has_first_page else []
    next_url = API + "transactions?page=2"
    requests_mock.get(
        API + "transactions", json={"data": first, "links": {"next": next_url if has_first_page else None}}
    )
    requests_mock.get(next_url, json={"data": [], "links": {"next": None}})
    assert list(pages(givebutter_source("test-api-key", inputs, manager))) == ([first] if has_first_page else [])
    assert len(requests_mock.request_history) == (2 if has_first_page else 1)
    requests_mock.get(API + "transactions", json={"message": "Unexpected response"})
    with pytest.raises(ValueError, match="Required data_selector"):
        list(pages(givebutter_source("test-api-key", inputs, manager)))


def test_household_array_pagination_resumes_by_page_number(
    requests_mock: Mocker, inputs: SourceInputs, manager: ResumableSourceManager[GivebutterResumeConfig]
) -> None:
    inputs.schema_name = "households"
    requests_mock.get(API + "households?page=1", json=[{"id": 101}])
    requests_mock.get(API + "households?page=2", json=[{"id": 102}])
    requests_mock.get(API + "households?page=3", json=[])
    iterator = pages(givebutter_source("test-api-key", inputs, manager))
    assert next(iterator) == [{"id": 101}]
    assert next(iterator) == [{"id": 102}]
    manager.commit()
    iterator.close()
    requests_mock.reset_mock()

    assert list(pages(givebutter_source("test-api-key", inputs, manager))) == [[{"id": 102}]]
    assert [request.qs for request in requests_mock.request_history] == [{"page": ["2"]}, {"page": ["3"]}]


@pytest.mark.parametrize(
    ("table", "parent", "suffix", "parent_column"),
    [
        ("campaign_members", "campaigns", "members", "_campaigns_id"),
        ("campaign_teams", "campaigns", "teams", "_campaigns_id"),
        ("campaign_tickets", "campaigns", "items/tickets", "_campaigns_id"),
        ("campaign_discount_codes", "campaigns", "discount-codes", "_campaigns_id"),
        ("contact_activities", "contacts", "activities", "_contacts_id"),
    ],
)
def test_child_rows_have_unique_parent_keys_and_resume_within_parent(
    requests_mock: Mocker,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GivebutterResumeConfig],
    table: str,
    parent: str,
    suffix: str,
    parent_column: str,
) -> None:
    inputs.schema_name = table
    requests_mock.get(
        API + parent,
        json={"data": [{"id": "parent-one"}, {"id": "parent-two"}], "links": {"next": None}},
    )
    requests_mock.get(
        API + f"{parent}/parent-one/{suffix}", json={"data": [{"id": "shared-id"}], "links": {"next": None}}
    )
    child_url = API + f"{parent}/parent-two/{suffix}"
    next_url = child_url + "?page=2&per_page=100"
    requests_mock.get(child_url, json={"data": [{"id": "shared-id"}], "links": {"next": next_url}})
    requests_mock.get(next_url, json={"data": [{"id": "last-id"}], "links": {"next": None}})

    response = givebutter_source("test-api-key", inputs, manager)
    iterator = pages(response)
    rows = next(iterator) + next(iterator)
    assert rows == [
        {"id": "shared-id", parent_column: "parent-one"},
        {"id": "shared-id", parent_column: "parent-two"},
    ]
    assert response.primary_keys is not None
    assert len({tuple(row[key] for key in response.primary_keys) for row in rows}) == 2
    assert next(iterator) == [{"id": "last-id", parent_column: "parent-two"}]
    manager.commit()
    iterator.close()
    requests_mock.reset_mock()

    assert list(pages(givebutter_source("test-api-key", inputs, manager))) == [
        [{"id": "last-id", parent_column: "parent-two"}]
    ]
    assert [request.url for request in requests_mock.request_history] == [API + parent + "?per_page=100", next_url]


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_retry_the_same_page(
    requests_mock: Mocker, inputs: SourceInputs, manager: ResumableSourceManager[GivebutterResumeConfig], status: int
) -> None:
    requests_mock.get(
        API + "transactions",
        [
            {"status_code": status, "json": {"message": "Temporary failure"}, "headers": {"Retry-After": "0"}},
            {"json": {"data": [{"id": "txn-one"}], "links": {"next": None}}},
        ],
    )
    with patch.object(cast(Any, RESTClient._send_request).retry, "sleep"):
        assert list(pages(givebutter_source("test-api-key", inputs, manager))) == [[{"id": "txn-one"}]]
    assert len(requests_mock.request_history) == 2
    assert requests_mock.request_history[0].url == requests_mock.request_history[1].url


@pytest.mark.parametrize("next_url", ["https://example.com/steal", "http://api.givebutter.com/v1/transactions?page=2"])
def test_next_links_cannot_retarget_credentials(
    requests_mock: Mocker,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GivebutterResumeConfig],
    next_url: str,
) -> None:
    requests_mock.get(API + "transactions", json={"data": [{"id": "txn-one"}], "links": {"next": next_url}})
    with pytest.raises(ValueError, match="Refusing to send request"):
        list(pages(givebutter_source("test-api-key", inputs, manager)))
    assert len(requests_mock.request_history) == 1
