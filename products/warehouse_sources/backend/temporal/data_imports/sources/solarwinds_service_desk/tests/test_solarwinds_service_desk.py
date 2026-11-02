from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Optional

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.solarwindsservicedesk import (
    SolarwindsServiceDeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    ENDPOINTS,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.solarwinds_service_desk import (
    SolarwindsServiceDeskResumeConfig,
    _format_updated_from,
    _unwrap_row,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.source import (
    SolarwindsServiceDeskSource,
)


def _response(items: Optional[list[Any]], *, total_pages: Optional[int] = None) -> ScriptedResponse:
    headers = {"X-Total-Pages": str(total_pages)} if total_pages is not None else {}
    return ScriptedResponse(json=items or [], headers=headers)


def _run(
    responses: Script,
    endpoint: str = "incidents",
    resume_state: Optional[SolarwindsServiceDeskResumeConfig] = None,
    **inputs: Any,
) -> DriveResult:
    config = SolarwindsServiceDeskSourceConfig(api_token="swsd-token", region="us")
    return SourceDriver(SolarwindsServiceDeskSource(), config).run(
        endpoint, responses, resume_state=resume_state, **inputs
    )


class TestPagination:
    def test_short_page_does_not_stop_pagination(self) -> None:
        # A page smaller than PER_PAGE must not be treated as the end: the server may clamp
        # `per_page`, so only an empty page or the X-Total-Pages header terminates the crawl.
        result = _run([_response([{"id": 1}]), _response([{"id": 2}]), _response([])])
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert len(result.requests) == 3
        assert result.params("page") == ["1", "2", "3"]

    def test_resumes_from_saved_page_with_saved_filter(self) -> None:
        result = _run(
            [_response([{"id": 9}], total_pages=3)],
            resume_state=SolarwindsServiceDeskResumeConfig(next_page=3, updated_from="2026-01-01T00:00"),
            # A resumed run must reuse the persisted filter, not recompute one from this watermark.
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-02-02T00:00:00Z",
        )
        assert result.rows == [{"id": 9}]
        assert result.requests[0].param("page") == "3"
        assert result.requests[0].param("updated_from") == "2026-01-01T00:00"

    @parameterized.expand(
        [
            ("full_refresh_endpoint", "users", True, datetime(2026, 1, 5, tzinfo=UTC)),
            ("incremental_disabled", "incidents", False, datetime(2026, 1, 5, tzinfo=UTC)),
            ("no_watermark", "incidents", True, None),
            ("unparseable_watermark", "incidents", True, "not a datetime"),
        ]
    )
    def test_no_updated_from_param(self, _name: str, endpoint: str, use_incremental: bool, watermark: Any) -> None:
        result = _run(
            [_response([])],
            endpoint=endpoint,
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=watermark,
        )
        assert result.requests[0].param("updated_from") is None


class TestTimeTracksFanout:
    def test_walks_every_incident_and_tags_rows_with_the_incident(self) -> None:
        result = _run(
            route(
                {
                    "/incidents.json": [
                        _response([{"incident": {"id": 1}}, {"id": 2}, {"id": 3}], total_pages=2),
                        _response([{"id": 4}], total_pages=2),
                    ],
                    "/incidents/1/time_tracks.json": [
                        _response([{"time_track": {"id": 10, "minutes": "30"}}], total_pages=2),
                        _response([{"id": 11, "minutes": "5"}], total_pages=2),
                    ],
                    # Deleted between the incident listing and the child fetch.
                    "/incidents/2/time_tracks.json": [ScriptedResponse(status=404, json={})],
                    "/incidents/3/time_tracks.json": [_response([])],
                    "/incidents/4/time_tracks.json": [
                        _response([{"time_track": {"id": 12, "minutes": "60"}}], total_pages=1)
                    ],
                }
            ),
            endpoint="time_tracks",
        )
        assert result.raised is None
        assert result.rows == [
            {"id": 10, "minutes": "30", "incident_id": 1},
            {"id": 11, "minutes": "5", "incident_id": 1},
            {"id": 12, "minutes": "60", "incident_id": 4},
        ]
        assert result.paths == [
            "/incidents.json",
            "/incidents/1/time_tracks.json",
            "/incidents/1/time_tracks.json",
            "/incidents/2/time_tracks.json",
            "/incidents/3/time_tracks.json",
            "/incidents.json",
            "/incidents/4/time_tracks.json",
        ]
        assert result.final_state.fanout_state["completed"] == [
            "/incidents/1/time_tracks.json",
            "/incidents/2/time_tracks.json",
            "/incidents/3/time_tracks.json",
            "/incidents/4/time_tracks.json",
        ]

    def test_resume_skips_completed_incidents_and_continues_the_current_one(self) -> None:
        result = _run(
            route(
                {
                    "/incidents.json": [_response([{"id": 1}, {"id": 2}, {"id": 3}], total_pages=1)],
                    "/incidents/2/time_tracks.json": [_response([{"id": 21}], total_pages=2)],
                    "/incidents/3/time_tracks.json": [_response([{"id": 31}], total_pages=1)],
                }
            ),
            endpoint="time_tracks",
            resume_state=SolarwindsServiceDeskResumeConfig(
                fanout_state={
                    "completed": ["/incidents/1/time_tracks.json"],
                    "current": "/incidents/2/time_tracks.json",
                    "child_state": {"page": 2},
                }
            ),
        )
        assert result.raised is None
        assert result.rows == [{"id": 21, "incident_id": 2}, {"id": 31, "incident_id": 3}]
        assert [r.path for r in result.requests if r.path != "/incidents.json"] == [
            "/incidents/2/time_tracks.json",
            "/incidents/3/time_tracks.json",
        ]
        assert result.requests[1].param("page") == "2"

    def test_retries_a_child_response_that_is_not_a_list(self) -> None:
        # A 200 error object carries no X-Total-Pages header; wrapped as a row it would keep the
        # crawl paging, so it must be retried instead.
        result = _run(
            route(
                {
                    "/incidents.json": [_response([{"id": 1}], total_pages=1)],
                    "/incidents/1/time_tracks.json": [
                        ScriptedResponse(json={"error": "temporarily unavailable"}),
                        _response([{"id": 10}], total_pages=1),
                    ],
                }
            ),
            endpoint="time_tracks",
        )
        assert result.raised is None
        assert result.rows == [{"id": 10, "incident_id": 1}]


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("aware_utc", datetime(2026, 1, 5, 8, 30, 59, tzinfo=UTC), "2026-01-05T08:30"),
            ("aware_offset", datetime(2026, 1, 5, 9, 30, tzinfo=timezone(timedelta(hours=1))), "2026-01-05T08:30"),
            ("naive_treated_as_utc", datetime(2026, 1, 5, 8, 30), "2026-01-05T08:30"),
            ("iso_string", "2026-01-05T08:30:59.000+00:00", "2026-01-05T08:30"),
            ("date", date(2026, 1, 5), "2026-01-05T00:00"),
            ("garbage_string", "not a datetime", None),
            ("integer", 12345, None),
            ("none", None, None),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert _format_updated_from(value) == expected


class TestUnwrapRow:
    @parameterized.expand(
        [
            ("wrapped", {"user": {"id": 1, "name": "A"}}, "user", {"id": 1, "name": "A"}),
            ("bare_record", {"id": 2, "name": "B"}, "user", {"id": 2, "name": "B"}),
            # A single-key dict whose value isn't a record is a real record that merely has one field.
            ("wrapper_key_not_a_record", {"user": "not a record", "id": 3}, "user", {"user": "not a record", "id": 3}),
            (
                "wrapped_with_parent_field",
                {"time_track": {"id": 4}, "incident_id": 9},
                "time_track",
                {"id": 4, "incident_id": 9},
            ),
            ("bare_with_parent_field", {"id": 5, "incident_id": 9}, "time_track", {"id": 5, "incident_id": 9}),
            # Only the declared parent fields may sit beside the wrapper; anything else means a real record.
            (
                "wrapper_beside_other_field",
                {"time_track": {"id": 6}, "note": "x"},
                "time_track",
                {"time_track": {"id": 6}, "note": "x"},
            ),
        ]
    )
    def test_normalizes_documented_shapes(
        self, _name: str, item: dict[str, Any], wrapper_key: str, expected: dict[str, Any]
    ) -> None:
        assert _unwrap_row(item, wrapper_key, frozenset({"incident_id"})) == expected


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.samanage.com"),
            ("eu", "https://apieu.samanage.com"),
            ("au", "https://apiau.samanage.com"),
            (None, "https://api.samanage.com"),
            ("unknown", "https://api.samanage.com"),
        ]
    )
    def test_base_url_per_region(self, region: Optional[str], expected: str) -> None:
        assert base_url(region) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            # A 403 with a genuine token must not block source-create, but must fail a
            # schema-scoped probe so the user sees which table their role can't read.
            ("forbidden_at_create", 403, None, True, None),
            (
                "forbidden_for_schema",
                403,
                "/incidents.json",
                False,
                "Your SolarWinds Service Desk token does not have permission to read this resource",
            ),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        path: Optional[str],
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("us", "swsd-token", path) == (expected_valid, expected_message)


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]
        result = _run([_response([])], endpoint=endpoint)
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Ordering is undocumented, so the watermark must only commit after a completed sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # updated_at-style partition keys rewrite partitions on every sync.
        assert all(
            config.partition_key in (None, "created_at") for config in SOLARWINDS_SERVICE_DESK_ENDPOINTS.values()
        )
        assert set(SOLARWINDS_SERVICE_DESK_ENDPOINTS) == set(ENDPOINTS)
