from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import EntityDependency
from posthog.models.entity_dependencies.types import Reference

from products.workflows.backend.entity_dependencies import HogFlowDependencySource
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _cohort(cohort_id: Any) -> dict[str, Any]:
    return {"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}


def _trigger(trigger_type: str, filters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "trigger", "config": {"type": trigger_type, "filters": filters}}


def _ref(cohort_id: str, role: str, path: str) -> Reference:
    return Reference(target_type="cohort", target_id=cohort_id, role=role, path=path)


class TestHogFlowDependencySourceExtraction(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "event_trigger_filters_including_per_event_properties",
                {
                    "trigger": _trigger(
                        "event",
                        {"events": [{"id": "$pageview", "properties": [_cohort(7)]}], "properties": [_cohort(5)]},
                    )
                },
                {
                    _ref("7", "trigger_filter", "trigger.config.filters.events[0].properties[0]"),
                    _ref("5", "trigger_filter", "trigger.config.filters.properties[0]"),
                },
            ),
            (
                "batch_audience_with_string_id",
                {"trigger": _trigger("batch", {"properties": [_cohort("9")]})},
                {_ref("9", "trigger_audience", "trigger.config.filters.properties[0]")},
            ),
            (
                "schedule_audience",
                {"trigger": _trigger("schedule", {"properties": [_cohort(2)]})},
                {_ref("2", "trigger_audience", "trigger.config.filters.properties[0]")},
            ),
            (
                "conditional_branch_conditions",
                {
                    "actions": [
                        {
                            "id": "a1",
                            "type": "conditional_branch",
                            "config": {
                                "conditions": [
                                    {"filters": {"properties": []}},
                                    {"filters": {"properties": [_cohort(3)]}},
                                ]
                            },
                        }
                    ]
                },
                {_ref("3", "branch_condition", "actions[a1].config.conditions[1].filters.properties[0]")},
            ),
            (
                "wait_until_condition",
                {
                    "actions": [
                        {
                            "id": "w1",
                            "type": "wait_until_condition",
                            "config": {
                                "condition": {"filters": {"properties": [_cohort(4)]}},
                                "max_wait_duration": "1d",
                            },
                        }
                    ]
                },
                {_ref("4", "wait_condition", "actions[w1].config.condition.filters.properties[0]")},
            ),
            (
                "conversion_property_filters_and_event_goals",
                {"conversion": {"filters": [_cohort(6)], "events": [{"filters": {"properties": [_cohort(8)]}}]}},
                {
                    _ref("6", "conversion", "conversion.filters[0]"),
                    _ref("8", "conversion", "conversion.events[0].filters.properties[0]"),
                },
            ),
            (
                "draft_content_gets_the_draft_prefix",
                {
                    "draft": {
                        "trigger": _trigger("batch", {"properties": [_cohort(11)]}),
                        "actions": [],
                        "conversion": None,
                    }
                },
                {_ref("11", "draft:trigger_audience", "draft.trigger.config.filters.properties[0]")},
            ),
            (
                "multi_value_cohort_filter_yields_one_reference_per_cohort",
                {"trigger": _trigger("event", {"properties": [_cohort([1, 2])]})},
                {
                    _ref("1", "trigger_filter", "trigger.config.filters.properties[0]"),
                    _ref("2", "trigger_filter", "trigger.config.filters.properties[0]"),
                },
            ),
            (
                "random_cohort_branch_buckets_are_not_cohorts",
                {
                    "actions": [
                        {
                            "id": "r1",
                            "type": "random_cohort_branch",
                            "config": {"cohorts": [{"percentage": 50}, {"percentage": 50}]},
                        }
                    ]
                },
                set(),
            ),
            (
                "non_numeric_cohort_values_are_skipped",
                {"trigger": _trigger("event", {"properties": [_cohort("not-an-id"), _cohort(True), _cohort(None)]})},
                set(),
            ),
            (
                "archived_workflows_have_no_references",
                {"status": HogFlow.State.ARCHIVED, "trigger": _trigger("batch", {"properties": [_cohort(5)]})},
                set(),
            ),
        ]
    )
    def test_extract_references(self, _name: str, fields: dict[str, Any], expected: set[Reference]) -> None:
        flow = HogFlow(team_id=1, name="Flow", **fields)

        assert set(HogFlowDependencySource().extract_references(flow)) == expected


class TestHogFlowDependencyWiring(BaseTest):
    def _rows(self) -> set[tuple[str, str, str]]:
        rows = EntityDependency.objects.for_team(self.team.id).filter(source_type="hog_flow")
        return {(row.source_id, row.target_id, row.role) for row in rows}

    def test_saving_a_workflow_records_its_cohort_references_and_archiving_removes_them(self) -> None:
        flow = HogFlow.objects.create(
            team=self.team, name="Flow", trigger=_trigger("batch", {"properties": [_cohort(5)]})
        )
        assert self._rows() == {(str(flow.id), "5", "trigger_audience")}

        flow.status = HogFlow.State.ARCHIVED
        flow.save()
        assert self._rows() == set()

    def test_backfill_command_rebuilds_rows_that_signals_did_not_write(self) -> None:
        HogFlow.objects.create(team=self.team, name="A", trigger=_trigger("batch", {"properties": [_cohort(5)]}))
        HogFlow.objects.create(team=self.team, name="B", conversion={"filters": [_cohort(6)], "events": []})
        HogFlow.objects.create(team=self.team, name="C")
        EntityDependency.objects.for_team(self.team.id).filter(source_type="hog_flow").delete()

        dry_run = StringIO()
        call_command(
            "backfill_entity_dependencies", "--source-type", "hog_flow", "--team-id", self.team.id, stdout=dry_run
        )
        assert "3 hog_flow scanned, 2 rows added (would be), 0 rows removed (would be), 0 errors" in dry_run.getvalue()
        assert self._rows() == set()

        live_run = StringIO()
        call_command(
            "backfill_entity_dependencies",
            "--source-type",
            "hog_flow",
            "--team-id",
            self.team.id,
            "--live-run",
            stdout=live_run,
        )
        assert "2 rows added, 0 rows removed, 0 errors" in live_run.getvalue()
        assert {(target, role) for _, target, role in self._rows()} == {("5", "trigger_audience"), ("6", "conversion")}

        rerun = StringIO()
        call_command(
            "backfill_entity_dependencies",
            "--source-type",
            "hog_flow",
            "--team-id",
            self.team.id,
            "--live-run",
            stdout=rerun,
        )
        assert "0 rows added, 0 rows removed, 0 errors" in rerun.getvalue()
