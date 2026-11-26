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
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppRefreshRun, NotebookAppSchedule
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

    def test_old_worker_cannot_replace_new_schedule(self):
        schedule = self.configure()
        run = self.slot(schedule)
        configure(self.team.pk, self.notebook.pk, self.user.pk, 3, 120, 180, True)
        run_slot(self.team.pk, run.pk)
        run.refresh_from_db()
        schedule.refresh_from_db()
        assert run.status == "failed"
        assert schedule.last_success_at is None
