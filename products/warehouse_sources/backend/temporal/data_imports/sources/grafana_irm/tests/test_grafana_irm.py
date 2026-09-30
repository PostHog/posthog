import json
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import responses

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.grafana_irm import (
    GrafanaIRMConfigError,
    GrafanaIRMResumeConfig,
    grafana_irm_source,
    normalize_oncall_api_url,
    normalize_stack_url,
    validate_credentials,
)

TOKEN = "glsa_test_token"
STACK_URL = "https://acme.grafana.net"
ONCALL_URL = "https://oncall-prod-us-central-0.grafana.net/oncall"
INCIDENT_BASE = f"{STACK_URL}/api/plugins/grafana-irm-app/resources/api/v1"


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as http:
        yield http


def _manager(resume: Optional[GrafanaIRMResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _source(endpoint: str, manager: MagicMock) -> Any:
    return grafana_irm_source(
        token=TOKEN,
        stack_url=STACK_URL,
        oncall_api_url=ONCALL_URL,
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _oncall_page(results: list[dict[str, Any]], page: int, total_pages: int) -> dict[str, Any]:
    return {
        "count": total_pages,
        "next": None,
        "previous": None,
        "results": results,
        "current_page_number": page,
        "page_size": 100,
        "total_pages": total_pages,
    }


def _body(call: Any) -> dict[str, Any]:
    return json.loads(call.request.body)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme.grafana.net", "https://acme.grafana.net"),
        ("https://ACME.grafana.net/a/grafana-irm-app/incidents", "https://acme.grafana.net"),
    ],
)
def test_normalize_stack_url(value: str, expected: str) -> None:
    assert normalize_stack_url(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("oncall-prod-us-central-0.grafana.net/oncall", ONCALL_URL),
        (f"{ONCALL_URL}/api/v1/", ONCALL_URL),
    ],
)
def test_normalize_oncall_api_url(value: str, expected: str) -> None:
    assert normalize_oncall_api_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://attacker.example.com",
        "https://grafana.net.attacker.example.com",
        "http://acme.grafana.net",
        "https://user:pass@acme.grafana.net",
        "https://acme.grafana.net:8443",
        # urlsplit keeps these characters in the hostname, but requests sends the request to `attacker.example`.
        "https://attacker.example\\.grafana.net",
        "https://attacker.example%2F.grafana.net",
    ],
)
def test_rejects_urls_outside_grafana_cloud(value: str) -> None:
    with pytest.raises(GrafanaIRMConfigError):
        normalize_stack_url(value)
    with pytest.raises(GrafanaIRMConfigError):
        normalize_oncall_api_url(value)
    ok, message = validate_credentials(TOKEN, value, ONCALL_URL)
    assert not ok and message


@pytest.mark.parametrize("resume_page", [None, 2])
def test_oncall_pagination_stops_at_total_pages_and_resumes(
    http: responses.RequestsMock, resume_page: Optional[int]
) -> None:
    url = f"{ONCALL_URL}/api/v1/shift_swaps/"
    pages = [1, 2] if resume_page is None else [resume_page]
    for page in pages:
        http.add(responses.GET, url, json=_oncall_page([{"id": f"SS{page}"}], page, total_pages=2))
    # Past the last page the API answers with the last page again, so any third request would loop.
    manager = _manager(GrafanaIRMResumeConfig(page=resume_page) if resume_page else None)

    result = _source("shift_swaps", manager)

    assert _rows(result) == [{"id": f"SS{page}"} for page in pages]
    assert [parse_qs(urlsplit(call.request.url).query)["page"] for call in http.calls] == [[str(p)] for p in pages]
    for call in http.calls:
        query = parse_qs(urlsplit(call.request.url).query)
        assert query["perpage"] == ["100"]
        assert query["starting_after"] == ["1970-01-01T00:00:00Z"]
        assert call.request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert call.request.headers["X-Grafana-URL"] == STACK_URL
    if resume_page is None:
        manager.save_state.assert_called_once_with(GrafanaIRMResumeConfig(page=2))
    assert result.primary_keys == ["id"]
    assert result.partition_keys == ["created_at"]


@pytest.mark.parametrize(
    ("endpoint", "row", "dropped"),
    [
        (
            "integrations",
            {"id": "C1", "name": "Grafana", "link": "https://secret", "inbound_email": "x@y"},
            ("link", "inbound_email"),
        ),
        (
            "schedules",
            {"id": "S1", "name": "Primary", "ical_url_primary": "https://cal/secret.ics", "ical_url_overrides": None},
            ("ical_url_primary", "ical_url_overrides"),
        ),
    ],
)
def test_credential_like_fields_are_dropped(
    http: responses.RequestsMock, endpoint: str, row: dict[str, Any], dropped: tuple[str, ...]
) -> None:
    http.add(responses.GET, f"{ONCALL_URL}/api/v1/{endpoint}/", json=_oncall_page([row], 1, total_pages=1))

    rows = _rows(_source(endpoint, _manager()))

    assert len(rows) == 1
    assert not set(dropped) & rows[0].keys()
    assert rows[0]["id"] == row["id"]


