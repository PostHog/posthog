from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.hubspot.metadata import (
    get_conversation_threads_rows,
    get_marketing_campaigns_rows,
    get_owners_rows,
    get_pipeline_stages_rows,
    get_pipelines_rows,
    get_properties_rows,
    get_teams_rows,
)
from products.warehouse_sources.sources.hubspot.scopes import HubspotForbiddenError
from products.warehouse_sources.sources.hubspot.settings import (
    CAMPAIGN_PROPERTIES,
    HUBSPOT_API_VERSION_2026_03,
    HUBSPOT_API_VERSION_2026_09,
    HUBSPOT_API_VERSION_V3,
    HUBSPOT_METADATA_ENDPOINTS,
)

_FETCH_DATA = "products.warehouse_sources.sources.hubspot.metadata.fetch_data"
_SESSION = "products.warehouse_sources.sources.hubspot.helpers.make_tracked_session"

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


def _call(fetcher: Any, api_version: str = HUBSPOT_API_VERSION_2026_03) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in fetcher(
        api_key="key",
        refresh_token="refresh",
        logger=MagicMock(),
        source_id="source-1",
        api_version=api_version,
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

    @pytest.mark.parametrize(
        "fetcher,api_version,path,params",
        [
            (
                get_conversation_threads_rows,
                HUBSPOT_API_VERSION_2026_09,
                "/conversations/conversations/2026-09/threads",
                {"limit": 100, "association": "TICKET"},
            ),
            # The Conversations API has no 2026-03 release, so that pin reads the v3 path.
            (
                get_conversation_threads_rows,
                HUBSPOT_API_VERSION_2026_03,
                "/conversations/v3/conversations/threads",
                {"limit": 100, "association": "TICKET"},
            ),
            # The 2026-09 Campaigns release is a public beta, so that pin reads the stable 2026-03 one.
            (
                get_marketing_campaigns_rows,
                HUBSPOT_API_VERSION_2026_09,
                "/marketing/campaigns/2026-03",
                {"limit": 100, "properties": ",".join(CAMPAIGN_PROPERTIES)},
            ),
            (
                get_marketing_campaigns_rows,
                HUBSPOT_API_VERSION_V3,
                "/marketing/v3/campaigns",
                {"limit": 100, "properties": ",".join(CAMPAIGN_PROPERTIES)},
            ),
        ],
    )
    def test_pages_by_after_cursor(self, fetcher: Any, api_version: str, path: str, params: dict[str, Any]) -> None:
        # These APIs document `paging.next.link` as optional or relative, so paging must not depend on it.
        pages = {
            None: {"results": [{"id": "1"}], "paging": {"next": {"after": "c1", "link": "?after=c1"}}},
            "c1": {"results": [{"id": "2"}]},
        }
        requests: list[tuple[str, dict[str, Any] | None]] = []

        def _get(url: str, headers: Any = None, params: Any = None, timeout: Any = None) -> MagicMock:  # noqa: ARG001
            requests.append((urlsplit(url).path, params))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = pages[(params or {}).get("after")]
            return response

        session = type("_S", (), {"get": staticmethod(_get)})()
        with patch(_SESSION, new=lambda *_a, **_k: session):
            rows = _call(fetcher, api_version)

        assert requests == [(path, params), (path, {**params, "after": "c1"})]
        assert [r["id"] for r in rows] == ["1", "2"]

    def test_conversation_threads_keeps_thread_associations(self) -> None:
        payload = {"id": "2", "status": "CLOSED", "threadAssociations": {"associatedTicketId": "9"}}
        with patch(_FETCH_DATA, new=_fetch_data_returning({"/conversations/v3/conversations/threads": [[payload]]})):
            rows = _call(get_conversation_threads_rows)

        assert rows[0]["threadAssociations"] == '{"associatedTicketId": "9"}'
        assert set(rows[0]) >= set(HUBSPOT_METADATA_ENDPOINTS["conversation_threads"].columns)

    @pytest.mark.parametrize(
        "api_version,path",
        [
            (HUBSPOT_API_VERSION_V3, "/settings/v3/users/teams"),
            (HUBSPOT_API_VERSION_2026_03, "/settings/users/2026-03/teams"),
            # The 2026-09 User Provisioning release is a public beta, so that pin reads 2026-03.
            (HUBSPOT_API_VERSION_2026_09, "/settings/users/2026-03/teams"),
        ],
    )
    def test_teams_reads_the_stable_route_and_encodes_members(self, api_version: str, path: str) -> None:
        payload = {"id": "7", "name": "Sales EMEA", "userIds": ["101", "102"]}
        with patch(_FETCH_DATA, new=_fetch_data_returning({path: [[payload]]})):
            rows = _call(get_teams_rows, api_version)

        assert rows == [{"id": "7", "name": "Sales EMEA", "userIds": '["101", "102"]', "secondaryUserIds": None}]

    def test_marketing_campaigns_lifts_properties_and_keeps_the_envelope(self) -> None:
        payload = {
            "id": "a1b2c3d4-0000-4000-8000-000000000001",
            "createdAt": "2026-01-02T03:04:05Z",
            "updatedAt": "2026-02-03T04:05:06Z",
            "businessUnits": [{"id": 0}],
            "properties": {"hs_name": "Spring launch", "hs_campaign_status": "active"},
        }
        with patch(_SESSION) as session:
            session.return_value.get.return_value = MagicMock(
                status_code=200, json=MagicMock(return_value={"results": [payload]})
            )
            rows = _call(get_marketing_campaigns_rows)

        row = rows[0]
        assert row["id"] == payload["id"]
        assert row["createdAt"] == "2026-01-02T03:04:05Z"
        assert row["updatedAt"] == "2026-02-03T04:05:06Z"
        assert row["businessUnits"] == '[{"id": 0}]'
        assert row["hs_name"] == "Spring launch"
        assert row["hs_end_date"] is None
        assert "properties" not in row
        assert set(row) == set(HUBSPOT_METADATA_ENDPOINTS["marketing_campaigns"].columns)

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
