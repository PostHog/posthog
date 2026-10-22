from typing import Any

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitix import (
    HumanitixSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix import (
    PAGE_SIZE,
    HumanitixResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source import HumanitixSource


def _driver() -> SourceDriver:
    return SourceDriver(HumanitixSource(), HumanitixSourceConfig(api_key="hmtx-key"))


def _rows(id_prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"_id": f"{id_prefix}-{i}"} for i in range(count)]


def _page(
    items: list[dict[str, Any]] | None,
    *,
    total: int | None = None,
    list_key: str = "events",
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {"page": 1, "pageSize": PAGE_SIZE}
    if total is not None:
        body["total"] = total
    if not drop_key:
        body[list_key] = items or []
    return ScriptedResponse(json=body)


class TestPagination:
    def test_stops_on_full_page_that_reaches_total(self) -> None:
        # A single full page whose length equals total must terminate without fetching page 2.
        result = _driver().run("events", [_page(_rows("id", PAGE_SIZE), total=PAGE_SIZE)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.params("page") == ["1"]
        assert result.saved_states == []

    def test_resumes_from_saved_page(self) -> None:
        # Page 1 must never be fetched on resume. Total spans 3 pages so page 2 (full) doesn't hit the
        # total-based stop, and page 3 (short) ends the sync.
        result = _driver().run(
            "events",
            [
                _page(_rows("p2", PAGE_SIZE), total=2 * PAGE_SIZE + 1),
                _page(_rows("p3", 1), total=2 * PAGE_SIZE + 1),
            ],
            resume_state=HumanitixResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("page") == ["2", "3"]

    def test_missing_list_key_raises_loudly(self) -> None:
        # A 200 body without the list key means the response shape changed — fail loud, not 0 rows.
        result = _driver().run("events", [_page(None, total=0, drop_key=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestEventFanout:
    @parameterized.expand([("orders",), ("tickets",)])
    def test_fetches_each_event_and_stamps_event_id(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"_id": "e1"}, {"_id": "e2"}], total=2),
                _page([{"_id": "c1"}], total=1, list_key=endpoint),
                _page([{"_id": "c2", "eventId": "e2"}], total=1, list_key=endpoint),
            ],
        )

        assert result.raised is None
        assert result.paths[1:] == [f"/v1/events/e1/{endpoint}", f"/v1/events/e2/{endpoint}"]
        assert result.params("page")[1:] == ["1", "1"]
        assert result.params("pageSize")[1:] == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Orders may omit `eventId`, but it is part of the primary key, so every row must carry it.
        assert result.response is not None
        assert result.response.primary_keys is not None
        assert [{key: row[key] for key in result.response.primary_keys} for row in result.rows] == [
            {"eventId": "e1", "_id": "c1"},
            {"eventId": "e2", "_id": "c2"},
        ]

    def test_resume_skips_completed_events_and_continues_the_current_one(self) -> None:
        result = _driver().run(
            "orders",
            [
                _page([{"_id": "e1"}, {"_id": "e2"}], total=2),
                _page(_rows("o", 1), total=PAGE_SIZE + 1, list_key="orders"),
            ],
            resume_state=HumanitixResumeConfig(
                completed=["/events/e1/orders"], current="/events/e2/orders", child_state={"next_page": 2}
            ),
        )

        assert result.raised is None
        assert len(result.rows) == 1
        assert result.paths == ["/v1/events", "/v1/events/e2/orders"]
        assert result.params("page")[1] == "2"
        # Finishing e2 records it as completed so a later restart skips it too.
        assert result.saved_states[-1] == HumanitixResumeConfig(
            completed=["/events/e1/orders", "/events/e2/orders"], current=None, child_state=None
        )


class TestRetryAndErrors:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_auth_errors_raise_without_retry(self, _name: str, status: int) -> None:
        # A 4xx auth failure is permanent: raise_for_status surfaces an HTTPError and it is not retried.
        result = _driver().run("events", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, HTTPError)
        assert result.params("page") == ["1"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_message: str | None) -> None:
        response = ScriptedResponse(status=status)
        script = always(response) if status == 500 else [response]
        with scripted_network(script) as network:
            assert validate_credentials("hmtx-key") == (expected_valid, expected_message)

        assert {request.path for request in network.requests_log} == {"/v1/events"}
        assert all(request.param("pageSize") == "1" for request in network.requests_log)
        assert all(request.headers["x-api-key"] == "hmtx-key" for request in network.requests_log)

    def test_unreachable_probe_maps_to_generic_message(self) -> None:
        # validate_via_probe swallows transport errors and reports no status; surface a generic message.
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("hmtx-key") == (False, "Could not validate Humanitix API key")


class TestSourceResponse:
    @parameterized.expand([("events",), ("tags",)])
    def test_source_response_uses_id_primary_key(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([], list_key=endpoint)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["_id"]
        # Every endpoint is full refresh only, so there is no datetime partitioning.
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
