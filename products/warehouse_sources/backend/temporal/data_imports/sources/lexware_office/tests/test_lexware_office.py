from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.lexware_office import (
    LexwareOfficeResumeConfig,
    lexware_office_source,
)

BASE = "https://api.lexware.io/v1"


def manager(state: LexwareOfficeResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = state
    return result


def rows(endpoint: str, resume: MagicMock) -> Iterable[list[dict[str, Any]]]:
    response = lexware_office_source("fake-key", endpoint, 1, "job", resume)
    return cast(Iterable[list[dict[str, Any]]], response.items())


@pytest.mark.parametrize("completed", [False, True])
def test_resume_starts_at_saved_page_or_stops(completed: bool) -> None:
    resume = manager(LexwareOfficeResumeConfig(paginator_state={"page": 3}, completed=completed))
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/contacts", json={"content": [{"id": "d"}], "totalPages": 4})
        assert list(rows("contacts", resume)) == ([] if completed else [[{"id": "d"}]])
        if completed:
            assert not http.called
        else:
            assert http.last_request is not None
            assert http.last_request.qs["page"] == ["3"]


@pytest.mark.parametrize("endpoint", ["contacts", "invoices"])
def test_empty_collection_and_search_window_limit(endpoint: str) -> None:
    url = f"{BASE}/contacts" if endpoint == "contacts" else f"{BASE}/voucherlist"
    with requests_mock.Mocker() as http:
        http.get(url, json={"content": [], "totalPages": 0, "totalElements": 0})
        assert not any(rows(endpoint, manager()))
        http.get(url, json={"content": [{"id": "a"}], "totalPages": 40, "totalElements": 10000})
        with pytest.raises(ValueError, match="10,000-record search limit"):
            list(rows(endpoint, manager()))


@pytest.mark.parametrize("status", [429, 500, 503, 401, 403, 404])
def test_status_retries_are_owned_by_shared_transport(status: int) -> None:
    with requests_mock.Mocker() as http, patch.object(RESTClient._send_request.retry, "sleep"):  # type: ignore[attr-defined]
        http.get(
            f"{BASE}/contacts",
            [
                {"status_code": status, "json": {}, "headers": {"Retry-After": "0"}},
                {"json": {"content": [{"id": "a"}], "totalPages": 1}},
            ],
        )
        if status in (401, 403, 404):
            with pytest.raises(HTTPError):
                list(rows("contacts", manager()))
            assert len(http.request_history) == 1
        else:
            assert list(rows("contacts", manager())) == [[{"id": "a"}]]
            assert len(http.request_history) == 2
