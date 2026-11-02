from collections.abc import Iterator
from datetime import timedelta

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import BOOKINGS_WINDOW_ORIGIN
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source import CalComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig


@pytest.fixture(autouse=True)
def _clock_before_the_window_origin() -> Iterator[None]:
    with time_machine.travel(BOOKINGS_WINDOW_ORIGIN - timedelta(days=200), tick=False):
        yield


class TestCalComSource:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.team_id = 123
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")

    def test_source_for_pipeline_drops_incremental_value_when_disabled(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "bookings",
            [ScriptedResponse(json={"data": [], "pagination": {"nextCursor": None}})],
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.requests[0].param("afterUpdatedAt") is None
        assert result.requests[0].param("afterCreatedAt") == "1970-01-01T00:00:00.000Z"

    @parameterized.expand(
        [
            ("organization_users", True),
            ("routing_form_responses", True),
            ("bookings", False),
        ]
    )
    def test_source_for_pipeline_resolves_the_org_only_where_a_path_needs_it(
        self, schema_name: str, needs_org: bool
    ) -> None:
        # An org lookup is an extra request per sync; a path with no {orgId} must not pay it.
        answers = [ScriptedResponse(json={"data": {"organizationId": 77}})] if needs_org else []
        answers.append(ScriptedResponse(json={"data": [], "pagination": {"nextCursor": None}}))
        result = SourceDriver(self.source, self.config).run(schema_name, answers)

        assert result.raised is None
        assert (result.paths[0] == "/v2/me") is needs_org
        if needs_org:
            assert "/organizations/77/" in result.paths[1]
        else:
            assert result.paths == ["/v2/bookings"]


class TestCalComEndpointPermissions:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")
        self.endpoints = ["bookings", "organization_users", "routing_form_responses"]

    def test_org_tables_are_flagged_for_a_personal_account(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": {"id": 1}})]) as network:
            permissions = self.source.get_endpoint_permissions(self.config, 1, self.endpoints)

        assert permissions["bookings"] is None
        assert "not in a Cal.com organization" in (permissions["organization_users"] or "")
        assert "not in a Cal.com organization" in (permissions["routing_form_responses"] or "")
        assert [request.path for request in network.requests_log] == ["/v2/me"]

    def test_org_tables_are_flagged_for_a_non_admin_member(self) -> None:
        with scripted_network(
            [ScriptedResponse(json={"data": {"organizationId": 77}}), ScriptedResponse(status=403)]
        ) as network:
            permissions = self.source.get_endpoint_permissions(self.config, 1, self.endpoints)

        assert permissions["bookings"] is None
        assert "organization member without admin access" in (permissions["organization_users"] or "")
        assert permissions["routing_form_responses"] == permissions["organization_users"]
        assert [request.path for request in network.requests_log] == ["/v2/me", "/v2/organizations/77/memberships"]

    def test_an_unreachable_probe_leaves_every_table_selectable(self) -> None:
        # The table picker must never be blocked by a failed probe.
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert self.source.get_endpoint_permissions(self.config, 1, self.endpoints) == dict.fromkeys(self.endpoints)
        assert {request.path for request in network.requests_log} == {"/v2/me"}

    def test_no_probe_when_no_org_table_is_requested(self) -> None:
        with scripted_network([]) as network:
            assert self.source.get_endpoint_permissions(self.config, 1, ["bookings"]) == {"bookings": None}
        assert network.requests_log == []
