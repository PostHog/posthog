from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.aha_ideas import (
    AhaIdeasResumeConfig,
    _build_initial_params,
    _format_updated_since,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.settings import (
    AHA_IDEAS_ENDPOINTS,
    PER_PAGE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.source import AhaIdeasSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahaideas import (
    AhaIdeasSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AhaIdeasSource(), AhaIdeasSourceConfig(subdomain="acme", api_key="key"))


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.aha.io", "acme"),
            ("https_url", "https://acme.aha.io", "acme"),
            ("trailing_slash", "acme.aha.io/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(value)


class TestFormatUpdatedSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_full_refresh_endpoint_never_filters(self) -> None:
        # idea_portals has no server-side `updated_since`; a cursor must not leak into the request.
        params = _build_initial_params(
            AHA_IDEAS_ENDPOINTS["idea_portals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if total_pages is not None:
        body["pagination"] = {"current_page": current_page or 1, "total_pages": total_pages}
    return ScriptedResponse(json=body)


class TestAhaIdeasSourceNonFanout:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "ideas",
            [_response("ideas", [{"id": "2"}], current_page=2, total_pages=2)],
            resume_state=AhaIdeasResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert result.params("page") == ["2"]

    def test_incremental_cursor_added_to_request(self) -> None:
        result = _driver().run(
            "ideas",
            [_response("ideas", [{"id": "1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("updated_since") == ["2026-03-04T02:58:14Z"]

    def test_uses_response_key_for_idea_endorsements(self) -> None:
        # Votes live at /ideas/endorsements with an `idea_endorsements` root key.
        result = _driver().run("idea_endorsements", [_response("idea_endorsements", [{"id": "v1"}], total_pages=1)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["v1"]
        assert result.urls[0].split("?", 1)[0] == "https://acme.aha.io/api/v1/ideas/endorsements"

    def test_missing_metadata_full_page_continues(self) -> None:
        # No pagination metadata + a full page -> there may be more pages.
        full_page = [{"id": str(i)} for i in range(PER_PAGE)]
        result = _driver().run("ideas", [_response("ideas", full_page), _response("ideas", [{"id": "last"}])])

        assert result.raised is None
        assert len(result.rows) == PER_PAGE + 1
        assert len(result.requests) == 2


class TestAhaIdeasSourceFanout:
    def test_idea_comments_fanout_row_format(self) -> None:
        result = _driver().run(
            "idea_comments",
            [
                _response("ideas", [{"id": "idea_1"}], total_pages=1),
                _response("idea_comments", [{"id": "comment_1", "idea_id": "idea_1"}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "comment_1", "idea_id": "idea_1"}]
        assert result.paths == ["/api/v1/ideas", "/api/v1/ideas/idea_1/idea_comments"]
        assert result.response is not None
        assert result.response.primary_keys == ["id", "idea_id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]


class TestAhaIdeasWorkflowStatusTimes:
    def test_explodes_status_times_per_idea(self) -> None:
        result = _driver().run(
            "workflow_status_times",
            [
                _response(
                    "ideas",
                    [
                        {
                            "id": "idea_1",
                            "updated_at": "2026-03-04T00:00:00Z",
                            "workflow_status_times": [
                                {"status_id": "s1", "status_name": "New", "started_at": "2026-01-01T00:00:00Z"},
                                {"status_id": "s2", "status_name": "Shipped", "started_at": "2026-02-01T00:00:00Z"},
                            ],
                        },
                        {"id": "idea_2", "updated_at": "2026-03-05T00:00:00Z", "workflow_status_times": None},
                        {"id": "idea_3", "updated_at": "2026-03-06T00:00:00Z"},
                    ],
                    total_pages=1,
                )
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [(row["idea_id"], row["status_id"], row["idea_updated_at"]) for row in result.rows] == [
            ("idea_1", "s1", "2026-03-04T00:00:00Z"),
            ("idea_1", "s2", "2026-03-04T00:00:00Z"),
        ]
        assert result.paths == ["/api/v1/ideas"]
        assert result.params("fields") == ["id,updated_at,workflow_status_times"]
        assert result.params("updated_since") == ["2026-03-01T00:00:00Z"]


class TestAhaIdeasWorkflows:
    def test_workflows_fan_out_over_products_without_paging(self) -> None:
        result = _driver().run(
            "workflows",
            [
                _response("products", [{"id": "p1"}, {"id": "p2"}], total_pages=1),
                _response("workflows", [{"id": 10, "name": "Idea workflow"}]),
                _response("workflows", [{"id": 10, "name": "Idea workflow"}]),
            ],
        )

        assert result.raised is None
        assert [(row["id"], row["product_id"]) for row in result.rows] == [(10, "p1"), (10, "p2")]
        assert result.paths == ["/api/v1/products", "/api/v1/products/p1/workflows", "/api/v1/products/p2/workflows"]
        assert result.params("page") == ["1", None, None]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("acme", "key") == (True, 200)

        assert [request.path for request in network.requests_log] == ["/api/v1/me"]

    def test_bad_subdomain_raises_before_probe(self) -> None:
        with scripted_network([]) as network:
            with pytest.raises(ValueError, match="Invalid Aha! account domain"):
                validate_credentials("acme/../evil", "key")

        assert network.requests_log == []
        assert network.session_options == []
