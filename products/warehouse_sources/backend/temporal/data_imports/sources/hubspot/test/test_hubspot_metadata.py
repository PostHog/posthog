from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

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
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.scopes import HubspotForbiddenError
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
    HUBSPOT_API_VERSION_2026_03,
    HUBSPOT_METADATA_ENDPOINTS,
)

_FETCH_DATA = "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.metadata.fetch_data"
_SESSION = "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers.make_tracked_session"

PROPERTIES_PREFIX = "/crm/properties/2026-03"
PIPELINES_PREFIX = "/crm/pipelines/2026-03"

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


def _patch_session(forbidden: set[str], rows_by_path: dict[str, list[dict[str, Any]]]) -> Any:
    # Patched at the HTTP boundary rather than at `fetch_data`, so the real status handling maps a
    # 403 to the exception the fetchers have to cope with.
    def _get(url: str, headers: Any = None, params: Any = None, timeout: Any = None) -> MagicMock:  # noqa: ARG001
        path = urlsplit(url).path
        response = MagicMock()
        response.status_code = 403 if path in forbidden else 200
        response.json.return_value = {"results": rows_by_path.get(path, [])}
        return response

    session = type("_S", (), {"get": staticmethod(_get)})()
    return patch(_SESSION, new=lambda *_a, **_k: session)


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

    @pytest.mark.parametrize(
        "fetcher,prefix,payload,forbidden_type,readable_type",
        [
            (get_properties_rows, PROPERTIES_PREFIX, [{"name": "amount"}], "feedback_submissions", "deals"),
            (get_properties_rows, PROPERTIES_PREFIX, [{"name": "amount"}], "leads", "deals"),
            (get_pipelines_rows, PIPELINES_PREFIX, PIPELINE_PAYLOAD, "tickets", "deals"),
            (get_pipeline_stages_rows, PIPELINES_PREFIX, PIPELINE_PAYLOAD, "tickets", "deals"),
        ],
    )
    def test_a_fan_out_skips_an_object_type_the_grant_cannot_read(
        self,
        fetcher: Any,
        prefix: str,
        payload: list[dict[str, Any]],
        forbidden_type: str,
        readable_type: str,
    ) -> None:
        # These tables are fanned out over every object endpoint, several of which need a scope the
        # connection may not hold. "leads" is the scope-gated flavor, which raises a subclass.
        with _patch_session({f"{prefix}/{forbidden_type}"}, {f"{prefix}/{readable_type}": payload}):
            rows = _call(fetcher)

        assert {r["object_type"] for r in rows} == {readable_type}

    def test_owners_fails_the_table_when_the_grant_cannot_read_it(self) -> None:
        with _patch_session({"/crm/owners/2026-03"}, {}), pytest.raises(HubspotForbiddenError):
            _call(get_owners_rows)

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
