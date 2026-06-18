from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

# skipped in CI because migration tests are slow; passes locally.
# To run it, comment this out: `hogli test products/tasks/backend/migrations/test/test_migration_0039.py`
pytestmark = pytest.mark.skip("historical migration tests slow overall test run")


class DedupeSandboxEnvironmentsMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0038_task_origin_product_conversations_support"
    migrate_to = "0039_dedupe_sandbox_environments"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "tasks"

    def setUp(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        migrate_from_targets = [
            ("tasks", self.migrate_from),
            ("posthog", "1166_oauth_impersonated_by"),
        ]
        migrate_to_targets = [("tasks", self.migrate_to)]

        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(migrate_from_targets).apps
        executor.migrate(migrate_from_targets)

        self.setUpBeforeMigration(old_apps)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(migrate_to_targets)

        self.apps = executor.loader.project_state(migrate_to_targets).apps

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=987654, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")
        self.team_id = team.id

        # No unique constraint at state 0037, so duplicates can be inserted directly.
        def make(name, internal, created_at):
            env = SandboxEnvironment.objects.create(team=team, name=name, internal=internal)
            SandboxEnvironment.objects.filter(id=env.id).update(created_at=created_at)
            return env

        self.internal_old = make("SIGNALS_REPO_DISCOVERY", True, "2024-01-01T00:00:00Z")
        self.internal_new = make("SIGNALS_REPO_DISCOVERY", True, "2024-02-01T00:00:00Z")
        self.user_old = make("staging", False, "2024-01-01T00:00:00Z")
        self.user_new = make("staging", False, "2024-02-01T00:00:00Z")
        self.singleton = make("prod", False, "2024-01-01T00:00:00Z")

        task = Task.objects.create(team=team, title="t", description="", origin_product="signal_report")
        self.task_run = TaskRun.objects.create(
            task=task, team=team, state={"sandbox_environment_id": str(self.internal_old.id)}
        )

    def test_keeps_most_recent_row_per_group(self):
        assert self.apps is not None
        SandboxEnvironment = self.apps.get_model("tasks", "SandboxEnvironment")
        internal = SandboxEnvironment.objects.filter(team_id=self.team_id, name="SIGNALS_REPO_DISCOVERY")
        user = SandboxEnvironment.objects.filter(team_id=self.team_id, name="staging")
        self.assertEqual(list(internal.values_list("id", flat=True)), [self.internal_new.id])
        self.assertEqual(list(user.values_list("id", flat=True)), [self.user_new.id])

    def test_repoints_references_to_keeper(self):
        assert self.apps is not None
        TaskRun = self.apps.get_model("tasks", "TaskRun")
        run = TaskRun.objects.get(id=self.task_run.id)
        self.assertEqual(run.state["sandbox_environment_id"], str(self.internal_new.id))

    def test_leaves_singleton_untouched(self):
        assert self.apps is not None
        SandboxEnvironment = self.apps.get_model("tasks", "SandboxEnvironment")
        self.assertTrue(SandboxEnvironment.objects.filter(id=self.singleton.id).exists())
