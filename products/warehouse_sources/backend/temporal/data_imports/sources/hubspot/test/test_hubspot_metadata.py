import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.metadata import (
    METADATA_FETCHERS,
    get_owners_rows,
    get_pipeline_stages_rows,
    get_pipelines_rows,
    get_properties_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
    HUBSPOT_API_VERSION_2026_03,
    HUBSPOT_METADATA_ENDPOINTS,
    PIPELINE_OBJECT_TYPES,
)

_FETCH_DATA = "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.metadata.fetch_data"

PIPELINE_PAYLOAD = [
    {
        "id": "default",
        "label": "Sales pipeline",
        "displayOrder": 0,
        "archived": False,
        "createdAt": "2020-01-01T00:00:00Z",
        "updatedAt": "2020-01-02T00:00:00Z",
        "stages": [
            {
                "id": "appointmentscheduled",
                "label": "Appointment scheduled",
                "displayOrder": 0,
                "archived": False,
                "metadata": {"isClosed": "false", "probability": "0.2"},
            }
        ],
    }
]


def _fetch_data_returning(pages_by_path: dict[str, list[list[dict[str, Any]]]]) -> Any:
    def _fake(path: str, *_args: Any, **_kwargs: Any) -> Iterator[list[dict[str, Any]]]:
        yield from pages_by_path.get(path, [])

    return _fake


def _call(fetcher: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in fetcher(
        api_key="key",
        refresh_token="refresh",
        logger=MagicMock(),
        source_id="source-1",
        api_version=HUBSPOT_API_VERSION_2026_03,
    ):
        rows.extend(page)
    return rows


class TestMetadataFetchers:
    def test_pipelines_carry_object_type_and_drop_stages(self) -> None:
        # Pipeline ids are only unique within an object type, so a row without object_type would
        # let the deals and tickets "default" pipelines overwrite each other on merge. The nested
        # stages blob belongs to the pipeline_stages table, not here.
        with patch(
            _FETCH_DATA,
            new=_fetch_data_returning(
                {f"/crm/pipelines/2026-03/{o}": [PIPELINE_PAYLOAD] for o in PIPELINE_OBJECT_TYPES}
            ),
        ):
            rows = _call(get_pipelines_rows)

        assert [r["object_type"] for r in rows] == list(PIPELINE_OBJECT_TYPES)
        assert all(r["id"] == "default" for r in rows)
        assert all("stages" not in r for r in rows)

    def test_pipeline_stages_carry_parent_ids(self) -> None:
        # Stage ids repeat across pipelines, so without object_type + pipeline_id the table's
        # primary key is not unique and every merge multi-matches.
        with patch(
            _FETCH_DATA,
            new=_fetch_data_returning(
                {f"/crm/pipelines/2026-03/{o}": [PIPELINE_PAYLOAD] for o in PIPELINE_OBJECT_TYPES}
            ),
        ):
            rows = _call(get_pipeline_stages_rows)

        assert {(r["object_type"], r["pipeline_id"], r["id"]) for r in rows} == {
            (o, "default", "appointmentscheduled") for o in PIPELINE_OBJECT_TYPES
        }

    def test_nested_values_are_json_encoded(self) -> None:
        # Stage metadata keys differ between deals and tickets. Left as a dict, PyArrow infers a
        # different struct per batch and the table's schema drifts between syncs.
        with patch(
            _FETCH_DATA,
            new=_fetch_data_returning(
                {f"/crm/pipelines/2026-03/{o}": [PIPELINE_PAYLOAD] for o in PIPELINE_OBJECT_TYPES}
            ),
        ):
            rows = _call(get_pipeline_stages_rows)

        assert json.loads(rows[0]["metadata"]) == {"isClosed": "false", "probability": "0.2"}

    @pytest.mark.parametrize(
        "fetcher,path,payload",
        [
            (get_owners_rows, "/crm/owners/2026-03", {"id": "1", "email": "rep@example.com"}),
            (get_properties_rows, "/crm/properties/2026-03/deals", {"name": "amount", "label": "Amount"}),
        ],
    )
    def test_missing_optional_fields_are_backfilled(self, fetcher: Any, path: str, payload: dict[str, Any]) -> None:
        # A portal that never sets an optional field would otherwise produce a narrower table than
        # one that does, and the column would appear or vanish between syncs.
        with patch(_FETCH_DATA, new=_fetch_data_returning({path: [[payload]]})):
            rows = _call(fetcher)

        table = "owners" if fetcher is get_owners_rows else "properties"
        assert set(rows[0]) >= set(HUBSPOT_METADATA_ENDPOINTS[table].columns)

    def test_owners_uses_the_pinned_date_version_path(self) -> None:
        # "/crm/v3/owners" has no path segment after the resource, so a version rewrite that only
        # matches "/crm/v3/<resource>/" would silently leave owners on the legacy path.
        captured: list[str] = []

        def _fake(path: str, *_args: Any, **_kwargs: Any) -> Iterator[list[dict[str, Any]]]:
            captured.append(path)
            yield []

        with patch(_FETCH_DATA, new=_fake):
            _call(get_owners_rows)

        assert captured == ["/crm/owners/2026-03"]

    def test_properties_skips_an_object_type_the_portal_cannot_read(self) -> None:
        # Property definitions are fanned out over every object endpoint, several of which need a
        # scope the connection may not hold. One 403 must not take the whole table down.
        response = MagicMock()
        response.status_code = 403

        def _fake(path: str, *_args: Any, **_kwargs: Any) -> Iterator[list[dict[str, Any]]]:
            if path == "/crm/properties/2026-03/deals":
                yield [{"name": "amount"}]
                return
            raise HTTPError("403 Client Error", response=response)

        with patch(_FETCH_DATA, new=_fake):
            rows = _call(get_properties_rows)

        assert [r["name"] for r in rows] == ["amount"]

    def test_server_error_still_fails_the_table(self) -> None:
        response = MagicMock()
        response.status_code = 500

        def _fake(*_args: Any, **_kwargs: Any) -> Iterator[list[dict[str, Any]]]:
            if response.status_code:
                raise HTTPError("500 Server Error", response=response)
            yield []

        with patch(_FETCH_DATA, new=_fake), pytest.raises(HTTPError):
            _call(get_owners_rows)

    def test_every_lookup_endpoint_has_a_fetcher(self) -> None:
        assert set(METADATA_FETCHERS) == set(HUBSPOT_METADATA_ENDPOINTS)
