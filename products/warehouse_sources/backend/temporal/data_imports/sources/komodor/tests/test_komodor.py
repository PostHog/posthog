import json
import time
from collections.abc import Iterable, Iterator
from http.client import responses as status_reasons
from typing import Any, Literal, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response, Session
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.komodor import (
    KomodorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.komodor import (
    KomodorResumeConfig,
    komodor_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.settings import (
    SEARCH_INCREMENTAL_OVERLAP_SECONDS,
    SEARCH_RETENTION_MARGIN_SECONDS,
    SEARCH_RETENTION_SECONDS,
    SEARCH_WINDOW_SECONDS,
    WINDOWED_SEARCHES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.source import KomodorSource


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = status_reasons[status]
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    with Session() as session:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
                return_value=session,
            ),
            patch.object(session, "send") as send,
        ):
            yield send


def manager(cursor: str | int | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = cursor is not None
    result.load_state.return_value = KomodorResumeConfig(cursor=cursor) if cursor is not None else None
    return result


def source_items(source: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], source.items())


def driver(config: KomodorSourceConfig | None = None) -> SourceDriver:
    return SourceDriver(KomodorSource(), config or KomodorSourceConfig(api_key="test-key", region="us"))


@pytest.mark.parametrize(
    ("table", "cursor_field", "body_field", "cursor"),
    [("services", "token", "token", "next-service"), ("jobs", "nextPage", "page", 2)],
)
@pytest.mark.parametrize("region", ["us", "eu"])
def test_pagination_auth_and_checkpoint(
    transport: MagicMock,
    table: str,
    cursor_field: str,
    body_field: str,
    cursor: str | int,
    region: Literal["us", "eu"],
) -> None:
    transport.side_effect = [
        response({"data": {table: [{"name": "first"}]}, "meta": {cursor_field: cursor}}),
        response({"data": {table: [{"name": "last"}]}, "meta": {"pageSize": 100}}),
    ]
    resume = manager()
    source = komodor_source(KomodorSourceConfig(api_key="test-key", region=region), table, 1, "test", "v2", resume)
    pages = iter(cast(Iterator[list[dict[str, Any]]], source_items(source)))
    assert next(pages) == [{"name": "first"}]
    assert list(pages) == [[{"name": "last"}]]
    assert transport.call_count == 2
    assert all(call.kwargs["allow_redirects"] is False for call in transport.call_args_list)
    assert all(call.kwargs["timeout"] == (10, 60) for call in transport.call_args_list)
    resume.save_state.assert_called_once_with(KomodorResumeConfig(cursor=cursor))
    first, second = [call.args[0] for call in transport.call_args_list]
    host = "api.komodor.com" if region == "us" else "api.eu.komodor.com"
    assert first.url == second.url == f"https://{host}/api/v2/{table}/search"
    assert first.method == second.method == "POST"
    assert first.headers["X-API-KEY"] == second.headers["X-API-KEY"] == "test-key"
    assert json.loads(first.body) == {"pagination": {"pageSize": 100}}
    assert json.loads(second.body) == {"pagination": {"pageSize": 100, body_field: cursor}}


@pytest.mark.parametrize(
    ("table", "body_field", "cursor"), [("services", "token", "saved-service"), ("jobs", "page", 7)]
)
@pytest.mark.parametrize("terminal_meta", [{}, {"token": None, "nextPage": None}, {"token": "", "nextPage": 0}])
def test_resume_and_empty_terminal_page(
    table: str, body_field: str, cursor: str | int, terminal_meta: dict[str, Any]
) -> None:
    result = driver().run(
        table,
        [ScriptedResponse(json={"data": {table: []}, "meta": terminal_meta})],
        resume_state=KomodorResumeConfig(cursor=cursor),
    )
    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 1
    assert result.requests[0].json() == {"pagination": {"pageSize": 100, body_field: cursor}}
    assert result.saved_states == []


@pytest.mark.parametrize("rows", [[], [{"service": "example"}]])
def test_credential_probe_is_one_small_request(transport: MagicMock, rows: list[dict[str, str]]) -> None:
    transport.return_value = response({"data": {"services": rows}, "meta": {"token": "more-services"}})
    assert validate_credentials(KomodorSourceConfig(api_key="test-key", region="eu"), "v2") == (True, None)
    transport.assert_called_once()
    request = transport.call_args.args[0]
    assert transport.call_args.kwargs["allow_redirects"] is False
    assert transport.call_args.kwargs["timeout"] == (10, 60)
    assert request.url == "https://api.eu.komodor.com/api/v2/services/search"
    assert request.headers["X-API-KEY"] == "test-key"
    assert json.loads(request.body) == {"pagination": {"pageSize": 1}}


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_terminal(status: int) -> None:
    config = KomodorSourceConfig(api_key="test-key", region="us")
    answer = ScriptedResponse(status=status, json={"Status": "Forbidden"})
    with scripted_network([answer]) as network:
        valid, message = validate_credentials(config, "v2")
    assert not valid
    assert message is not None and "API key" in message and "region" in message
    assert len(network.requests_log) == 1
    result = driver(config).run("services", [answer])
    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    matches = [
        text for pattern, text in KomodorSource().get_non_retryable_errors().items() if pattern in str(result.raised)
    ]
    assert matches == [message]


def test_other_client_errors_propagate() -> None:
    with scripted_network([ScriptedResponse(status=400, json={"error": "bad_request"})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials(KomodorSourceConfig(api_key="test-key", region="us"), "v2")
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("region", ["", "https://example.com", "US"])
def test_invalid_region_never_sends_credentials(region: str) -> None:
    config = KomodorSourceConfig(api_key="test-key", region=cast(Any, region))
    with scripted_network([]) as network:
        assert validate_credentials(config, "v2") == (False, "Select a valid Komodor region: US or EU.")
    assert network.requests_log == []
    result = driver(config).run("clusters", [])
    assert isinstance(result.raised, ValueError)
    assert "Select a valid Komodor region" in str(result.raised)
    assert result.requests == []


@pytest.mark.parametrize(("table", "cursor_field", "cursor"), [("services", "token", "same"), ("jobs", "nextPage", 2)])
def test_repeated_resume_cursor_fails(table: str, cursor_field: str, cursor: str | int) -> None:
    result = driver().run(
        table,
        [ScriptedResponse(json={"data": {table: [{"name": "example"}]}, "meta": {cursor_field: cursor}})],
        resume_state=KomodorResumeConfig(cursor=cursor),
    )
    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert len(result.requests) == 1


ENDPOINT_PATHS = {"cluster_issues": "clusters/issues/search", "k8s_events": "clusters/k8s-events/search"}
SEARCHES = [
    ("cluster_issues", "issues", "nextPage", "page", 2),
    ("k8s_events", "events", "token", "token", "next-event"),
]


def search_script(collection: str, cursor_field: str, cursor: str | int, pages: dict[tuple[str, int], list[dict]]):
    def answer(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/clusters"):
            return ScriptedResponse(json={"data": {"clusters": [{"name": "b"}, {"name": "a"}]}})
        body = request.json()
        props = body["props"]
        if body["scope"]["cluster"] != "a":
            return ScriptedResponse(json={"data": {collection: []}, "meta": {}})
        if body["pagination"].get("token" if cursor_field == "token" else "page") is None:
            rows = pages.get((props["type"], props["fromEpoch"]), [])
            meta = {cursor_field: cursor} if rows else {}
        else:
            rows, meta = pages.get(("next", props["fromEpoch"]), []), {}
        return ScriptedResponse(json={"data": {collection: rows}, "meta": meta})

    return answer


@pytest.mark.parametrize(("table", "collection", "cursor_field", "body_field", "cursor"), SEARCHES)
def test_windowed_search_walks_clusters_types_windows_and_pages(
    table: str, collection: str, cursor_field: str, body_field: str, cursor: str | int
) -> None:
    search = WINDOWED_SEARCHES[table]
    first_type = search.types[0]
    start = int(time.time()) - 3 * 24 * 60 * 60
    repeated = {"type": first_type, "startTime": start + 5, "link": "https://app.komodor.com/x"}
    script = search_script(
        collection,
        cursor_field,
        cursor,
        {
            (first_type, start): [repeated],
            ("next", start): [{"type": first_type, "startTime": start + 6, "link": "https://app.komodor.com/y"}],
            (first_type, start + SEARCH_WINDOW_SECONDS): [repeated],
        },
    )
    until = start + SEARCH_WINDOW_SECONDS + 100
    result = driver().run(table, script, resume_state=KomodorResumeConfig(start=start, until=until))

    assert result.raised is None
    assert result.rows == [
        {**repeated, "cluster": "a"},
        {"type": first_type, "startTime": start + 6, "link": "https://app.komodor.com/y", "cluster": "a"},
    ]
    searches = [request.json() for request in result.requests[1:]]
    assert len(searches) == 2 * len(search.types) * 2 + 2
    assert searches[:3] == [
        {
            "scope": {"cluster": "a"},
            "props": {
                "type": first_type,
                "fromEpoch": start,
                "toEpoch": start + SEARCH_WINDOW_SECONDS - 1,
                **({"statuses": list(search.statuses)} if search.statuses else {}),
            },
            "pagination": {"pageSize": 100, **extra},
        }
        for extra in ({}, {body_field: cursor})
    ] + [
        {
            "scope": {"cluster": "a"},
            "props": {
                "type": first_type,
                "fromEpoch": start + SEARCH_WINDOW_SECONDS,
                "toEpoch": until - 1,
                **({"statuses": list(search.statuses)} if search.statuses else {}),
            },
            "pagination": {"pageSize": 100},
        }
    ]
    assert [body["scope"]["cluster"] for body in searches[-len(search.types) * 2 :]] == ["b"] * len(search.types) * 2
    assert result.committed_states[1:3] == [
        KomodorResumeConfig(
            cursor=cursor, cluster="a", search_type=first_type, window_start=start, start=start, until=until
        ),
        KomodorResumeConfig(
            cluster="a", search_type=first_type, window_start=start + SEARCH_WINDOW_SECONDS, start=start, until=until
        ),
    ]


@pytest.mark.parametrize(("table", "collection", "cursor_field", "body_field", "cursor"), SEARCHES)
def test_windowed_search_resumes_at_the_saved_cluster_type_window_and_cursor(
    table: str, collection: str, cursor_field: str, body_field: str, cursor: str | int
) -> None:
    search = WINDOWED_SEARCHES[table]
    start = int(time.time()) - 3 * 24 * 60 * 60
    state = KomodorResumeConfig(
        cursor=cursor,
        cluster="b",
        search_type=search.types[-1],
        window_start=start + SEARCH_WINDOW_SECONDS,
        start=start,
        until=start + SEARCH_WINDOW_SECONDS + 100,
    )
    result = driver().run(table, search_script(collection, cursor_field, cursor, {}), resume_state=state)

    assert result.raised is None
    assert [request.path for request in result.requests] == ["/api/v2/clusters", f"/api/v2/{ENDPOINT_PATHS[table]}"]
    body = result.requests[1].json()
    assert body["scope"] == {"cluster": "b"}
    assert (body["props"]["type"], body["props"]["fromEpoch"]) == (search.types[-1], start + SEARCH_WINDOW_SECONDS)
    assert body["pagination"] == {"pageSize": 100, body_field: cursor}


@pytest.mark.parametrize("table", WINDOWED_SEARCHES)
@pytest.mark.parametrize("last_value_age", [None, 3600])
def test_windowed_search_reads_retention_or_from_the_watermark_in_two_day_windows(
    table: str, last_value_age: int | None
) -> None:
    now = int(time.time())
    last_value = None if last_value_age is None else now - last_value_age
    result = driver().run(
        table,
        lambda request: ScriptedResponse(
            json={"data": {"clusters": [{"name": "a"}]}}
            if request.path.endswith("/clusters")
            else {"data": {"issues": [], "events": []}, "meta": {}}
        ),
        incremental_field="startTime",
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    windows = sorted({(r.json()["props"]["fromEpoch"], r.json()["props"]["toEpoch"]) for r in result.requests[1:]})
    expected_start = (
        now - SEARCH_RETENTION_SECONDS + SEARCH_RETENTION_MARGIN_SECONDS
        if last_value is None
        else last_value - SEARCH_INCREMENTAL_OVERLAP_SECONDS
    )
    assert abs(windows[0][0] - expected_start) <= 5
    assert all(to - start < SEARCH_WINDOW_SECONDS for start, to in windows)
    assert all(later[0] == earlier[1] + 1 for earlier, later in zip(windows, windows[1:]))
    assert abs(windows[-1][1] - now) <= 5


def test_windowed_search_skips_and_clamps_windows_past_retention() -> None:
    now = int(time.time())
    start = now - SEARCH_RETENTION_SECONDS - SEARCH_WINDOW_SECONDS - 100
    result = driver().run(
        "k8s_events",
        lambda request: ScriptedResponse(
            json={"data": {"clusters": [{"name": "a"}]}}
            if request.path.endswith("/clusters")
            else {"data": {"events": []}, "meta": {}}
        ),
        resume_state=KomodorResumeConfig(start=start, until=now),
    )

    assert result.raised is None
    starts = sorted({request.json()["props"]["fromEpoch"] for request in result.requests[1:]})
    floor = now - SEARCH_RETENTION_SECONDS + SEARCH_RETENTION_MARGIN_SECONDS
    assert floor <= starts[0] <= floor + 5
    assert starts[1:] == [start + n * SEARCH_WINDOW_SECONDS for n in range(2, 5)]


def test_cost_allocation_stops_when_no_more_pages_despite_a_token() -> None:
    result = driver().run(
        "cost_allocation",
        [
            ScriptedResponse(
                json={"groupedCosts": [{"komodorServiceId": "s1"}], "paginationToken": "t1", "hasMorePages": True}
            ),
            ScriptedResponse(
                json={"groupedCosts": [{"komodorServiceId": "s2"}], "paginationToken": "t2", "hasMorePages": False}
            ),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"komodorServiceId": "s1"}, {"komodorServiceId": "s2"}]
    assert result.params("paginationToken") == [None, "t1"]
    assert result.params("timeFrame") == ["Past_30_days", "Past_30_days"]
    assert result.params("groupBy") == ["komodorServiceName", "komodorServiceName"]
    assert result.committed_states == [KomodorResumeConfig(cursor="t1")]
