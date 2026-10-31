from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.grafanairm import (
    GrafanaIRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.grafana_irm import (
    GrafanaIRMConfigError,
    GrafanaIRMResumeConfig,
    normalize_oncall_api_url,
    normalize_stack_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.source import GrafanaIRMSource

TOKEN = "glsa_test_token"
STACK_URL = "https://acme.grafana.net"
ONCALL_URL = "https://oncall-prod-us-central-0.grafana.net/oncall"
INCIDENT_PATH = "/api/plugins/grafana-irm-app/resources/api/v1/IncidentsService.QueryIncidentPreviews"
ACTIVITY_PATH = "/api/plugins/grafana-irm-app/resources/api/v1/ActivityService.QueryActivity"
MEMBERSHIP_PATH = "/api/plugins/grafana-irm-app/resources/api/v1/IncidentsService.GetIncidentMembership"


def _driver() -> SourceDriver:
    return SourceDriver(
        GrafanaIRMSource(),
        GrafanaIRMSourceConfig(
            token=TOKEN,
            stack_url=STACK_URL,
            oncall_api_url=ONCALL_URL,
        ),
    )


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
def test_oncall_pagination_stops_at_total_pages_and_resumes(resume_page: Optional[int]) -> None:
    pages = [1, 2] if resume_page is None else [resume_page]
    # Past the last page the API answers with the last page again, so any third request would loop.
    result = _driver().run(
        "shift_swaps",
        [ScriptedResponse(json=_oncall_page([{"id": f"SS{page}"}], page, total_pages=2)) for page in pages],
        resume_state=GrafanaIRMResumeConfig(page=resume_page) if resume_page else None,
    )

    assert result.raised is None
    assert result.rows == [{"id": f"SS{page}"} for page in pages]
    assert result.paths == ["/oncall/api/v1/shift_swaps/"] * len(pages)
    assert result.params("page") == [str(page) for page in pages]
    for request in result.requests:
        assert request.param("perpage") == "100"
        assert request.param("starting_after") == "1970-01-01T00:00:00Z"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["x-grafana-url"] == STACK_URL
    if resume_page is None:
        assert result.saved_states == [GrafanaIRMResumeConfig(page=2)]
    assert result.response is not None
    assert result.response.primary_keys == ["id"]
    assert result.response.partition_keys == ["created_at"]


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
def test_credential_like_fields_are_dropped(endpoint: str, row: dict[str, Any], dropped: tuple[str, ...]) -> None:
    result = _driver().run(endpoint, [ScriptedResponse(json=_oncall_page([row], 1, total_pages=1))])

    assert result.raised is None
    assert result.paths == [f"/oncall/api/v1/{endpoint}/"]
    assert len(result.rows) == 1
    assert not set(dropped) & result.rows[0].keys()
    assert result.rows[0]["id"] == row["id"]


@pytest.mark.parametrize("resume_cursor", [None, "cursor-resumed"])
def test_incident_cursor_travels_in_the_post_body(resume_cursor: Optional[str]) -> None:
    result = _driver().run(
        "incidents",
        [
            ScriptedResponse(
                json={"incidentPreviews": [{"incidentID": "1"}], "cursor": {"nextValue": "cursor-2", "hasMore": True}}
            ),
            ScriptedResponse(
                json={"incidentPreviews": [{"incidentID": "2"}], "cursor": {"nextValue": "", "hasMore": False}}
            ),
        ],
        resume_state=GrafanaIRMResumeConfig(cursor=resume_cursor) if resume_cursor else None,
    )

    assert result.raised is None
    assert result.rows == [{"incidentID": "1"}, {"incidentID": "2"}]
    assert result.paths == [INCIDENT_PATH] * 2
    first, second = (request.json() for request in result.requests)
    assert first.get("cursor") == ({"nextValue": resume_cursor, "hasMore": True} if resume_cursor else None)
    assert second["cursor"] == {"nextValue": "cursor-2", "hasMore": True}
    assert first["query"] == second["query"] == {"limit": 50, "orderField": "createdTime", "orderDirection": "ASC"}
    assert result.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert result.saved_states == [GrafanaIRMResumeConfig(cursor="cursor-2")]
    assert result.response is not None
    assert result.response.primary_keys == ["incidentID"]


def test_incident_activity_fans_out_over_every_incident() -> None:
    result = _driver().run(
        "incident_activity",
        [
            ScriptedResponse(
                json={"incidentPreviews": [{"incidentID": "1"}, {"incidentID": "2"}], "cursor": {"hasMore": False}}
            ),
            ScriptedResponse(
                json={
                    "activityItems": [{"incidentID": "1", "activityItemID": "a"}],
                    "cursor": {"nextValue": "c", "hasMore": True},
                }
            ),
            ScriptedResponse(
                json={"activityItems": [{"incidentID": "1", "activityItemID": "b"}], "cursor": {"hasMore": False}}
            ),
            ScriptedResponse(json={"activityItems": [], "cursor": {"hasMore": False}}),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {"incidentID": "1", "activityItemID": "a"},
        {"incidentID": "1", "activityItemID": "b"},
    ]
    assert result.paths == [INCIDENT_PATH, ACTIVITY_PATH, ACTIVITY_PATH, ACTIVITY_PATH]
    activity_bodies = [request.json() for request in result.requests if request.path == ACTIVITY_PATH]
    assert [(body["query"]["incidentID"], body.get("cursor")) for body in activity_bodies] == [
        ("1", None),
        ("1", {"nextValue": "c", "hasMore": True}),
        ("2", None),
    ]
    assert result.response is not None
    assert result.response.primary_keys == ["incidentID", "activityItemID"]


def test_alerts_fan_out_over_every_alert_group() -> None:
    result = _driver().run(
        "alerts",
        [
            ScriptedResponse(json=_oncall_page([{"id": "IG1"}], 1, total_pages=2)),
            ScriptedResponse(json=_oncall_page([{"id": "AL1", "alert_group_id": "IG1"}], 1, total_pages=2)),
            ScriptedResponse(json=_oncall_page([{"id": "AL2", "alert_group_id": "IG1"}], 2, total_pages=2)),
            ScriptedResponse(json=_oncall_page([{"id": "IG2"}, {"title": "no id"}], 2, total_pages=2)),
            ScriptedResponse(json=_oncall_page([], 1, total_pages=1)),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "AL1", "alert_group_id": "IG1"}, {"id": "AL2", "alert_group_id": "IG1"}]
    assert [(request.path, request.param("alert_group_id"), request.param("page")) for request in result.requests] == [
        ("/oncall/api/v1/alert_groups/", None, "1"),
        ("/oncall/api/v1/alerts/", "IG1", "1"),
        ("/oncall/api/v1/alerts/", "IG1", "2"),
        ("/oncall/api/v1/alert_groups/", None, "2"),
        ("/oncall/api/v1/alerts/", "IG2", "1"),
    ]
    for request in result.requests:
        assert request.param("perpage") == "100"
        assert request.headers["x-grafana-url"] == STACK_URL
    assert result.response is not None
    assert result.response.primary_keys == ["id"]
    assert result.response.partition_keys == ["created_at"]


def test_incident_membership_lifts_ids_onto_each_assignment() -> None:
    commander = {"roleID": 1, "name": "commander"}
    result = _driver().run(
        "incident_membership",
        [
            ScriptedResponse(
                json={"incidentPreviews": [{"incidentID": "1"}, {"incidentID": "2"}], "cursor": {"hasMore": False}}
            ),
            ScriptedResponse(
                json={
                    "assignments": [
                        {"role": commander, "roleID": 1, "user": {"userID": "user-a", "name": "Ada"}},
                        {"role": commander, "roleID": 1, "user": None},
                        {"roleID": 2, "user": {"userID": "user-b"}},
                    ],
                    "error": "",
                }
            ),
            ScriptedResponse(json={"assignments": None, "error": ""}),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {
            "role": commander,
            "roleID": 1,
            "user": {"userID": "user-a", "name": "Ada"},
            "incidentID": "1",
            "userID": "user-a",
        },
        {"roleID": 2, "user": {"userID": "user-b"}, "incidentID": "1", "userID": "user-b"},
    ]
    assert result.paths == [INCIDENT_PATH, MEMBERSHIP_PATH, MEMBERSHIP_PATH]
    assert [request.json() for request in result.requests[1:]] == [{"incidentID": "1"}, {"incidentID": "2"}]
    assert result.response is not None
    assert result.response.primary_keys == ["incidentID", "roleID", "userID"]


@pytest.mark.parametrize(
    ("endpoint", "path", "body", "primary_key"),
    [
        ("incident_roles", "RolesService.GetRoles", {"roles": [{"roleID": 1}, {"roleID": 2}]}, "roleID"),
        ("incident_custom_fields", "FieldsService.GetFields", {"fields": [{"uuid": "f-1"}, {"uuid": "f-2"}]}, "uuid"),
    ],
)
def test_incident_lookup_tables_are_one_unfiltered_request(
    endpoint: str, path: str, body: dict[str, Any], primary_key: str
) -> None:
    result = _driver().run(endpoint, [ScriptedResponse(json={**body, "error": ""})])

    assert result.raised is None
    assert result.rows == next(iter(body.values()))
    assert result.paths == [f"/api/plugins/grafana-irm-app/resources/api/v1/{path}"]
    assert result.requests[0].method == "POST"
    assert result.requests[0].json() == {}
    assert result.response is not None
    assert result.response.primary_keys == [primary_key]


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
        (200, None, "alerts", True, None),
        (403, None, "alerts", False, "permission"),
        (None, 403, "incidents", False, "permission"),
        (500, 200, None, False, "HTTP 500"),
    ],
)
def test_validate_credentials_maps_statuses(
    oncall_status: Optional[int],
    incident_status: Optional[int],
    schema_name: Optional[str],
    expected_ok: bool,
    message_part: Optional[str],
) -> None:
    script: list[ScriptedResponse] = []
    if oncall_status is not None:
        script.append(ScriptedResponse(status=oncall_status, json={}))
    if incident_status is not None:
        script.append(ScriptedResponse(status=incident_status, json={}))

    with scripted_network(always(ScriptedResponse(status=500)) if oncall_status == 500 else script) as network:
        ok, message = validate_credentials(TOKEN, STACK_URL, ONCALL_URL, schema_name)

    assert ok is expected_ok
    assert network.session_options == [{"redact_values": (TOKEN,)}]
    expected_requests = []
    if schema_name != "incidents":
        expected_requests.append(("GET", "/oncall/api/v1/alert_groups/"))
    if schema_name == "incidents" or (schema_name is None and oncall_status in (200, 403)):
        expected_requests.append(("POST", INCIDENT_PATH))
    requests = [(request.method, request.path) for request in network.requests_log]
    if oncall_status == 500:
        assert set(requests) == {("GET", "/oncall/api/v1/alert_groups/")}
        assert len(requests) > 1
    else:
        assert requests == expected_requests
    if message_part is None:
        assert message is None
    else:
        assert message is not None and message_part in message
