from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.cyberimpact._config import CyberimpactSourceConfig
from products.warehouse_sources.sources.cyberimpact.cyberimpact import (
    INVALID_TOKEN_ERROR,
    UNVERIFIED_TOKEN_ERROR,
    CyberimpactResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.cyberimpact.source import CyberimpactSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _driver() -> SourceDriver:
    return SourceDriver(CyberimpactSource(), CyberimpactSourceConfig(api_token="ci_test_token"))


def _page(key: str, rows: list[dict[str, Any]], total: int | None, limit: int = 2) -> ScriptedResponse:
    body: dict[str, Any] = {key: rows, "page": 1, "limit": limit}
    if total is not None:
        body["totalCount"] = total
    return ScriptedResponse(json=body)


def _members(ids: list[int], total: int | None, limit: int = 2) -> ScriptedResponse:
    return _page(
        "members", [{"id": member_id, "email": f"m{member_id}@example.com"} for member_id in ids], total, limit
    )


class TestListings:
    @pytest.mark.parametrize(
        ("script", "expected_pages"),
        [
            # totalCount says when the pages run out, so no empty page is requested.
            ([_members([1, 2], 5), _members([3, 4], 5), _members([5], 5)], ["1", "2", "3"]),
            ([_members([1, 2], 4), _members([3, 4], 4)], ["1", "2"]),
            # Without totalCount, the walk stops at the first empty page.
            ([_members([1, 2], None), _members([3], None), _members([], None)], ["1", "2", "3"]),
        ],
    )
    def test_walks_pages_to_the_last_page(self, script: list[ScriptedResponse], expected_pages: list[str]) -> None:
        result = _driver().run("members", script)

        assert result.raised is None
        assert result.params("page") == expected_pages
        assert {request.origin for request in result.requests} == {"https://api.cyberimpact.com"}
        assert {request.headers["authorization"] for request in result.requests} == {"Bearer ci_test_token"}
        assert set(result.params("limit")) == {"10000"}
        assert set(result.params("dateReturnFormat")) == {"ISO8601"}
        # Without status=all the listing leaves out members in no group.
        assert set(result.params("status")) == {"all"}
        assert set(result.params("sort")) == {"date_asc"}
        assert result.params("updatedOnFrom") == [None] * len(expected_pages)
        assert result.saved_states == [CyberimpactResumeConfig(page=int(page)) for page in expected_pages[1:]]

    def test_a_response_without_the_row_list_fails_the_run(self) -> None:
        result = _driver().run("groups", [ScriptedResponse(json={"message": "unexpected"})])

        assert result.raised is not None
        assert result.rows == []

    def test_custom_fields_is_read_in_one_unpaginated_request(self) -> None:
        result = _driver().run(
            "custom_fields", [ScriptedResponse(json={"customFields": [{"id": 1, "name": "Colour", "type": "text"}]})]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.params("page") == [None]
        assert result.params("limit") == [None]


class TestIncrementalMembers:
    @pytest.mark.parametrize(
        "last_value",
        [
            datetime(2026, 3, 10, 2, 30, tzinfo=UTC),
            datetime(2026, 3, 10, 2, 30),
            date(2026, 3, 10),
            "2026-03-10T02:30:00+00:00",
        ],
    )
    def test_reads_updated_then_joined_members_from_the_day_before_the_watermark(self, last_value: Any) -> None:
        result = _driver().run(
            "members",
            [_members([1, 2], 3), _members([3], 3), _members([4], 1)],
            incremental_field="updatedOn",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3, 4]
        assert result.params("updatedOnFrom") == ["2026-03-09", "2026-03-09", None]
        # A member never edited has a null updatedOn, so the joined-date pass picks up new members.
        assert result.params("joinedOnFrom") == [None, None, "2026-03-09"]
        assert result.params("page") == ["1", "2", "1"]
        assert result.saved_states == [
            CyberimpactResumeConfig(page=2, phase=0),
            CyberimpactResumeConfig(page=1, phase=1),
        ]

    def test_an_empty_updated_pass_still_runs_the_joined_pass(self) -> None:
        result = _driver().run(
            "members",
            [_members([], 0), _members([7], 1)],
            incremental_field="updatedOn",
            db_incremental_field_last_value=date(2026, 3, 10),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert result.params("joinedOnFrom") == [None, "2026-03-09"]

    def test_a_first_incremental_run_reads_every_member_once(self) -> None:
        result = _driver().run(
            "members",
            [_members([1], 1)],
            incremental_field="updatedOn",
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.params("updatedOnFrom") == [None]
        assert result.params("joinedOnFrom") == [None]

    def test_resume_continues_the_saved_pass_at_the_saved_page(self) -> None:
        result = _driver().run(
            "members",
            [_members([5], 3)],
            incremental_field="updatedOn",
            db_incremental_field_last_value=date(2026, 3, 10),
            resume_state=CyberimpactResumeConfig(page=2, phase=1),
        )

        assert result.raised is None
        assert result.params("page") == ["2"]
        assert result.params("joinedOnFrom") == ["2026-03-09"]
        assert result.params("updatedOnFrom") == [None]


def _mailings(ids: list[int], total: int) -> ScriptedResponse:
    return _page("mailings", [{"id": mailing_id, "subject": f"s{mailing_id}"} for mailing_id in ids], total)


def _recipients(emails: list[str], total: int) -> ScriptedResponse:
    return _page("recipients", [{"idMember": None, "email": email} for email in emails], total)


class TestMailingFanOut:
    def test_opens_fan_out_over_sent_mailings_and_skip_a_deleted_mailing(self) -> None:
        result = _driver().run(
            "mailing_opens",
            route(
                {
                    "/mailings/sent": [_mailings([10, 11], 3), _mailings([12], 3)],
                    "/mailings/10/recipients/opened": [
                        _recipients(["a@example.com", "b@example.com"], 3),
                        _recipients(["c@example.com"], 3),
                    ],
                    "/mailings/11/recipients/opened": [ScriptedResponse(status=404, json={"status_code": 404})],
                    "/mailings/12/recipients/opened": [_recipients(["a@example.com"], 1)],
                }
            ),
        )

        assert result.raised is None
        assert [(row["mailing_id"], row["email"]) for row in result.rows] == [
            (10, "a@example.com"),
            (10, "b@example.com"),
            (10, "c@example.com"),
            (12, "a@example.com"),
        ]
        child_requests = [request for request in result.requests if "/recipients/" in request.path]
        assert {request.param("limit") for request in child_requests} == {"10000"}
        assert {request.param("dateReturnFormat") for request in child_requests} == {"ISO8601"}

    def test_stats_read_each_mailing_as_one_object(self) -> None:
        result = _driver().run(
            "mailing_stats",
            route(
                {
                    "/mailings/sent": [_mailings([10, 11], 2)],
                    "/mailings/10": [ScriptedResponse(json={"id": 10, "views": 4, "clicks": 1})],
                    "/mailings/11": [ScriptedResponse(json={"id": 11, "views": 0, "clicks": 0})],
                }
            ),
        )

        assert result.raised is None
        assert [(row["id"], row["views"]) for row in result.rows] == [(10, 4), (11, 0)]
        detail_requests = [request for request in result.requests if request.path != "/mailings/sent"]
        assert [request.param("limit") for request in detail_requests] == [None, None]
        assert [request.param("page") for request in detail_requests] == [None, None]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("token", "answer", "expected"),
        [
            ("ci_test_token", ScriptedResponse(json={"ping": "success"}), (True, None)),
            # A pasted "Bearer " prefix would otherwise be sent twice.
            ("Bearer ci_test_token ", ScriptedResponse(json={"ping": "success"}), (True, None)),
            (
                "ci_test_token",
                ScriptedResponse(status=401, json={"message": "Could not decode token", "status_code": 401}),
                (False, INVALID_TOKEN_ERROR),
            ),
            ("ci_test_token", ScriptedResponse(status=500, json={"status_code": 500}), (False, UNVERIFIED_TOKEN_ERROR)),
        ],
    )
    def test_maps_the_ping_response(
        self, token: str, answer: ScriptedResponse, expected: tuple[bool, str | None]
    ) -> None:
        with scripted_network(always(answer)) as network:
            assert validate_credentials(token) == expected

        assert {request.url for request in network.requests_log} == {"https://api.cyberimpact.com/ping"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer ci_test_token"}
