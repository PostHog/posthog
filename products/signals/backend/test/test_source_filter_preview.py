import json
from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.emission.linear_issues import EXTRA_FIELDS, LINEAR_ISSUES_CONFIG, linear_issue_emitter
from products.signals.backend.filter_catalog import SignalFilterSourceDefinition
from products.signals.backend.filter_catalog_seeds import LINEAR_ISSUE_SEED
from products.signals.backend.models import SignalSourceConfig
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_synced_table_from_rows
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

_STRING: dict[str, str | bool] = {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}
_INTEGER: dict[str, str | bool] = {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)", "valid": True}
_COLUMNS: dict[str, dict[str, str | bool]] = {
    "id": _STRING,
    "identifier": _STRING,
    "title": _STRING,
    "description": _STRING,
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
    description: str | None = "Exports time out on large projects",
) -> list[object]:
    created_at = (timezone.now() - timedelta(days=days_ago)).isoformat()
    return [
        issue_id,
        f"ENG-{issue_id}",
        f"Issue {issue_id}",
        description,
        f"https://linear.example.com/issue/{issue_id}",
        created_at,
        2,
        json.dumps({"id": linear_team}),
        project,
        assignee,
        json.dumps({"type": state_type}),
        json.dumps({"nodes": [{"name": "bug"}]}),
    ]


class _LinearSourceFilterTest(APIBaseTest):
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

    def _post(self, action: str, expression: str, **extra_body: object) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/signals/source_configs/{action}/",
            {"source_product": "linear", "source_type": "issue", "expression": expression, **extra_body},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()


