import uuid
import dataclasses

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.storage.object_storage import ObjectStorage, object_storage_client

from products.tasks.backend.logic.services import orphaned_objects
from products.tasks.backend.logic.services.agent_memory import user_memory_prefix
from products.tasks.backend.logic.services.orphaned_objects import (
    KIND_NAMES,
    OrphanedObjectsTotals,
    OrphanedPrefix,
    clean_orphaned_prefixes,
    delete_prefix,
    prefix_kinds,
)
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.orphaned_objects.workflow import resume_totals

LIVE_TEAM_ID = 9_100_012
ORPHAN_TEAM_ID = 910_001
ORPHAN_ORGANIZATION_ID = "00000000-0000-4000-8000-0000000000aa"
OVERFLOWING_TEAM_KEY = "tasks/logs/team_99999999999/x.jsonl"


def keys_by_kind(team_id: int, organization_id: str) -> dict[str, set[str]]:
    runs = [TaskRun(id=uuid.uuid4(), team_id=team_id, task_id=uuid.uuid4()) for _ in range(5)]
    return {
        "logs": {run.log_url for run in runs},
        "artifacts": {f"{runs[0].get_artifact_s3_prefix()}/plan.md"},
        "agent-memory": {f"{user_memory_prefix(team_id, 7)}-repo/memory/a.md"},
        "task-sessions": {f"task-sessions/{organization_id}/{runs[0].task_id}/session.jsonl"},
    }


class TestCleanOrphanedPrefixes(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(self.settings(OBJECT_STORAGE_ENABLED=True))
        self.enterContext(patch.object(orphaned_objects, "PAGE_SIZE", 2))
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
        self.orphan_keys = set().union(*self.orphan_keys_by_kind.values()) | {OVERFLOWING_TEAM_KEY}
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

    def _clean(
        self,
        *,
        execute: bool,
        kind_names: tuple[str, ...] = KIND_NAMES,
        max_prefixes: int = 100,
        start: OrphanedObjectsTotals | None = None,
    ) -> OrphanedObjectsTotals:
        return clean_orphaned_prefixes(
            bucket=self.bucket,
            kind_names=kind_names,
            max_prefixes=max_prefixes,
            execute=execute,
            start=start or OrphanedObjectsTotals(),
            checkpoint=lambda totals: None,
        )

    @parameterized.expand([("execute", True), ("dry_run", False)])
    def test_deletes_only_orphaned_prefixes(self, _name: str, execute: bool) -> None:
        totals = self._clean(execute=execute)

        assert self._keys() == (self.live_keys if execute else self.live_keys | self.orphan_keys)
        assert totals == OrphanedObjectsTotals(prefixes=5, objects=9, size_bytes=9, unrecognized_prefixes=1)

    @parameterized.expand(
        [
            ("kind", {"kind_names": ("task-sessions",)}, "task-sessions"),
            ("limit", {"max_prefixes": 1}, "logs"),
            (
                "limit_left_by_an_earlier_attempt",
                {"max_prefixes": 2, "start": OrphanedObjectsTotals(prefixes=1)},
                "logs",
            ),
        ]
    )
    def test_rollout_inputs_narrow_what_is_deleted(self, _name: str, inputs: dict, deleted_kind: str) -> None:
        self._clean(execute=True, **inputs)

        assert self._keys() == (self.live_keys | self.orphan_keys) - self.orphan_keys_by_kind[deleted_kind]

    def test_failed_deletes_are_kept_and_counted(self) -> None:
        stuck_key = sorted(self.orphan_keys_by_kind["logs"])[0]
        delete_objects = self.storage.delete_objects

        def delete_all_but_stuck(bucket: str, keys: list[str]) -> list[str]:
            deleted = [key for key in keys if key != stuck_key]
            return delete_objects(bucket, deleted) + [key for key in keys if key == stuck_key]

        with patch.object(self.storage, "delete_objects", side_effect=delete_all_but_stuck):
            totals = self._clean(execute=True)

        assert self._keys() == self.live_keys | {stuck_key}
        assert totals.failed_objects == 1
        assert totals.objects == 8

    def test_owner_created_after_listing_keeps_its_objects(self) -> None:
        logs = next(kind for kind in prefix_kinds() if kind.name == "logs")
        orphan = OrphanedPrefix(kind=logs, owner_id=str(ORPHAN_TEAM_ID), prefix=f"tasks/logs/team_{ORPHAN_TEAM_ID}/")
        Team.objects.create(id=ORPHAN_TEAM_ID, organization=Organization.objects.create(name="Late"), name="Late")

        outcome = delete_prefix(self.storage, self.bucket, orphan, execute=True, progress=lambda: None)

        assert outcome.owner_reappeared
        assert self._keys() == self.live_keys | self.orphan_keys


EARLIER_ATTEMPT = OrphanedObjectsTotals(prefixes=3, objects=40)


class TestResumeTotals(SimpleTestCase):
    @parameterized.expand(
        [
            ("deletion_retry_resumes", True, [dataclasses.asdict(EARLIER_ATTEMPT)], EARLIER_ATTEMPT),
            ("scan_retry_starts_over", False, [dataclasses.asdict(EARLIER_ATTEMPT)], OrphanedObjectsTotals()),
            ("first_attempt_starts_at_zero", True, [], OrphanedObjectsTotals()),
        ]
    )
    def test_resume_totals(
        self, _name: str, execute: bool, details: list[object], expected: OrphanedObjectsTotals
    ) -> None:
        assert resume_totals(execute, details) == expected
