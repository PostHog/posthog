import json
from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.filter_catalog import SignalFilterSourceDefinition
from products.signals.backend.filter_catalog_seeds import LINEAR_ISSUE_SEED
from products.signals.backend.models import SignalSourceConfig
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.testing import create_synced_table_from_rows
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

_STRING = {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}
_INTEGER = {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)", "valid": True}
_COLUMNS = {
    "id": _STRING,
    "identifier": _STRING,
    "title": _STRING,
    "url": _STRING,
    "created_at": _STRING,
    "priority": _INTEGER,
    "team": _STRING,
    "project": _STRING,
    "assignee": _STRING,
    "state": _STRING,
    "labels": _STRING,
}
_ALLOWED_TEAM = "linear-team-a"


def _issue(
    issue_id: str,
    *,
    days_ago: int = 1,
    linear_team: str = _ALLOWED_TEAM,
    project: str = '{"id": "p1", "name": "Core"}',
    assignee: str = "",
    state_type: str = "unstarted",
) -> list[object]:
    created_at = (timezone.now() - timedelta(days=days_ago)).isoformat()
    return [
        issue_id,
        f"ENG-{issue_id}",
        f"Issue {issue_id}",
        f"https://linear.example.com/issue/{issue_id}",
        created_at,
        2,
        json.dumps({"id": linear_team}),
        project,
        assignee,
        json.dumps({"type": state_type}),
        json.dumps({"nodes": [{"name": "bug"}]}),
    ]


class TestSourceFilterPreview(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        SignalFilterSourceDefinition.publish(
            source_product=LINEAR_ISSUE_SEED.source_product,
            source_type=LINEAR_ISSUE_SEED.source_type,
            adapter_kind=LINEAR_ISSUE_SEED.adapter_kind,
            initial_rollout_state=LINEAR_ISSUE_SEED.initial_rollout_state,
            bundle=LINEAR_ISSUE_SEED.bundle,
        )
        source = SignalFilterSourceDefinition.objects.get(source_product="linear", source_type="issue")
        source.filter_query_eligible = True
        source.save()
        flag = patch("products.signals.backend.source_filters.feature_enabled_or_false", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _preview(self, expression: str) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/source_configs/filter_preview/",
            {"source_product": "linear", "source_type": "issue", "expression": expression},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def _linear_issues(self, rows: list[list[object]]) -> None:
        create_synced_table_from_rows(
            self.team,
            source_type=ExternalDataSourceType.LINEAR,
            schema_name="issues",
            table_name="linear_issues",
            columns=_COLUMNS,
            rows=rows,
            descriptions={},
            test_bucket="test_signal_source_filter_preview",
        )

    def test_preview_counts_the_records_emission_would_read(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="linear", source_type="issue", config={"linear_team_ids": [_ALLOWED_TEAM]}
        )
        self._linear_issues(
            [
                _issue("passes"),
                _issue("assigned", assignee='{"id": "u1"}'),
                _issue("other-project", project='{"id": "p2", "name": "Web"}'),
                _issue("malformed", project="{not json"),
                _issue("completed", state_type="completed"),
                _issue("too-old", days_ago=10),
                _issue("other-team", linear_team="linear-team-b"),
            ]
        )

        preview = self._preview("project_name = 'Core' AND assignee_id IS NULL")

        assert preview["status"] == "ok", preview
        assert (
            preview["total_count"],
            preview["passing_count"],
            preview["excluded_count"],
            preview["malformed_count"],
        ) == (4, 1, 3, 1)
        [passing] = preview["passing"]
        assert passing["id"] == "passes"
        assert passing["identifier"] == "ENG-passes"
        assert passing["field_values"]["project_name"] == "Core"
        assert passing["field_values"]["label_names"] == ["bug"]
        assert passing["field_values"]["assignee_id"] is None
        excluded = {record["id"]: record["malformed"] for record in preview["excluded"]}
        assert excluded == {"assigned": False, "other-project": False, "malformed": True}

    def test_preview_runs_with_the_requesters_warehouse_access(self) -> None:
        self._linear_issues([_issue("passes")])
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(DataWarehouseTable.objects.get(team=self.team, name="linear_issues").id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        with patch(
            "posthog.hogql.database.database.feature_enabled_or_false",
            side_effect=lambda key, *args, **kwargs: key == "hogql-warehouse-access-control",
        ):
            preview = self._preview("")

        assert preview["status"] == "access_denied"
        assert (preview["total_count"], preview["passing"], preview["excluded"]) == (0, [], [])

    @parameterized.expand(
        [
            ("unknown_field", "category = 'Core'", "invalid_expression"),
            ("no_linear_import", "project_name = 'Core'", "not_connected"),
        ]
    )
    def test_preview_reports_why_it_has_no_records(self, _name: str, expression: str, expected_status: str) -> None:
        preview = self._preview(expression)

        assert preview["status"] == expected_status
        assert preview["total_count"] == 0

    def test_preview_is_refused_where_the_filter_cannot_be_saved(self) -> None:
        with patch("products.signals.backend.source_filters.feature_enabled_or_false", return_value=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/source_configs/filter_preview/",
                {"source_product": "linear", "source_type": "issue", "expression": ""},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