class TestSourceFilterPreview(ClickhouseTestMixin, _LinearSourceFilterTest):
    def _preview(self, expression: str, **extra_body: object) -> dict:
        return self._post("filter_preview", expression, **extra_body)

    def _linear_issues(self, rows: list[list[object]], columns: dict[str, dict[str, str | bool]] = _COLUMNS) -> None:
        create_synced_table_from_rows(
            self.team,
            source_type=ExternalDataSourceType.LINEAR,
            schema_name="issues",
            table_name="linear_issues",
            columns=columns,
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
        assert passing["failed_conditions"] is None
        excluded = {record["id"]: (record["malformed"], record["failed_conditions"]) for record in preview["excluded"]}
        assert excluded == {
            "assigned": (False, ["assignee_id IS NULL"]),
            "other-project": (False, ["project_name = 'Core'"]),
            "malformed": (True, ["project_name = 'Core'"]),
        }

    def test_preview_lists_failed_conditions_only_for_a_top_level_and(self) -> None:
        self._linear_issues([_issue("assigned", assignee='{"id": "u1"}')])

        def failed_conditions(expression: str) -> list[str] | None:
            [excluded] = self._preview(expression)["excluded"]
            return excluded["failed_conditions"]

        assert failed_conditions("(project_name = 'Web' OR priority = 1) AND assignee_id IS NULL") == [
            "project_name = 'Web' OR priority = 1",
            "assignee_id IS NULL",
        ]
        assert failed_conditions("project_name = 'Web' OR assignee_id IS NULL") is None
        assert failed_conditions(" AND ".join(["priority = 2"] * 8 + ["assignee_id IS NULL"])) is None
        assert failed_conditions("\ufeffproject_name = 'Web' AND assignee_id IS NULL") is None

    def test_preview_leaves_out_the_records_the_emitter_skips(self) -> None:
        """The CSV fixture can't hold '' apart from null, so the parity test below covers the empty string."""
        self._linear_issues(
            [_issue("described"), _issue("whitespace", description="\n "), _issue("missing", description=None)]
        )

        preview = self._preview("")

        assert preview["total_count"] == 2
        assert {record["id"] for record in preview["passing"] + preview["excluded"]} == {"described", "whitespace"}

    def test_linear_emittable_where_keeps_what_the_emitter_keeps(self) -> None:
        descriptions = [None, "", " ", "\n", "Exports time out"]
        assert LINEAR_ISSUES_CONFIG.emittable_where is not None
        response = execute_hogql_query(
            parse_select(
                "SELECT description, {emittable} FROM (SELECT arrayJoin({descriptions}) AS description)",
                placeholders={
                    "emittable": parse_expr(LINEAR_ISSUES_CONFIG.emittable_where),
                    "descriptions": ast.Array(exprs=[ast.Constant(value=description) for description in descriptions]),
                },
            ),
            team=self.team,
        )

        kept_by_hogql = {description for description, kept in response.results if kept}
        kept_by_emitter = {
            description
            for description in descriptions
            if linear_issue_emitter(
                self.team.pk, {**dict.fromkeys(EXTRA_FIELDS), "id": "1", "title": "Issue", "description": description}
            )
        }
        assert kept_by_hogql == kept_by_emitter

    @parameterized.expand(
        [
            ("absent_uses_saved_allowlist", {}, {"in-allowed-team"}),
            ("null_uses_saved_allowlist", {"scope_ids": None}, {"in-allowed-team"}),
            ("empty_reads_every_team", {"scope_ids": []}, {"in-allowed-team", "in-other-team"}),
            ("list_replaces_saved_allowlist", {"scope_ids": [" linear-team-b "]}, {"in-other-team"}),
        ]
    )
    def test_preview_reads_the_requested_team_allowlist(
        self, _name: str, extra_body: dict[str, object], expected_ids: set[str]
    ) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="linear", source_type="issue", config={"linear_team_ids": [_ALLOWED_TEAM]}
        )
        self._linear_issues([_issue("in-allowed-team"), _issue("in-other-team", linear_team="linear-team-b")])

        preview = self._preview("", **extra_body)

        assert preview["status"] == "ok", preview
        assert {record["id"] for record in preview["passing"]} == expected_ids

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
            ("unknown_field", "category = 'Core'", None, "invalid_expression", ("unknown_field", 0, 8)),
            ("syntax", "project_name = ", None, "invalid_expression", ("syntax", 15, 15)),
            ("type", "priority = 'high'", None, "invalid_expression", ("type", 0, 17)),
            ("no_linear_import", "project_name = 'Core'", None, "not_connected", (None, None, None)),
            ("first_sync_pending", "project_name = 'Core'", "no_table", "not_synced", (None, None, None)),
            (
                "import_lacks_a_bound_column",
                "project_name = 'Core'",
                "no_labels_column",
                "incompatible_table",
                (None, None, None),
            ),
        ]
    )
    def test_preview_reports_why_it_has_no_records(
        self,
        _name: str,
        expression: str,
        linear_import: str | None,
        expected_status: str,
        expected_error: tuple[str | None, int | None, int | None],
    ) -> None:
        if linear_import == "no_table":
            source = ExternalDataSource.objects.create(
                team=self.team,
                source_id="linear_source",
                connection_id="linear_connection",
                status=ExternalDataSource.Status.RUNNING,
                source_type=ExternalDataSourceType.LINEAR,
            )
            ExternalDataSchema.objects.create(team=self.team, name="issues", source=source, should_sync=True)
        elif linear_import == "no_labels_column":
            columns = {name: column for name, column in _COLUMNS.items() if name != "labels"}
            self._linear_issues([_issue("passes")[:-1]], columns=columns)

        preview = self._preview(expression)

        assert preview["status"] == expected_status
        assert preview["total_count"] == 0
        assert (preview["error_code"], preview["error_start"], preview["error_end"]) == expected_error

    @parameterized.expand(
        [
            ("filter_cannot_be_saved", False, {}, "source_type"),
            ("blank_scope_id", True, {"scope_ids": [_ALLOWED_TEAM, " "]}, "scope_ids"),
            ("too_many_scope_ids", True, {"scope_ids": [f"team-{i}" for i in range(101)]}, "scope_ids"),
            ("scope_id_too_long", True, {"scope_ids": ["t" * 256]}, "scope_ids__0"),
        ]
    )
    def test_preview_is_refused(
        self, _name: str, filter_writable: bool, extra_body: dict[str, object], expected_attr: str
    ) -> None:
        with patch("products.signals.backend.source_filters.feature_enabled_or_false", return_value=filter_writable):
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/source_configs/filter_preview/",
                {"source_product": "linear", "source_type": "issue", "expression": "", **extra_body},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == expected_attr

    def test_validate_reads_no_warehouse_records(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="linear", source_type="issue", config={"linear_team_ids": [_ALLOWED_TEAM]}
        )
        self._linear_issues([_issue("passes")])

        with self.capture_queries(lambda _query: True) as queries:
            validation = self._post("filter_validate", "project_name = 'Core'")

        assert validation["valid"] is True
        assert queries == []

    def test_validate_is_refused_where_the_filter_cannot_be_saved(self) -> None:
        with patch("products.signals.backend.source_filters.feature_enabled_or_false", return_value=False):
            response = self.client.post(
                f"/api/projects/{self.team.id}/signals/source_configs/filter_validate/",
                {"source_product": "linear", "source_type": "issue", "expression": ""},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "source_type"

    @parameterized.expand(
        [
            ("filter_preview", "SourceFilterPreviewBurstThrottle"),
            ("filter_validate", "SourceFilterValidateBurstThrottle"),
        ]
    )
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_check_throttles_session_requests(self, action: str, throttle: str, _rate_limit: object) -> None:
        url = f"/api/projects/{self.team.id}/signals/source_configs/{action}/"
        body = {"source_product": "linear", "source_type": "issue", "expression": ""}

        with patch(f"products.signals.backend.throttles.{throttle}.rate", new="1/minute"):
            first = self.client.post(url, body, format="json")
            second = self.client.post(url, body, format="json")

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS


class TestSourceFilterValidate(_LinearSourceFilterTest):
    @parameterized.expand(
        [
            ("valid", "project_name = 'Core' AND assignee_id IS NULL", (None, None, None)),
            ("blank", "  ", (None, None, None)),
            ("unknown_field", "category = 'Core'", ("unknown_field", 0, 8)),
            ("syntax", "project_name = ", ("syntax", 15, 15)),
            ("too_long", "project_name = 'Core' OR " * 200, ("expression_limit", None, None)),
        ]
    )
    def test_validate_checks_the_expression_against_the_active_catalog(
        self, _name: str, expression: str, expected_error: tuple[str | None, int | None, int | None]
    ) -> None:
        catalog = SignalFilterSourceDefinition.objects.get(source_product="linear", source_type="issue")
        assert catalog.active_catalog_version is not None

        validation = self._post("filter_validate", expression)

        assert validation["valid"] is (expected_error[0] is None)
        assert validation["catalog_version"] == catalog.active_catalog_version.version
        assert (validation["error"] is None) is validation["valid"]
        assert (validation["error_code"], validation["error_start"], validation["error_end"]) == expected_error
