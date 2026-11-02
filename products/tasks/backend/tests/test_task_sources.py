from typing import Any
from uuid import UUID

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport
from products.tasks.backend.facade.profiles import SourceKind
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.task_sources import idempotency_key_q, idempotency_key_startswith_q, source_q

REPORT_ID = UUID("11111111-1111-4111-8111-111111111111")
FLOW_ID = UUID("22222222-2222-4222-8222-222222222222")


class TestStoredSource(SimpleTestCase):
    @parameterized.expand(
        [
            ("neither", {}, None, None),
            ("report_in_old_column", {"signal_report_id": REPORT_ID}, REPORT_ID, None),
            ("flow_in_old_column", {"hog_flow_id": FLOW_ID}, None, FLOW_ID),
            ("report_in_new_columns", {"source_kind": "signal_report", "source_id": str(REPORT_ID)}, REPORT_ID, None),
            ("flow_in_new_columns", {"source_kind": "hog_flow", "source_id": str(FLOW_ID)}, None, FLOW_ID),
            (
                "new_columns_win_over_old",
                {"source_kind": "hog_flow", "source_id": str(FLOW_ID), "signal_report_id": REPORT_ID},
                None,
                FLOW_ID,
            ),
            (
                "loop_hides_the_old_report",
                {"source_kind": "loop", "source_id": "loop-1", "signal_report_id": REPORT_ID},
                None,
                None,
            ),
            ("kind_without_id_falls_back", {"source_kind": "hog_flow", "hog_flow_id": FLOW_ID}, None, FLOW_ID),
        ]
    )
    def test_reads_the_new_columns_and_falls_back_to_the_old_ones(
        self, _name: str, columns: dict, report_id: UUID | None, flow_id: UUID | None
    ) -> None:
        task = Task(**columns)

        self.assertEqual((task.signal_report_source_id, task.hog_flow_source_id), (report_id, flow_id))

    @parameterized.expand(
        [
            ("neither", {}, None),
            ("old_column_only", {"origin_key": "old"}, "old"),
            ("new_column_only", {"idempotency_key": "new"}, "new"),
            ("new_column_wins", {"origin_key": "old", "idempotency_key": "new"}, "new"),
        ]
    )
    def test_reads_the_idempotency_key_and_falls_back_to_the_origin_key(
        self, _name: str, columns: dict, expected: str | None
    ) -> None:
        self.assertEqual(Task(**columns).stored_idempotency_key, expected)


class TestSourceQueries(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = Team.objects.create(organization=Organization.objects.create(name="Org"), name="Team")
        SignalReport.objects.create(team=self.team, id=REPORT_ID)
        rows: dict[str, dict[str, Any]] = {
            "neither": {},
            "report_old": {"signal_report_id": REPORT_ID, "origin_key": "scout-trial:report_old"},
            "report_new": {
                "source_kind": "signal_report",
                "source_id": str(REPORT_ID),
                "idempotency_key": "scout-trial:report_new",
            },
            "report_both": {
                "signal_report_id": REPORT_ID,
                "source_kind": "signal_report",
                "source_id": str(REPORT_ID),
                "origin_key": "scout-trial:report_both",
                "idempotency_key": "scout-trial:report_both",
            },
            "flow_old": {"hog_flow_id": FLOW_ID},
            "flow_new": {"source_kind": "hog_flow", "source_id": str(FLOW_ID)},
            "flow_over_old_report": {
                "signal_report_id": REPORT_ID,
                "source_kind": "hog_flow",
                "source_id": str(FLOW_ID),
                "origin_key": "scout-trial:stale",
                "idempotency_key": "other:fresh",
            },
        }
        self.tasks = {
            name: Task.objects.create(
                team=self.team,
                title=name,
                description="d",
                origin_product=Task.OriginProduct.USER_CREATED,
                **columns,
            )
            for name, columns in rows.items()
        }

    def _names(self, queryset_filter) -> set[str]:
        return {task.title for task in Task.objects.filter(queryset_filter)}

    @parameterized.expand(
        [
            (
                "report",
                SourceKind.SIGNAL_REPORT,
                REPORT_ID,
                {"report_old", "report_new", "report_both"},
            ),
            ("flow", SourceKind.HOG_FLOW, FLOW_ID, {"flow_old", "flow_new", "flow_over_old_report"}),
            ("flow_id_under_the_report_kind", SourceKind.SIGNAL_REPORT, FLOW_ID, set()),
            ("loop_has_no_old_column", SourceKind.LOOP, REPORT_ID, set()),
        ]
    )
    def test_source_q_matches_new_and_old_columns_by_kind(
        self, _name: str, kind: SourceKind, source_id: UUID, expected: set[str]
    ) -> None:
        self.assertEqual(self._names(source_q(kind, [source_id])), expected)

    def test_source_q_follows_a_relation(self) -> None:
        for task in self.tasks.values():
            TaskRun.objects.create(task=task, team=self.team)

        runs = TaskRun.objects.filter(source_q(SourceKind.SIGNAL_REPORT, [REPORT_ID], via="task__"))

        self.assertEqual({run.task.title for run in runs}, {"report_old", "report_new", "report_both"})

    @parameterized.expand(
        [
            ("old_column", "scout-trial:report_old", {"report_old"}),
            ("new_column", "scout-trial:report_new", {"report_new"}),
            ("both_columns", "scout-trial:report_both", {"report_both"}),
            ("old_value_hidden_by_new", "scout-trial:stale", set()),
            ("new_value", "other:fresh", {"flow_over_old_report"}),
            ("unknown", "missing", set()),
        ]
    )
    def test_idempotency_key_q_matches_new_and_old_columns(self, _name: str, key: str, expected: set[str]) -> None:
        self.assertEqual(self._names(idempotency_key_q(key)), expected)

    def test_idempotency_key_startswith_q_matches_new_and_old_columns(self) -> None:
        self.assertEqual(
            self._names(idempotency_key_startswith_q("scout-trial:")),
            {"report_old", "report_new", "report_both"},
        )
