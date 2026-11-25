import uuid
from io import StringIO

from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorage, object_storage_client

from products.tasks.backend.logic.services.agent_memory import user_memory_prefix
from products.tasks.backend.management.commands import delete_orphaned_task_objects
from products.tasks.backend.management.commands.delete_orphaned_task_objects import (
    OrphanedPrefix,
    delete_prefix,
    prefix_kinds,
)
from products.tasks.backend.models import TaskRun

LIVE_TEAM_ID = 9_100_012
ORPHAN_TEAM_ID = 9_100_01
ORPHAN_ORGANIZATION_ID = "00000000-0000-4000-8000-0000000000aa"


def keys_by_kind(team_id: int, organization_id: str) -> dict[str, set[str]]:
    runs = [TaskRun(id=uuid.uuid4(), team_id=team_id, task_id=uuid.uuid4()) for _ in range(5)]
    return {
        "logs": {run.log_url for run in runs},
        "artifacts": {f"{runs[0].get_artifact_s3_prefix()}/plan.md"},
        "agent-memory": {f"{user_memory_prefix(team_id, 7)}-repo/memory/a.md"},
        "task-sessions": {f"task-sessions/{organization_id}/{runs[0].task_id}/session.jsonl"},
    }


class TestDeleteOrphanedTaskObjects(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(self.settings(OBJECT_STORAGE_ENABLED=True))
        self.enterContext(patch.object(delete_orphaned_task_objects, "PAGE_SIZE", 2))
        storage = object_storage_client()
        assert isinstance(storage, ObjectStorage)
        self.storage = storage
        self.bucket = f"test-orphaned-tasks-{uuid.uuid4().hex[:12]}"
        self.storage.aws_client.create_bucket(Bucket=self.bucket)
        self.addCleanup(self._drop_bucket)

        organization = Organization.objects.create(name="Org")
        Team.objects.create(id=LIVE_TEAM_ID, organization=organization, name="Live")
        assert not Team.objects.filter(id=ORPHAN_TEAM_ID).exists()
        assert not Organization.objects.filter(id=ORPHAN_ORGANIZATION_ID).exists()

        self.orphan_keys_by_kind = keys_by_kind(ORPHAN_TEAM_ID, ORPHAN_ORGANIZATION_ID)
        self.orphan_keys = set().union(*self.orphan_keys_by_kind.values()) | {"tasks/logs/team_99999999999/x.jsonl"}
        self.live_keys = set().union(*keys_by_kind(LIVE_TEAM_ID, str(organization.id)).values()) | {
            f"tasks/billing/team_{ORPHAN_TEAM_ID}/usage.json",
            f"tasks/autoresearch/{ORPHAN_TEAM_ID}/notes.md",
            "tasks/logs/not-a-team/x.jsonl",
        }
        for key in self.live_keys | self.orphan_keys:
            self.storage.aws_client.put_object(Bucket=self.bucket, Key=key, Body=b"x")

    def _drop_bucket(self) -> None:
        keys = self._keys()
        if keys:
            self.storage.delete_objects(self.bucket, list(keys))
        self.storage.aws_client.delete_bucket(Bucket=self.bucket)

    def _keys(self) -> set[str]:
        return set(self.storage.iter_keys(self.bucket, ""))

    def _run(self, *args: str) -> str:
        stdout = StringIO()
        call_command("delete_orphaned_task_objects", "--bucket", self.bucket, *args, stdout=stdout, stderr=StringIO())
        return stdout.getvalue()

    @parameterized.expand([("execute", ["--execute"], "Deleted", True), ("dry_run", [], "Would delete", False)])
    def test_deletes_only_orphaned_prefixes(self, _name: str, args: list[str], verb: str, deletes: bool) -> None:
        output = self._run(*args)

        assert self._keys() == (self.live_keys if deletes else self.live_keys | self.orphan_keys)
        assert f"{verb} 9 objects (9 bytes) under 5 orphaned prefixes" in output

    @parameterized.expand([("kind", ["--kind", "task-sessions"], "task-sessions"), ("limit", ["--limit", "1"], "logs")])
    def test_rollout_flags_narrow_what_is_deleted(self, _name: str, args: list[str], deleted_kind: str) -> None:
        self._run("--execute", *args)

        assert self._keys() == (self.live_keys | self.orphan_keys) - self.orphan_keys_by_kind[deleted_kind]

    def test_failed_deletes_are_kept_and_reported(self) -> None:
        stuck_key = sorted(self.orphan_keys_by_kind["logs"])[0]
        delete_objects = self.storage.delete_objects

        def delete_all_but_stuck(bucket: str, keys: list[str]) -> list[str]:
            return delete_objects(bucket, [key for key in keys if key != stuck_key]) + [
                key for key in keys if key == stuck_key
            ]

        with patch.object(self.storage, "delete_objects", side_effect=delete_all_but_stuck):
            with self.assertRaisesMessage(CommandError, "1 objects failed"):
                self._run("--execute")

        assert self._keys() == self.live_keys | {stuck_key}

    def test_owner_created_after_listing_keeps_its_objects(self) -> None:
        logs = next(kind for kind in prefix_kinds() if kind.name == "logs")
        orphan = OrphanedPrefix(kind=logs, owner_id=str(ORPHAN_TEAM_ID), prefix=f"tasks/logs/team_{ORPHAN_TEAM_ID}/")
        Team.objects.create(id=ORPHAN_TEAM_ID, organization=Organization.objects.create(name="Late"), name="Late")

        outcome = delete_prefix(self.storage, self.bucket, orphan, execute=True)

        assert outcome.owner_reappeared
        assert self._keys() == self.live_keys | self.orphan_keys
