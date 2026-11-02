from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.eventzilla import (
    PAGE_SIZE,
    EventzillaResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.source import EventzillaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventzilla import (
    EventzillaSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(EventzillaSource(), EventzillaSourceConfig(api_key="key"))


def _page(data_key: str, items: list[dict[str, Any]], total: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if total is not None:
        body["pagination"] = {"offset": 0, "limit": PAGE_SIZE, "total": total}
    return ScriptedResponse(json=body)


class TestTopLevelPagination:
    def test_follows_multiple_pages_until_total_reached(self) -> None:
        result = _driver().run(
            "events",
            [
                _page("events", [{"id": i} for i in range(PAGE_SIZE)], total=PAGE_SIZE + 1),
                _page("events", [{"id": 999}], total=PAGE_SIZE + 1),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        # The offset advances by the real returned count, not a fixed step.
        assert result.params("offset") == ["0", str(PAGE_SIZE)]


class TestTopLevelResume:
    def test_resume_uses_saved_offset(self) -> None:
        result = _driver().run(
            "events",
            [_page("events", [], total=40)],
            resume_state=EventzillaResumeConfig(offset=40),
        )

        assert result.raised is None
        assert result.params("offset") == ["40"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/v2/events"


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_5xx_and_429_are_retried_then_succeed(self, _name: str, status: int) -> None:
        result = _driver().run(
            "events",
            [ScriptedResponse(status=status, json={}), _page("events", [{"id": 1}], total=1)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    def test_4xx_auth_error_is_raised(self) -> None:
        result = _driver().run("events", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, Exception)


class TestFanOut:
    def test_resume_skips_completed_events(self) -> None:
        # Resuming with event 1's child path already completed must skip it entirely and only fetch
        # event 2's attendees. Only two responses are scripted (events discovery + event 2), so a fetch
        # of event 1 would exhaust the script and fail.
        fanout_state = {
            "completed": ["/events/1/attendees"],
            "current": "/events/2/attendees",
            "child_state": {"offset": 0},
        }
        result = _driver().run(
            "attendees",
            [_page("events", [{"id": 1}, {"id": 2}], total=2), _page("attendees", [{"id": "A3"}])],
            resume_state=EventzillaResumeConfig(fanout_state=fanout_state),
        )

        assert result.raised is None
        assert result.rows == [{"id": "A3", "event_id": "2"}]
        assert not any("/events/1/attendees" in path for path in result.paths)

    def test_non_404_child_error_propagates(self) -> None:
        # A 5xx is retried up to the client's attempt cap. Keep answering it so the retryable
        # error, rather than an exhausted script, is what finally propagates.
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/v2/events":
                return _page("events", [{"id": 1}], total=1)
            return ScriptedResponse(status=500, json={"error": "boom"})

        result = _driver().run("attendees", respond)

        assert isinstance(result.raised, Exception)
        assert result.paths[0] == "/api/v2/events"
        assert set(result.paths[1:]) == {"/api/v2/events/1/attendees"}


class TestSourceResponse:
    @parameterized.expand(
        [
            ("events", ["id"], None),
            ("categories", ["category"], None),
            ("users", ["id"], None),
            ("attendees", ["event_id", "id"], "transaction_date"),
            ("transactions", ["event_id", "checkout_id"], "transaction_date"),
            ("tickets", ["event_id", "id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        script = (
            [_page("events", [])] if endpoint in {"attendees", "transactions", "tickets"} else [_page(endpoint, [])]
        )
        result = _driver().run(endpoint, script)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]
