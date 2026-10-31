from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.prefectcloud import (
    PrefectCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud import prefect_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud import (
    PrefectCloudResumeConfig,
    _build_json_body,
    _format_after,
    normalize_uuid,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    PAGE_LIMIT,
    PREFECT_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.source import PrefectCloudSource

_ACCOUNT_ID = "11111111-2222-3333-4444-555555555555"
_WORKSPACE_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"
_WORKSPACE_URL = f"https://api.prefect.cloud/api/accounts/{_ACCOUNT_ID}/workspaces/{_WORKSPACE_ID}"


class TestNormalizeUuid:
    @parameterized.expand(
        [
            ("lowercase", _ACCOUNT_ID, _ACCOUNT_ID),
            ("uppercase", _ACCOUNT_ID.upper(), _ACCOUNT_ID),
            ("whitespace", f"  {_ACCOUNT_ID}  ", _ACCOUNT_ID),
        ]
    )
    def test_valid_uuids(self, _name: str, value: str, expected: str) -> None:
        assert normalize_uuid(value, "account ID") == expected

    @parameterized.expand(
        [
            ("path_injection", "1111/../other-account"),
            ("url", "https://app.prefect.cloud/account/11111111-2222-3333-4444-555555555555"),
            ("empty", ""),
            ("not_a_uuid", "my-workspace"),
        ]
    )
    def test_invalid_uuids_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_uuid(value, "account ID")


class TestFormatAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_after(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildJsonBody:
    def test_incremental_unknown_field_falls_back_to_first_advertised(self) -> None:
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="updated",
        )
        assert body["flow_runs"] == {"start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert body["sort"] == "START_TIME_ASC"

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # flows has no server-side time filter; a cursor must not leak into the request.
        body = _build_json_body(
            PREFECT_CLOUD_ENDPOINTS["flows"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created",
        )
        assert body == {"sort": "CREATED_ASC"}


def _driver() -> SourceDriver:
    return SourceDriver(
        PrefectCloudSource(),
        PrefectCloudSourceConfig(account_id=_ACCOUNT_ID, workspace_id=_WORKSPACE_ID, api_key="pnu_key"),
    )


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    # Prefect's filter endpoints return a bare JSON array of rows.
    return ScriptedResponse(json=items)


class TestPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "flows", [_page([{"id": "resumed"}])], resume_state=PrefectCloudResumeConfig(offset=PAGE_LIMIT)
        )

        assert [r["id"] for r in result.rows] == ["resumed"]
        assert [r.json()["offset"] for r in result.requests] == [PAGE_LIMIT]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("flows", [_page([{"id": "first"}])])

        assert [r.json()["offset"] for r in result.requests] == [0]

    def test_incremental_filter_rides_every_page(self) -> None:
        # Prefect takes the filter in the POST body, so later pages must carry the same watermark.
        full_page = [{"id": str(n)} for n in range(PAGE_LIMIT)]

        result = _driver().run(
            "flow_runs",
            [_page(full_page), _page([{"id": "last"}])],
            incremental_field="start_time",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        bodies = [r.json() for r in result.requests]
        assert len(bodies) == 2
        assert all(b["flow_runs"] == {"start_time": {"after_": "2026-03-04T02:58:14Z"}} for b in bodies)
        assert all(b["sort"] == "START_TIME_ASC" for b in bodies)
        assert [b["offset"] for b in bodies] == [0, PAGE_LIMIT]


def _logs(*timestamps: str) -> list[dict[str, Any]]:
    return [{"id": f"log-{n}", "timestamp": ts} for n, ts in enumerate(timestamps)]


class TestLogsKeysetPagination:
    def test_moves_the_lower_bound_before_the_offset_cap_and_rereads_the_boundary_timestamp(self) -> None:
        # The sort has no tie-breaker, so the restart must read every row at T2 again (offset 0)
        # rather than skip a count of them.
        pages = [
            _page(_logs(*["T1"] * PAGE_LIMIT)),
            _page(_logs(*["T1"] * PAGE_LIMIT)),
            _page(_logs(*["T1"] * (PAGE_LIMIT - 2), "T2", "T2")),
            _page(_logs("T2", "T2", "T3")),
        ]

        with mock.patch.object(prefect_cloud, "LOGS_MAX_OFFSET", 2 * PAGE_LIMIT):
            result = _driver().run("logs", pages)

        bodies = [r.json() for r in result.requests]
        assert [b["logs"]["timestamp"].get("after_") for b in bodies] == [None, None, None, "T2"]
        assert [b["offset"] for b in bodies] == [0, PAGE_LIMIT, 2 * PAGE_LIMIT, 0]
        assert len({b["logs"]["timestamp"]["before_"] for b in bodies}) == 1
        assert all(b["sort"] == "TIMESTAMP_ASC" and b["limit"] == PAGE_LIMIT for b in bodies)

    def test_resume_keeps_the_saved_bounds_over_the_watermark(self) -> None:
        result = _driver().run(
            "logs",
            [_page(_logs("T9"))],
            resume_state=PrefectCloudResumeConfig(after="T5", before="T8", offset=3),
            incremental_field="timestamp",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert [r.json()["logs"] for r in result.requests] == [{"timestamp": {"after_": "T5", "before_": "T8"}}]
        assert [r.json()["offset"] for r in result.requests] == [3]


class TestEventsPagination:
    @parameterized.expand(
        [
            ("full_refresh", None, "2020-01-01T00:00:00Z"),
            ("incremental", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_posts_the_filter_then_follows_next_page_with_get(
        self, _name: str, watermark: datetime | None, expected_since: str
    ) -> None:
        next_page = f"{_WORKSPACE_URL}/events/filter/next?page-token=abc"
        result = _driver().run(
            "events",
            [
                ScriptedResponse(json={"events": [{"id": "e1"}], "total": 2, "next_page": next_page}),
                ScriptedResponse(json={"events": [{"id": "e2"}], "total": 2, "next_page": None}),
            ],
            incremental_field="occurred" if watermark else None,
            db_incremental_field_last_value=watermark,
        )

        assert [r["id"] for r in result.rows] == ["e1", "e2"]
        first, second = result.requests
        assert first.method == "POST"
        assert first.json()["filter"] == {"order": "ASC", "occurred": {"since": expected_since}}
        assert (second.method, second.url, second.body) == ("GET", next_page, None)


class TestStateHistoryFanout:
    @parameterized.expand(
        [
            ("flow_run_states", "flow_runs", "flow_run_id"),
            ("task_run_states", "task_runs", "task_run_id"),
        ]
    )
    def test_reads_each_runs_states_and_tags_rows_with_the_run(self, endpoint: str, parent: str, param: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": "run-a"}, {"id": "run-b"}]),
                _page([{"id": "s1", "type": "SCHEDULED"}, {"id": "s2", "type": "RUNNING"}]),
                _page([{"id": "s3", "type": "SCHEDULED"}]),
            ],
            incremental_field="timestamp",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        parent_request, *state_requests = result.requests
        assert parent_request.json()[parent] == {"expected_start_time": {"after_": "2026-03-04T00:00:00Z"}}
        assert [(r.method, r.param(param)) for r in state_requests] == [("GET", "run-a"), ("GET", "run-b")]
        assert [(r[param], r["id"]) for r in result.rows] == [("run-a", "s1"), ("run-a", "s2"), ("run-b", "s3")]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (404, (False, 404)),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: tuple) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            assert validate_credentials(_ACCOUNT_ID, _WORKSPACE_ID, "pnu_key") == expected

        assert network.requests_log[0].url == f"{_WORKSPACE_URL}/flows/filter"

    def test_malformed_id_raises_before_any_request(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError):
                validate_credentials("not-a-uuid", _WORKSPACE_ID, "pnu_key")

        assert network.requests_log == []
