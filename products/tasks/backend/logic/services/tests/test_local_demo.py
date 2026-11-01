from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from products.tasks.backend.facade.local_demo import local_demo_task_ids, seed_local_demo_task
from products.tasks.backend.models import Task, TaskRun


@override_settings(
    DEBUG=True,
    CLOUD_DEPLOYMENT=None,
    SITE_URL="http://localhost:8010",
    OBJECT_STORAGE_ENABLED=True,
    OBJECT_STORAGE_ENDPOINT="http://localhost:19000",
    OBJECT_STORAGE_BUCKET="posthog",
)
class TestLocalDemoStorage(BaseTest):
    @parameterized.expand(
        [
            ("disabled", False, "require object storage"),
            ("no_op", True, "did not persist the demo chat log"),
        ]
    )
    def test_unavailable_storage_creates_no_task_or_run(self, _name: str, enabled: bool, message: str) -> None:
        with (
            override_settings(OBJECT_STORAGE_ENABLED=enabled),
            patch("posthog.storage.object_storage.read", return_value=None),
            patch("posthog.storage.object_storage.write"),
            self.assertRaisesMessage(CommandError, message),
        ):
            call_command("seed_local_inbox_data", team_id=self.team.id, user_id=self.user.id)

        assert not Task.objects.filter(team_id=self.team.id).exists()
        assert not TaskRun.objects.filter(team_id=self.team.id).exists()

    def test_storage_failure_preserves_existing_demo_rows_and_retry_reuses_them(self) -> None:
        storage: dict[str, str] = {}

        def read(path: str, **kwargs: object) -> str | None:
            return storage.get(path)

        def write(path: str, content: str, **kwargs: object) -> None:
            storage[path] = content

        with (
            patch("posthog.storage.object_storage.read", side_effect=read),
            patch("posthog.storage.object_storage.write", side_effect=write),
        ):
            seeded = seed_local_demo_task(team_id=self.team.id, user_id=self.user.id)
        assert seeded == local_demo_task_ids(team_id=self.team.id, user_id=self.user.id)
        Task.objects.filter(team_id=self.team.id, id=seeded.task_id).update(title="Edited demo title")
        TaskRun.objects.filter(team_id=self.team.id, id=seeded.run_id).update(stage="review")

        with (
            patch("posthog.storage.object_storage.read", return_value=None),
            patch("posthog.storage.object_storage.write"),
            self.assertRaisesMessage(CommandError, "did not persist the demo chat log"),
        ):
            call_command("seed_local_inbox_data", team_id=self.team.id, user_id=self.user.id)

        assert Task.objects.filter(team_id=self.team.id).count() == 1
        assert TaskRun.objects.filter(team_id=self.team.id).count() == 1
        assert Task.objects.get(team_id=self.team.id, id=seeded.task_id).title == "Edited demo title"
        assert TaskRun.objects.get(team_id=self.team.id, id=seeded.run_id).stage == "review"
        with (
            patch("posthog.storage.object_storage.read", side_effect=read),
            patch("posthog.storage.object_storage.write") as writes,
        ):
            assert seed_local_demo_task(team_id=self.team.id, user_id=self.user.id) == seeded
        writes.assert_not_called()
