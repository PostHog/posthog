from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workable import (
    WorkableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import WORKABLE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.source import WorkableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable import (
    WorkableResumeConfig,
    _format_datetime,
    _sort_mode_for,
    _validate_subdomain,
    validate_credentials,
)


def _response(body: dict[str, Any] | None, *, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _page(items: list[dict[str, Any]], data_key: str = "candidates", next_url: str | None = None) -> dict[str, Any]:
    return {data_key: items, "paging": ({"next": next_url} if next_url else {})}


def _driver() -> SourceDriver:
    return SourceDriver(WorkableSource(), WorkableSourceConfig(subdomain="acme", api_token="tok"))


class TestValidateSubdomain:
    @parameterized.expand(
        [
            ("simple", "groove-tech", "groove-tech"),
            ("alnum", "company123", "company123"),
            ("single_char", "a", "a"),
            ("trims_whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert _validate_subdomain(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("dot_injection", "evil.com/"),
            ("slash", "acme/foo"),
            ("at_sign", "user@host"),
            ("dotted", "a.b"),
            ("trailing_hyphen", "acme-"),
            ("leading_hyphen", "-acme"),
            ("space_inside", "ac me"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            _validate_subdomain(value)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_only", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "already-a-cursor", "already-a-cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestSortMode:
    @parameterized.expand(
        [
            ("created_at_is_asc", "candidates", True, "created_at", "asc"),
            ("updated_at_is_desc", "candidates", True, "updated_at", "desc"),
            ("default_field_is_desc", "candidates", True, None, "desc"),
            ("non_incremental_run_is_asc", "candidates", False, "updated_at", "asc"),
            ("full_refresh_endpoint_is_asc", "members", True, "updated_at", "asc"),
        ]
    )
    def test_sort_mode(
        self, _name: str, endpoint: str, use_incremental: bool, field: str | None, expected: str
    ) -> None:
        assert _sort_mode_for(endpoint, use_incremental, field) == expected


class TestPagination:
    def test_saves_state_after_each_page_with_more_pages(self) -> None:
        second = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=2"
        result = _driver().run(
            "candidates",
            [
                _response(_page([{"id": "1"}], next_url=second)),
                _response(_page([{"id": "2"}])),
            ],
        )

        # State saved once (after page 1, which had a next); not after the final page.
        assert result.saved_states == [WorkableResumeConfig(next_url=second)]

    def test_resumes_from_saved_next_url(self) -> None:
        resume_url = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=99"

        result = _driver().run(
            "candidates",
            [_response(_page([{"id": "99"}]))],
            resume_state=WorkableResumeConfig(next_url=resume_url),
        )

        # The initial URL is never fetched — we pick up from the saved cursor.
        assert [r["id"] for r in result.rows] == ["99"]
        assert result.urls == [resume_url]

    def test_next_url_on_another_host_is_not_followed(self) -> None:
        result = _driver().run(
            "candidates",
            [_response(_page([{"id": "1"}], next_url="https://attacker.example/collect"))],
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert len(result.urls) == 1

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("candidates", [_response(_page([{"id": "1"}]))])

        assert result.urls[0].startswith("https://acme.workable.com/spi/v3/candidates?")


class TestIncrementalFilter:
    def test_default_field_injects_updated_after(self) -> None:
        result = _driver().run(
            "candidates",
            [_response(_page([{"id": "1"}]))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.requests[0].param("updated_after") == "2026-01-02T03:04:05Z"
        assert "created_after" not in result.requests[0].query

    def test_created_at_field_injects_created_after(self) -> None:
        result = _driver().run(
            "candidates",
            [_response(_page([{"id": "1"}]))],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.requests[0].param("created_after") == "2026-01-02T03:04:05Z"
        assert "updated_after" not in result.requests[0].query


class TestRetryBehavior:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run(
            "candidates",
            [
                _response({}, status=status),
                _response(_page([{"id": "1"}])),
            ],
        )

        assert [r["id"] for r in result.rows] == ["1"]
        assert len(result.requests) == 2

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    def test_non_retryable_status_raises_http_error(self, _name: str, status: int, reason: str) -> None:
        result = _driver().run("candidates", always(_response({}, status=status)))

        assert isinstance(result.raised, requests.HTTPError)
        # The message shape feeds source.get_non_retryable_errors matching.
        assert f"{status} Client Error: {reason} for url: https://" in str(result.raised)

    def test_bearer_token_is_redacted_from_errors(self) -> None:
        # Carry the token in the URL to prove it's scrubbed from the raised error.
        result = SourceDriver(WorkableSource(), WorkableSourceConfig(subdomain="acme", api_token="secret-tok")).run(
            "candidates",
            always(_response({}, status=401)),
            resume_state=WorkableResumeConfig(next_url="https://acme.workable.com/spi/v3/candidates?t=secret-tok"),
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "secret-tok" not in str(result.raised)


class TestWorkableSourceResponse:
    @parameterized.expand(list(WORKABLE_ENDPOINTS.keys()))
    def test_source_response_primary_keys_and_partitioning(self, endpoint: str) -> None:
        config = WORKABLE_ENDPOINTS[endpoint]

        result = _driver().run(endpoint, always(_response({})))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # Never partition on a mutable field like updated_at.
        for config in WORKABLE_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden", 403, (403, False)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[int, bool]) -> None:
        with scripted_network(always(_response({}, status=status))) as network:
            assert validate_credentials("acme", "tok") == expected

        assert network.requests_log[0].url == "https://acme.workable.com/spi/v3/jobs?limit=1"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"

    def test_invalid_subdomain_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com/", "tok")


class TestEmployees:
    @parameterized.expand(
        [
            # A server-side cap below PAGE_SIZE must move the offset by the rows returned, not the limit.
            ("capped_page_size_stops_at_total", {"totalCount": 4}, ["0", "2"]),
            # Without a total, the walk ends on the first empty page.
            ("missing_total_stops_on_empty_page", {}, ["0", "2", "4"]),
        ]
    )
    def test_offset_walk(self, _name: str, total: dict[str, Any], expected_offsets: list[str]) -> None:
        pages = [
            _response({**total, "employees": [{"id": "e1"}, {"id": "e2"}]}),
            _response({**total, "employees": [{"id": "e3"}, {"id": "e4"}]}),
            _response({**total, "employees": []}),
        ]

        result = _driver().run("employees", pages[: len(expected_offsets)])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["e1", "e2", "e3", "e4"]
        assert result.params("offset") == expected_offsets
        assert set(result.params("limit")) == {"100"}


class TestDepartments:
    def test_bare_array_body_is_read_in_one_request(self) -> None:
        result = _driver().run(
            "departments",
            [
                ScriptedResponse(
                    json=[
                        {"id": "d1", "name": "Engineering", "parent_id": None},
                        {"id": "d2", "name": "Platform", "parent_id": "d1"},
                    ]
                )
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["parent_id"]) for r in result.rows] == [("d1", None), ("d2", "d1")]
        assert result.paths == ["/spi/v3/departments"]
        assert result.requests[0].query == {}


class TestCandidateActivities:
    @parameterized.expand(
        [
            ("full_refresh", False, None, None),
            ("incremental", True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
        ]
    )
    def test_fans_out_over_candidates(
        self, _name: str, use_incremental: bool, last_value: datetime | None, expected_filter: str | None
    ) -> None:
        candidates_next = "https://acme.workable.com/spi/v3/candidates?limit=100&since_id=c2"
        activities_next = "https://acme.workable.com/spi/v3/candidates/c1/activities?limit=100&since_id=a2"
        script = route(
            {
                "/c1/activities": [
                    _response(
                        _page(
                            [{"action": "applied", "created_at": "2026-01-03T00:00:00Z"}], "activities", activities_next
                        )
                    ),
                    _response(_page([{"action": "comment", "created_at": "2026-01-04T00:00:00Z"}], "activities")),
                ],
                # A candidate deleted between the listing and its activity fetch is skipped.
                "/c2/activities": [_response({"error": "Not found"}, status=404)],
                "/c3/activities": [
                    _response(_page([{"action": "moved", "created_at": "2026-01-05T00:00:00Z"}], "activities"))
                ],
                "/candidates": [
                    _response(_page([{"id": "c1"}, {"id": "c2"}], next_url=candidates_next)),
                    _response(_page([{"id": "c3"}])),
                ],
            }
        )

        result = _driver().run(
            "candidate_activities",
            script,
            incremental_field="updated_at",
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [(r["candidate_id"], r["action"]) for r in result.rows] == [
            ("c1", "applied"),
            ("c1", "comment"),
            ("c3", "moved"),
        ]
        child_requests = [r for r in result.requests if r.path.endswith("/activities")]
        parent_requests = [r for r in result.requests if r.path.endswith("/candidates")]
        assert [r.param("updated_after") for r in child_requests[:1] + child_requests[2:]] == [expected_filter] * 3
        assert all(r.param("updated_after") is None for r in parent_requests)

    def test_resume_skips_completed_candidates(self) -> None:
        script = route(
            {
                "/c2/activities": [
                    _response(_page([{"action": "applied", "created_at": "2026-01-03T00:00:00Z"}], "activities"))
                ],
                "/candidates": [_response(_page([{"id": "c1"}, {"id": "c2"}]))],
            }
        )

        result = _driver().run(
            "candidate_activities",
            script,
            should_use_incremental_field=False,
            resume_state=WorkableResumeConfig(
                fanout_state={"completed": ["/candidates/c1/activities"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [r["candidate_id"] for r in result.rows] == ["c2"]
        assert not any(r.path.endswith("/c1/activities") for r in result.requests)
        assert result.committed_states[-1].fanout_state["completed"] == [
            "/candidates/c1/activities",
            "/candidates/c2/activities",
        ]
