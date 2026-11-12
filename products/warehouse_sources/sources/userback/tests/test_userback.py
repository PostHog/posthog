from datetime import UTC, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.userback._config import UserbackSourceConfig
from products.warehouse_sources.sources.userback.source import UserbackSource
from products.warehouse_sources.sources.userback.userback import UserbackResumeConfig, validate_credentials

# Verbatim body the live API returns for a missing or wrong token.
UNAUTHORIZED_BODY = {"message": "Unauthorized", "status": 401}


def _driver() -> SourceDriver:
    return SourceDriver(UserbackSource(), UserbackSourceConfig(api_token="ub-token"))


def _page(rows: list[dict[str, Any]], page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "_links": {"self": f"https://rest.userback.io/1.0/feedback?page={page}"},
            "_pagination": {
                "totalPages": total_pages,
                "totalRecords": len(rows) * total_pages,
                "pageSize": 100,
                "records": len(rows),
                "pageNumber": page,
            },
            "data": rows,
        }
    )


class TestPagination:
    def test_walks_pages_until_total_pages_and_checkpoints_the_next_page(self) -> None:
        result = _driver().run(
            "feedback",
            [
                _page([{"id": 1, "created": "2026-01-01T00:00:00Z"}], page=1, total_pages=2),
                _page([{"id": 2, "created": "2026-01-02T00:00:00Z"}], page=2, total_pages=2),
            ],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2]
        # totalPages ends the walk, so no third request for an empty page.
        assert result.paths == ["/1.0/feedback", "/1.0/feedback"]
        assert result.params("page") == ["1", "2"]
        assert result.params("limit") == ["100", "100"]
        assert all(request.headers["authorization"] == "Bearer ub-token" for request in result.requests)
        assert result.committed_states == [UserbackResumeConfig(page=2)]

    def test_resume_starts_from_the_saved_page(self) -> None:
        result = _driver().run(
            "feedback",
            [_page([{"id": 7, "created": "2026-01-03T00:00:00Z"}], page=3, total_pages=3)],
            resume_state=UserbackResumeConfig(page=3),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert result.params("page") == ["3"]


class TestRequestShaping:
    @pytest.mark.parametrize(
        ("endpoint", "inputs", "expected_filter", "expected_sort"),
        [
            (
                "feedback",
                {
                    "incremental_field": "modified",
                    "db_incremental_field_last_value": datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                },
                "modified ge '2026-03-04T02:58:14Z'",
                "modified,asc",
            ),
            (
                "feedback",
                {"incremental_field": "created", "db_incremental_field_last_value": datetime(2026, 3, 4, 2, 58, 14)},
                "created ge '2026-03-04T02:58:14Z'",
                "created,asc",
            ),
            (
                "feedback_comments",
                {"incremental_field": "modified", "db_incremental_field_last_value": "2026-03-04T02:58:14Z"},
                "modified ge '2026-03-04T02:58:14Z'",
                "modified,asc",
            ),
            (
                "session_recordings",
                {"incremental_field": "created", "db_incremental_field_last_value": None},
                None,
                "created,asc",
            ),
            ("feedback", {"should_use_incremental_field": False}, None, "created,asc"),
            ("members", {}, None, None),
            ("workflows", {}, None, None),
        ],
    )
    def test_filter_and_sort(
        self, endpoint: str, inputs: dict[str, Any], expected_filter: str | None, expected_sort: str | None
    ) -> None:
        result = _driver().run(endpoint, [_page([], page=1, total_pages=0)], **inputs)

        assert result.raised is None
        assert result.params("filter") == [expected_filter]
        assert result.params("sort") == [expected_sort]


class TestErrors:
    def test_unauthorized_sync_raises_http_error(self) -> None:
        result = _driver().run("projects", [ScriptedResponse(status=401, json=UNAUTHORIZED_BODY)])

        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://rest.userback.io" in str(result.raised)

    def test_body_without_data_raises(self) -> None:
        result = _driver().run("projects", [ScriptedResponse(json={"message": "unexpected"})])

        # A 200 without a `data` array means the response shape changed. The sync fails instead of loading 0 rows.
        assert result.raised is not None
        assert result.rows == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("answer", "expected_ok", "expected_message"),
        [
            (ScriptedResponse(json={"data": []}), True, None),
            (ScriptedResponse(status=401, json=UNAUTHORIZED_BODY), False, "rejected the API token"),
            (ScriptedResponse(status=403, json={"message": "Forbidden", "status": 403}), False, "Premium plan"),
            (ScriptedResponse(status=500, json={"message": "Error", "status": 500}), False, "status 500"),
            (requests.ConnectionError("connection reset"), False, "Could not reach Userback"),
        ],
    )
    def test_probe_result_maps_to_message(self, answer: Any, expected_ok: bool, expected_message: str | None) -> None:
        with scripted_network(always(answer)) as network:
            ok, message = validate_credentials("ub-token")

        assert {request.path for request in network.requests_log} == {"/1.0/project"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer ub-token"}
        assert ok is expected_ok
        if expected_message is None:
            assert message is None
        else:
            assert message is not None and expected_message in message
