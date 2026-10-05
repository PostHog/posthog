from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import responses

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productive import (
    ProductiveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.productive import (
    ProductiveResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.source import ProductiveSource


@pytest.mark.parametrize(
    "endpoint",
    [
        "bookings",
        "companies",
        "contact_entries",
        "deals",
        "expenses",
        "invoices",
        "payments",
        "people",
        "projects",
        "services",
        "tasks",
        "time_entries",
    ],
)
@responses.activate
def test_paginated_full_refresh_preserves_ids_and_relationships(
    config: ProductiveSourceConfig, inputs: SourceInputs, resume_manager: MagicMock, endpoint: str
) -> None:
    inputs.schema_name = endpoint
    url = f"https://api.productive.io/api/v2/{endpoint}"
    relationship = {"company": {"data": {"id": "99", "type": "companies"}}}
    for identifier in ("101", "102"):
        responses.get(
            url,
            json={
                "data": [
                    {
                        "id": identifier,
                        "type": endpoint,
                        "attributes": {"name": "Example record", "created_at": "2026-01-01T00:00:00Z"},
                        "relationships": relationship,
                    }
                ],
                "included": [{"id": "99", "type": "companies", "attributes": {"name": "Example company"}}],
                "meta": {"total_pages": 2},
            },
        )

    result = ProductiveSource().source_for_pipeline(config, resume_manager, inputs)
    pages = iter(cast(Iterable[list[dict[str, Any]]], result.items()))
    assert next(pages)[0] == {
        "id": "101",
        "type": endpoint,
        "name": "Example record",
        "created_at": "2026-01-01T00:00:00Z",
        "relationships": relationship,
    }
    resume_manager.save_state.assert_not_called()
    assert next(pages)[0]["id"] == "102"
    resume_manager.save_state.assert_called_once_with(ProductiveResumeConfig(next_page=2))
    with pytest.raises(StopIteration):
        next(pages)
    assert resume_manager.save_state.call_args.args[0] == ProductiveResumeConfig(next_page=None)
    assert len(responses.calls) == 2
    for page_number, call in enumerate(responses.calls, start=1):
        assert parse_qs(urlsplit(call.request.url).query) == {
            "page[size]": ["200"],
            "page[number]": [str(page_number)],
        }
        assert call.request.headers["X-Auth-Token"] == "test-productive-token"
        assert call.request.headers["X-Organization-Id"] == "123"
        assert call.request.headers["Content-Type"] == "application/vnd.api+json"


@pytest.mark.parametrize("next_page", [3, None])
@responses.activate
def test_resume_starts_at_checkpoint_or_skips_completed_import(
    config: ProductiveSourceConfig, inputs: SourceInputs, resume_manager: MagicMock, next_page: int | None
) -> None:
    resume_manager.can_resume.return_value = True
    resume_manager.load_state.return_value = ProductiveResumeConfig(next_page=next_page)
    if next_page is not None:
        responses.get(
            "https://api.productive.io/api/v2/projects",
            json={"data": [{"id": "103", "type": "projects", "attributes": {}}], "meta": {"total_pages": 3}},
        )
    result = ProductiveSource().source_for_pipeline(config, resume_manager, inputs)
    pages = list(cast(Iterable[list[dict[str, Any]]], result.items()))
    if next_page is None:
        assert pages == []
        assert len(responses.calls) == 0
    else:
        assert pages == [[{"id": "103", "type": "projects"}]]
        assert len(responses.calls) == 1
        assert parse_qs(urlsplit(responses.calls[0].request.url).query)["page[number]"] == ["3"]


@pytest.mark.parametrize("meta", [{"total_pages": 0}, {}])
@responses.activate
def test_empty_collection_terminates(
    config: ProductiveSourceConfig, inputs: SourceInputs, resume_manager: MagicMock, meta: dict[str, int]
) -> None:
    responses.get("https://api.productive.io/api/v2/projects", json={"data": [], "meta": meta})
    result = ProductiveSource().source_for_pipeline(config, resume_manager, inputs)
    assert not any(cast(Iterable[list[dict[str, Any]]], result.items()))
    assert len(responses.calls) == 1


def test_unknown_schema_never_becomes_a_request_path(
    config: ProductiveSourceConfig, inputs: SourceInputs, resume_manager: MagicMock
) -> None:
    inputs.schema_name = "https://example.com/collect"
    with pytest.raises(UnknownResourceError):
        ProductiveSource().source_for_pipeline(config, resume_manager, inputs)
