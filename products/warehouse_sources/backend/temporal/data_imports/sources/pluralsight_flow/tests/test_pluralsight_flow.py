import re
from datetime import date

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.pluralsight_flow import (
    PluralsightFlowResumeConfig,
    _format_incremental_value,
    normalize_workspace,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.source import (
    PluralsightFlowSource,
)


class TestNormalizeWorkspace:
    @pytest.mark.parametrize(
        "raw",
        [
            "acme/evil.com",
            "acme@evil.com",
            "evil.com/acme",
            "",
            "-acme",
        ],
    )
    def test_rejects_invalid_workspaces(self, raw):
        with pytest.raises(ValueError, match="Invalid Flow workspace"):
            normalize_workspace(raw)


class TestFormatIncrementalValue:
    def test_formats_date(self):
        assert _format_incremental_value(date(2024, 3, 5)) == "2024-03-05T00:00:00"


class TestPluralsightFlowSourceCoreEndpoints:
    """End-to-end pagination/resume behaviour of core endpoints via `rest_api_resource`."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(PluralsightFlowSource(), PluralsightFlowSourceConfig(workspace="acme", api_key="test-key"))

    def test_paginates_until_short_page_and_saves_resume_offset(self) -> None:
        # A page exactly `limit` (1000) long doesn't tell the paginator it's the last page — only
        # a page shorter than `limit` does, so the first fake page must be full-sized.
        full_page = [{"id": i} for i in range(1000)]
        responses = [
            ScriptedResponse(json={"count": 1001, "next": "...", "previous": None, "results": full_page}),
            ScriptedResponse(json={"count": 1001, "next": None, "previous": "...", "results": [{"id": 1000}]}),
        ]
        result = self._driver().run("Repos", responses)

        assert result.raised is None
        assert result.rows == [*full_page, {"id": 1000}]
        # OffsetPaginator always injects `offset` (starting at 0), unlike a bespoke paginator
        # that only adds it once seeded.
        assert result.params("offset") == ["0", "1000"]
        assert result.saved_states == [PluralsightFlowResumeConfig(offset=1000)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        result = self._driver().run(
            "Repos",
            [ScriptedResponse(json={"count": 1, "next": None, "previous": None, "results": [{"id": 5}]})],
            resume_state=PluralsightFlowResumeConfig(offset=2000),
        )

        assert result.raised is None
        assert result.rows == [{"id": 5}]
        assert result.params("offset") == ["2000"]

    @pytest.mark.parametrize(
        ("endpoint", "path", "filter_param"),
        [
            ("Commits", "/v3/customer/core/commits/", "author_date__gte"),
            ("UserAliases", "/v3/customer/core/user_alias/", "created_at__gte"),
        ],
    )
    def test_incremental_endpoint_sends_gte_filter(self, endpoint: str, path: str, filter_param: str) -> None:
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json={"count": 1, "next": None, "previous": None, "results": [{"id": 1}]})],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.paths == [path]
        assert result.requests[0].param(filter_param) == "1970-01-01T00:00:00"

    @pytest.mark.parametrize(
        ("endpoint", "path"),
        [
            ("TeamMemberships", "/v3/customer/core/team_membership/"),
            ("PullRequestProjects", "/v3/customer/core/pull_request_projects/"),
            ("TicketProjects", "/v3/customer/core/ticket_projects/"),
            ("PullRequestComments", "/v3/customer/core/pull_request_comments/"),
            ("TicketEvents", "/v3/customer/core/ticket_events/"),
        ],
    )
    def test_full_refresh_endpoint_sends_no_date_filter(self, endpoint: str, path: str) -> None:
        result = self._driver().run(
            endpoint,
            [ScriptedResponse(json={"count": 1, "next": None, "previous": None, "results": [{"id": 7}]})],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.rows == [{"id": 7}]
        assert result.paths == [path]
        assert not [name for name in result.requests[0].query if name.endswith("__gte")]


class TestPluralsightFlowSourceMetricsEndpoints:
    @pytest.mark.parametrize(
        ("endpoint", "path", "date_range_pattern"),
        [
            (
                "CollaborationMetrics",
                "/collaboration/pullrequest/metrics/",
                r"^\[\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}\]$",
            ),
            (
                "TicketMetrics",
                "/ticket-delivery/metrics/",
                r'^\["\d{4}-\d{2}-\d{2}T00:00:00\+00:00","\d{4}-\d{2}-\d{2}T00:00:00\+00:00"\]$',
            ),
            (
                "DoraChangeFailureRate",
                "/dora/build-release/incident/change_failure_rate/",
                r"^\d{4}-\d{2}-\d{2}T00:00:00\+00:00,\d{4}-\d{2}-\d{2}T00:00:00\+00:00$",
            ),
        ],
    )
    def test_single_object_response_yields_one_row_with_date_range(
        self, endpoint: str, path: str, date_range_pattern: str
    ) -> None:
        result = SourceDriver(
            PluralsightFlowSource(), PluralsightFlowSourceConfig(workspace="acme", api_key="test-key")
        ).run(endpoint, [ScriptedResponse(json={"metric": {"average": 3.5, "trend": 0.1}})])

        assert result.raised is None
        assert result.paths == [path]
        assert re.match(date_range_pattern, result.requests[0].param("date_range") or "")
        assert len(result.rows) == 1
        assert result.rows[0]["metric"] == {"average": 3.5, "trend": 0.1}
        assert result.rows[0]["date_range"] == result.requests[0].param("date_range")
        assert result.saved_states == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_maps_status_to_validity(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            is_valid, status = validate_credentials("test-key", "acme")

        assert is_valid is expected_valid
        assert status == status_code
        assert network.requests_log[0].path == "/v3/customer/core/users/"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer test-key"

    def test_invalid_workspace_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid Flow workspace"):
            validate_credentials("test-key", "a/b")
