from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from posthog.hogql.context import HogQLContext

from products.notebooks.backend.app_refresh import (
    configure,
    notify_owner,
    read_outputs,
    refresh_status,
    result_scope,
    run_slot,
)
from products.notebooks.backend.markdown_conversion import (
    build_markdown_notebook_content,
    get_markdown_notebook_markdown,
)
from products.notebooks.backend.models import Notebook, NotebookAppRefreshRun, NotebookAppRelease, NotebookAppSchedule
from products.notebooks.backend.tasks.app_refresh import dispatch_notebook_app_refreshes
from products.notifications.backend.models import NotificationEvent


class TestAppRefresh(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            app_revision=3,
            content=build_markdown_notebook_content('<SQLV2 nodeId="signups" code="SELECT 1 AS signups" />'),
            app_published={
                "tabs": [{"id": "overview", "title": "Overview"}],
                "blocks": [{"id": "b", "kind": "cell", "node_id": "signups", "tab_id": "overview"}],
            },
        )
        self.url = f"/api/projects/{self.team.pk}/notebooks/{self.notebook.short_id}/app_refresh_schedule/"
        self.schedule_payload = {"revision": 3, "enabled": True, "interval_minutes": 60, "freshness_minutes": 90}

    def configure(self) -> NotebookAppSchedule:
        configure(self.team.pk, self.notebook.pk, self.user.pk, 3, 60, 90, True)
        return NotebookAppSchedule.objects.for_team(self.team.pk).get(notebook=self.notebook)

    def slot(self, schedule: NotebookAppSchedule) -> NotebookAppRefreshRun:
        return NotebookAppRefreshRun.objects.for_team(self.team.pk).create(
            team=self.team, schedule=schedule, revision=3, due_at=timezone.now()
        )

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_author_changes_only_the_current_release_and_retries_keep_the_original_due_time(self, _flag):
        assert self.client.post(self.url, {**self.schedule_payload, "revision": 2}, format="json").status_code == 409
        first = self.client.post(self.url, self.schedule_payload, format="json")
        assert first.status_code == 200, first.json()
        assert first.json()["published_revision"] == 3
        assert first.json()["history"] == []
        again = self.client.post(self.url, self.schedule_payload, format="json")
        assert again.json()["next_due_at"] == first.json()["next_due_at"]
        stopped = self.client.post(self.url, {**self.schedule_payload, "enabled": False}, format="json")
        assert stopped.status_code == 200
        assert not stopped.json()["enabled"]

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_worker_runs_default_sql_and_restores_the_rows_to_an_authorized_reader(self, _flag):
        schedule = self.configure()
        run = self.slot(schedule)
        run_slot(self.team.pk, run.pk)
        run.refresh_from_db()
        assert run.status == "succeeded", run.detail
        assert read_outputs(self.team.pk, self.notebook.pk, self.user.pk, 3)["signups"].results == [[1]]

    def test_beat_registers_an_expiring_dispatch_task_from_product_discovery(self):
        from celery import current_app

        entry = current_app.conf.beat_schedule["dispatch notebook app refreshes"]
        assert entry["task"] == "products.notebooks.backend.tasks.app_refresh.dispatch_notebook_app_refreshes"
        assert entry["schedule"] == 60
        assert entry["options"]["expires"] == 90

    def test_failed_refresh_retains_last_success_and_duplicate_delivery_does_not_replace_it(self):
        schedule = self.configure()
        success = self.slot(schedule)
        payload = {"signups": {"scope": "fixture", "result": {"columns": ["signups"], "results": [[1]]}}}
        with patch("products.notebooks.backend.app_refresh.refresh_outputs", return_value=payload):
            run_slot(self.team.pk, success.pk)
        with patch("products.notebooks.backend.app_refresh.refresh_outputs", side_effect=PermissionDenied()):
            run_slot(self.team.pk, success.pk)
            run_slot(self.team.pk, self.slot(schedule).pk)
        schedule.refresh_from_db()
        assert schedule.outputs == payload
        assert schedule.last_success_at is not None
        status = refresh_status(self.team.pk, self.notebook.pk)
        assert [item.status for item in status.history] == ["failed", "succeeded"]
        assert status.history[0].detail == "The schedule owner no longer has access."

    def test_scope_includes_bound_values_and_current_permissions(self):
        schedule = self.configure()
        left, right = HogQLContext(), HogQLContext()
        left.values["user"] = 1
        right.values["user"] = 2
        sql = "SELECT signups WHERE owner = %(user)s"
        fingerprint = result_scope(sql, left)
        assert fingerprint != result_scope(sql, right)
        payload = {"columns": ["signups"], "results": [[1]]}
        schedule.outputs = {"signups": {"scope": fingerprint, "result": payload}}
        schedule.last_success_at = timezone.now()
        schedule.save()
        with patch("products.notebooks.backend.app_refresh.query_executor") as executor:
            executor.return_value.direct_sql = None
            executor.return_value.generate_clickhouse_sql.return_value = (sql, right)
            assert read_outputs(self.team.pk, self.notebook.pk, self.user.pk, 3) == {}
            executor.return_value.generate_clickhouse_sql.return_value = (sql, left)
            assert read_outputs(self.team.pk, self.notebook.pk, self.user.pk, 3)["signups"].results == [[1]]
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with pytest.raises(PermissionDenied):
            read_outputs(self.team.pk, self.notebook.pk, self.user.pk, 3)

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    def test_notification_has_one_event_for_the_owner_and_links_to_the_app(self, _flag):
        schedule = self.configure()
        for _ in range(2):
            notify_owner(schedule, "Notebook app refresh failed", f"test:refresh:{schedule.pk}")
        event = NotificationEvent.objects.get(team=self.team, notification_type="notebook_app_refresh")
        assert event.target_id == str(self.user.pk)
        assert event.source_url == f"/project/{self.team.pk}/notebooks/{self.notebook.short_id}?view=app"

    def test_dispatch_claims_one_slot_and_notifies_at_the_freshness_deadline(self):
        schedule = self.configure()
        with (
            patch("products.notebooks.backend.tasks.app_refresh.refresh_notebook_app.delay"),
            patch("products.notebooks.backend.app_refresh.notify_owner") as notify,
        ):
            dispatch_notebook_app_refreshes()
            dispatch_notebook_app_refreshes()
            assert list(NotebookAppRefreshRun.objects.for_team(self.team.pk).values_list("status", flat=True)) == [
                "queued"
            ]
            NotebookAppSchedule.objects.for_team(self.team.pk).filter(pk=schedule.pk).update(
                stale_at=timezone.now() - timedelta(minutes=1), next_due_at=timezone.now() + timedelta(minutes=30)
            )
            with self.captureOnCommitCallbacks(execute=True):
                dispatch_notebook_app_refreshes()
                dispatch_notebook_app_refreshes()
            assert notify.call_count == 1
            assert notify.call_args.args[1] == "Notebook app results are stale"

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_publishing_a_new_release_pauses_the_old_schedule(self, _flag):
        schedule = self.configure()
        self.notebook.app_revision = 4
        self.notebook.save(update_fields=["app_revision"])
        run = self.slot(schedule)
        run_slot(self.team.pk, run.pk)
        run.refresh_from_db()
        schedule.refresh_from_db()
        assert run.detail == "A new release needs a new refresh schedule."
        assert not schedule.enabled
        assert schedule.last_success_at is None

    def publish_private_cells(self):
        self.notebook.content = build_markdown_notebook_content(
            '<PythonV2 nodeId="score" code="print(42)" returnVariable="activation_score" />\n\n'
            '<SQLV2 nodeId="counts" code="SELECT 1" connectionId="test-connection" returnVariable="counts" />\n\n'
            '<PythonV2 nodeId="hidden" code="print(1)" />'
        )
        self.notebook.app_published["blocks"] = [
            {"id": "one", "kind": "cell", "node_id": "score", "tab_id": "overview", "title": "Score"},
            {"id": "two", "kind": "cell", "node_id": "counts", "tab_id": "overview"},
        ]
        self.notebook.save(update_fields=["content", "app_published"])
        NotebookAppRelease.objects.for_team(self.team.pk).create(
            team=self.team,
            notebook=self.notebook,
            revision=3,
            title="Activation",
            variables=[],
            layout=self.notebook.app_published,
            markdown=get_markdown_notebook_markdown(self.notebook.content),
        )

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_opt_in_runs_published_defaults_as_the_owner_and_discards_every_private_result(self, _flag):
        self.publish_private_cells()
        executed = []

        def compute(team_id, notebook_id, user, revision, node_id, inputs):
            executed.append((team_id, notebook_id, user.pk, revision, node_id, inputs))
            return {"columns": ["private"], "rows": [["never persist this row"]]}

        with patch("products.notebooks.backend.app_runtime_checks.run_app_cell", side_effect=compute):
            denied = self.client.post(
                self.url, {**self.schedule_payload, "checked_node_ids": ["hidden"]}, format="json"
            )
            assert denied.status_code == 400
            response = self.client.post(
                self.url, {**self.schedule_payload, "checked_node_ids": ["score", "counts"]}, format="json"
            )
            assert response.status_code == 200, response.json()
            assert {target["node_id"] for target in response.json()["check_targets"]} == {"score", "counts"}
            schedule = NotebookAppSchedule.objects.for_team(self.team.pk).get(notebook=self.notebook)
            run = self.slot(schedule)
            run_slot(self.team.pk, run.pk)
            run_slot(self.team.pk, run.pk)
        state = refresh_status(self.team.pk, self.notebook.pk)
        schedule.refresh_from_db()
        assert executed == [(self.team.pk, self.notebook.pk, self.user.pk, 3, node, {}) for node in ["counts", "score"]]
        assert state.history[0].status == "succeeded"
        assert state.history[0].checked_count == 2
        assert state.history[0].duration_seconds is not None
        assert schedule.outputs == {}
        assert read_outputs(self.team.pk, self.notebook.pk, self.user.pk, 3) == {}

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_private_failure_never_records_the_exception_text_or_a_result(self, _flag):
        self.publish_private_cells()

        def compute(*_args):
            raise ValueError("private output in error text")

        with patch("products.notebooks.backend.app_runtime_checks.run_app_cell", side_effect=compute):
            configure(self.team.pk, self.notebook.pk, self.user.pk, 3, 60, 90, True, ["score"])
            schedule = NotebookAppSchedule.objects.for_team(self.team.pk).get(notebook=self.notebook)
            run_slot(self.team.pk, self.slot(schedule).pk)
        state = refresh_status(self.team.pk, self.notebook.pk)
        assert state.history[0].status == "failed"
        assert state.history[0].detail == "Runtime check failed for score. Open the app and run the cell to inspect it."
        assert state.last_success_at is None

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_owner_losing_access_during_a_run_stops_the_remaining_cells(self, _flag):
        self.publish_private_cells()
        executed = []

        def revoke_after_first(_team, _notebook, owner, _revision, node_id, _inputs):
            executed.append(node_id)
            owner.is_active = False
            owner.save(update_fields=["is_active"])
            return {}

        configure(self.team.pk, self.notebook.pk, self.user.pk, 3, 60, 90, True, ["counts", "score"])
        schedule = NotebookAppSchedule.objects.for_team(self.team.pk).get(notebook=self.notebook)
        with patch("products.notebooks.backend.app_runtime_checks.run_app_cell", side_effect=revoke_after_first):
            run_slot(self.team.pk, self.slot(schedule).pk)
        state = refresh_status(self.team.pk, self.notebook.pk)
        assert executed == ["counts"]
        assert state.history[0].status == "failed"
        assert state.history[0].checked_count == 1

    @patch(
        "products.notebooks.backend.presentation.app_serializers.posthoganalytics.feature_enabled", return_value=True
    )
    def test_legacy_layouts_keep_sql_refresh_and_only_offer_checks_after_republication(self, _flag):
        response = self.client.post(self.url, self.schedule_payload, format="json")
        assert response.status_code == 200
        assert response.json()["check_targets"] == []
        assert response.json()["checked_node_ids"] == []
        response = self.client.post(self.url, {**self.schedule_payload, "checked_node_ids": ["signups"]}, format="json")
        assert response.status_code == 400

    def test_old_worker_cannot_replace_new_schedule(self):
        schedule = self.configure()
        run = self.slot(schedule)
        configure(self.team.pk, self.notebook.pk, self.user.pk, 3, 120, 180, True)
        run_slot(self.team.pk, run.pk)
        run.refresh_from_db()
        schedule.refresh_from_db()
        assert run.status == "failed"
        assert schedule.last_success_at is None