@pytest.mark.parametrize("resume_cursor", [None, "cursor-resumed"])
def test_incident_cursor_travels_in_the_post_body(http: responses.RequestsMock, resume_cursor: Optional[str]) -> None:
    url = f"{INCIDENT_BASE}/IncidentsService.QueryIncidentPreviews"
    http.add(
        responses.POST,
        url,
        json={"incidentPreviews": [{"incidentID": "1"}], "cursor": {"nextValue": "cursor-2", "hasMore": True}},
    )
    http.add(
        responses.POST,
        url,
        json={"incidentPreviews": [{"incidentID": "2"}], "cursor": {"nextValue": "", "hasMore": False}},
    )
    manager = _manager(GrafanaIRMResumeConfig(cursor=resume_cursor) if resume_cursor else None)

    result = _source("incidents", manager)

    assert _rows(result) == [{"incidentID": "1"}, {"incidentID": "2"}]
    first, second = (_body(call) for call in http.calls)
    assert first.get("cursor") == ({"nextValue": resume_cursor, "hasMore": True} if resume_cursor else None)
    assert second["cursor"] == {"nextValue": "cursor-2", "hasMore": True}
    assert first["query"] == second["query"] == {"limit": 50, "orderField": "createdTime", "orderDirection": "ASC"}
    assert http.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
    manager.save_state.assert_called_once_with(GrafanaIRMResumeConfig(cursor="cursor-2"))
    assert result.primary_keys == ["incidentID"]


def test_incident_activity_fans_out_over_every_incident(http: responses.RequestsMock) -> None:
    http.add(
        responses.POST,
        f"{INCIDENT_BASE}/IncidentsService.QueryIncidentPreviews",
        json={"incidentPreviews": [{"incidentID": "1"}, {"incidentID": "2"}], "cursor": {"hasMore": False}},
    )
    activity_url = f"{INCIDENT_BASE}/ActivityService.QueryActivity"
    http.add(
        responses.POST,
        activity_url,
        json={
            "activityItems": [{"incidentID": "1", "activityItemID": "a"}],
            "cursor": {"nextValue": "c", "hasMore": True},
        },
    )
    http.add(
        responses.POST,
        activity_url,
        json={"activityItems": [{"incidentID": "1", "activityItemID": "b"}], "cursor": {"hasMore": False}},
    )
    http.add(responses.POST, activity_url, json={"activityItems": [], "cursor": {"hasMore": False}})

    result = _source("incident_activity", _manager())

    assert _rows(result) == [
        {"incidentID": "1", "activityItemID": "a"},
        {"incidentID": "1", "activityItemID": "b"},
    ]
    activity_bodies = [_body(call) for call in http.calls if call.request.url == activity_url]
    assert [(body["query"]["incidentID"], body.get("cursor")) for body in activity_bodies] == [
        ("1", None),
        ("1", {"nextValue": "c", "hasMore": True}),
        ("2", None),
    ]
    assert result.primary_keys == ["incidentID", "activityItemID"]


@pytest.mark.parametrize(
    ("oncall_status", "incident_status", "schema_name", "expected_ok", "message_part"),
    [
        (200, 200, None, True, None),
        (403, 403, None, True, None),
        (401, 200, None, False, "rejected the token"),
        (200, 401, None, False, "rejected the token"),
        (404, 200, None, False, "Admin & API"),
        (200, 404, None, False, "isn't enabled"),
        (403, None, "alert_groups", False, "permission"),
        (None, 403, "incidents", False, "permission"),
        (500, 200, None, False, "HTTP 500"),
    ],
)
def test_validate_credentials_maps_statuses(
    http: responses.RequestsMock,
    oncall_status: Optional[int],
    incident_status: Optional[int],
    schema_name: Optional[str],
    expected_ok: bool,
    message_part: Optional[str],
) -> None:
    http.assert_all_requests_are_fired = False
    if oncall_status is not None:
        http.add(responses.GET, f"{ONCALL_URL}/api/v1/alert_groups/", status=oncall_status, json={})
    if incident_status is not None:
        http.add(
            responses.POST,
            f"{INCIDENT_BASE}/IncidentsService.QueryIncidentPreviews",
            status=incident_status,
            json={},
        )

    ok, message = validate_credentials(TOKEN, STACK_URL, ONCALL_URL, schema_name)

    assert ok is expected_ok
    if message_part is None:
        assert message is None
    else:
        assert message is not None and message_part in message
