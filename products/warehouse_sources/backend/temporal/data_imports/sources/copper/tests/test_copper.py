from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.copper import (
    COPPER_DEFAULT_PAGE_SIZE,
    CopperResumeConfig,
    _to_unix_seconds,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.copper.source import CopperSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.copper import CopperSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(CopperSource(), CopperSourceConfig(api_key="key", user_email="user@example.com"))


def _records(ids: list[int]) -> list[dict[str, Any]]:
    return [{"id": i, "date_created": 1700000000 + i, "date_modified": 1700000100 + i} for i in ids]


class TestToUnixSeconds:
    @parameterized.expand(
        [
            ("none", None, None),
            ("int", 1700000000, 1700000000),
            ("float", 1700000000.7, 1700000000),
            ("numeric_string", "1700000000", 1700000000),
            ("bool_true", True, None),
            ("garbage", "not-a-number", None),
        ]
    )
    def test_scalar_coercion(self, _name: str, value: Any, expected: int | None) -> None:
        assert _to_unix_seconds(value) == expected

    def test_datetime_coercion(self) -> None:
        dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
        assert _to_unix_seconds(dt) == int(dt.timestamp())

    def test_date_treated_as_utc(self) -> None:
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestPagination:
    def test_checkpoints_next_page_after_each_full_page(self) -> None:
        full_a = _records(list(range(COPPER_DEFAULT_PAGE_SIZE)))
        full_b = _records(list(range(COPPER_DEFAULT_PAGE_SIZE, 2 * COPPER_DEFAULT_PAGE_SIZE)))
        tail = _records([99999])
        result = _driver().run(
            "people", [ScriptedResponse(json=full_a), ScriptedResponse(json=full_b), ScriptedResponse(json=tail)]
        )

        assert result.raised is None
        assert len(result.rows) == 2 * COPPER_DEFAULT_PAGE_SIZE + 1
        # Requests walk pages 1, 2, 3; a checkpoint pointing at the next page is saved after each
        # full page, and the short final page ends the loop without a checkpoint.
        assert [request.json()["page_number"] for request in result.requests] == [1, 2, 3]
        assert result.saved_states == [CopperResumeConfig(page_number=2), CopperResumeConfig(page_number=3)]

    def test_resume_starts_from_saved_page(self) -> None:
        result = _driver().run(
            "people", [ScriptedResponse(json=_records([1]))], resume_state=CopperResumeConfig(page_number=4)
        )

        assert result.raised is None
        assert result.requests[0].json()["page_number"] == 4


class TestSearchBody:
    @parameterized.expand(
        [
            ("people", "date_modified", "minimum_modified_date"),
            ("people", "date_created", "minimum_created_date"),
            ("activities", "activity_date", "minimum_activity_date"),
        ]
    )
    def test_incremental_sets_endpoint_filter_param(
        self, endpoint: str, incremental_field: str, min_param: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=1700000000,
        )

        assert result.raised is None
        body = result.requests[0].json()
        assert body[min_param] == 1700000000
        assert body["page_size"] == COPPER_DEFAULT_PAGE_SIZE

    @parameterized.expand([("incremental", True), ("full_refresh", False)])
    def test_activities_cap_the_window_at_the_sync_start(self, _name: str, should_use_incremental_field: bool) -> None:
        before = int(datetime.now(UTC).timestamp())
        result = _driver().run(
            "activities",
            [ScriptedResponse(json=[])],
            incremental_field="activity_date" if should_use_incremental_field else None,
            db_incremental_field_last_value=1700000000,
        )
        after = int(datetime.now(UTC).timestamp())

        assert result.raised is None
        # `activity_date` is customer-editable, so a row dated far ahead would otherwise become the
        # watermark and hide every later activity behind it.
        assert before <= result.requests[0].json()["maximum_activity_date"] <= after


class TestActivityTypes:
    def test_empty_envelope_yields_nothing(self) -> None:
        result = _driver().run("activity_types", [ScriptedResponse(json={"user": [], "system": []})])

        assert result.raised is None
        assert result.rows == []


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_retries_then_succeeds(self, _name: str, status_code: int) -> None:
        result = _driver().run("people", [ScriptedResponse(status=status_code), ScriptedResponse(json=_records([1]))])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2


class TestRedaction:
    def test_registers_api_key_for_redaction(self) -> None:
        result = _driver().run("people", [ScriptedResponse(json=_records([1]))])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("key",)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("key", "user@example.com")

        assert {request.path for request in network.requests_log} == {"/developer_api/v1/account"}
        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_transport_error_maps_to_invalid(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            valid, error = validate_credentials("key", "user@example.com")

        assert valid is False
        assert error is not None

    def test_registers_api_key_for_redaction(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("secret-key", "user@example.com")

        assert network.session_options[0]["redact_values"] == ("secret-key",)


class TestFieldLayouts:
    def test_entity_copper_does_not_serve_is_skipped(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/developer_api/v1/pipelines":
                return ScriptedResponse(json=[])
            if request.path == "/developer_api/v1/field_layouts/by_entity/tasks":
                return ScriptedResponse(json=[{"field_id": 3}])
            return ScriptedResponse(status=404)

        result = _driver().run("field_layouts", respond)

        assert result.raised is None
        # The other five entities 404 on this account; the walk keeps going instead of failing.
        assert result.rows == [{"entity_type": "tasks", "pipeline_id": 0, "field_id": 3}]


class TestRelatedItems:
    def test_record_deleted_mid_walk_is_skipped(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/developer_api/v1/people/search":
                return ScriptedResponse(json=[{"id": 7}, {"id": 8}])
            if request.path == "/developer_api/v1/people/8/related":
                return ScriptedResponse(json=[{"id": 1, "type": "company"}])
            if request.method == "POST":
                return ScriptedResponse(json=[])
            return ScriptedResponse(status=404)

        result = _driver().run("related_items", respond)

        assert result.raised is None
        # Person 7 was deleted between the search page and its related lookup, so it 404s.
        assert "/developer_api/v1/people/7/related" in result.paths
        assert result.rows == [{"parent_type": "person", "parent_id": 8, "id": 1, "type": "company"}]

    def test_checkpoints_the_next_position_after_each_page(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/developer_api/v1/leads/search":
                page = request.json()["page_number"]
                if page in (1, 2):
                    return ScriptedResponse(json=[{"id": page}, *[{} for _ in range(COPPER_DEFAULT_PAGE_SIZE - 1)]])
            if request.path == "/developer_api/v1/leads/1/related":
                return ScriptedResponse(json=[{"id": 1, "type": "task"}])
            return ScriptedResponse(json=[])

        result = _driver().run("related_items", respond)

        assert result.raised is None
        checkpoints = [(state.parent_index, state.page_number) for state in result.saved_states]
        # Leads pages 1 and 2, then the walk moves on to people (index 1) at page 1. Every later
        # parent contributes one more checkpoint as its single empty page ends it.
        assert checkpoints[:3] == [(0, 2), (0, 3), (1, 1)]

    def test_malformed_search_page_fails_loudly(self) -> None:
        result = _driver().run("related_items", [ScriptedResponse(json=None, body=b"null")])

        assert isinstance(result.raised, ValueError)
