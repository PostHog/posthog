import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lexwareoffice import (
    LexwareOfficeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.lexware_office import (
    LexwareOfficeResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.source import LexwareOfficeSource


def driver() -> SourceDriver:
    return SourceDriver(LexwareOfficeSource(), LexwareOfficeSourceConfig(api_key="fake-key"))


@pytest.mark.parametrize("completed", [False, True])
def test_resume_starts_at_saved_page_or_stops(completed: bool) -> None:
    result = driver().run(
        "contacts",
        [] if completed else [ScriptedResponse(json={"content": [{"id": "d"}], "totalPages": 4})],
        resume_state=LexwareOfficeResumeConfig(paginator_state={"page": 3}, completed=completed),
    )

    assert result.raised is None
    assert result.items == ([] if completed else [[{"id": "d"}]])
    if completed:
        assert result.requests == []
    else:
        assert result.params("page") == ["3"]


@pytest.mark.parametrize("endpoint", ["contacts", "invoices"])
def test_empty_collection_and_search_window_limit(endpoint: str) -> None:
    empty = driver().run(endpoint, [ScriptedResponse(json={"content": [], "totalPages": 0, "totalElements": 0})])
    assert empty.raised is None
    assert empty.items == []

    full = driver().run(
        endpoint,
        [ScriptedResponse(json={"content": [{"id": "a"}], "totalPages": 40, "totalElements": 10000})],
    )
    assert isinstance(full.raised, ValueError)
    assert "10,000-record search limit" in str(full.raised)
    assert full.paths == ["/v1/contacts" if endpoint == "contacts" else "/v1/voucherlist"]


@pytest.mark.parametrize("status", [429, 500, 503, 401, 403, 404])
def test_status_retries_are_owned_by_shared_transport(status: int) -> None:
    result = driver().run(
        "contacts",
        [
            ScriptedResponse(status=status, json={}, headers={"Retry-After": "0"}),
            ScriptedResponse(json={"content": [{"id": "a"}], "totalPages": 1}),
        ],
    )

    if status in (401, 403, 404):
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1
    else:
        assert result.raised is None
        assert result.items == [[{"id": "a"}]]
        assert len(result.requests) == 2
