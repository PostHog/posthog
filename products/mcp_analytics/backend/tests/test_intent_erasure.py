import sys
import types
import importlib.machinery
from collections.abc import Callable
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.dags.tests.conftest import isolated_clickhouse_cluster
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.api import complete_intent_erasure, prepare_intent_erasure
from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_DATA_TABLE
from products.mcp_analytics.backend.facade.contracts import (
    IntentErasure,
    IntentErasurePending,
    IntentInvalidationConflict,
)
from products.mcp_analytics.backend.intent_topics.invalidation import (
    IntentWritesFrozen,
    admit_writer,
    locked_fill,
    snapshot_barrier,
)
from products.mcp_analytics.backend.models import (
    MCPIntentClusterSnapshot,
    MCPIntentEmbeddingCache,
    MCPIntentErasure,
    MCPIntentWriteBarrier,
    MCPSession,
)
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment

PROVIDER_PACKAGE = "products.mcp_analytics.backend"
WRITERS_MODULE = f"{PROVIDER_PACKAGE}.intent_erasure_writers"
STORAGE_MODULE = f"{PROVIDER_PACKAGE}.intent_erasure_storage"
ROLLUPS_MODULE = f"{PROVIDER_PACKAGE}.intent_erasure_rollups"


def _provider_module(module: str, function: str, implementation: Callable[..., None]) -> types.ModuleType:
    fake = types.ModuleType(f"{PROVIDER_PACKAGE}.{module}")
    fake.__spec__ = importlib.machinery.ModuleSpec(fake.__name__, None)
    setattr(fake, function, implementation)
    return fake


class TestMCPIntentErasure(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cluster = self.enterContext(isolated_clickhouse_cluster())
        self.sibling = Team.objects.create(organization=self.organization, parent_team=self.team)
        self.other = Team.objects.create(organization=self.organization)
        # ClickHouse is not rolled back with Postgres, so rows from other tests or runs can share these team ids.
        team_ids = (self.team.pk, self.sibling.pk, self.other.pk)
        self._delete_assignments(*team_ids)
        self.addCleanup(self._delete_assignments, *team_ids)
        self.drain_error: Exception | None = None

        def drained(*, erasure: IntentErasure, cluster: object) -> None:
            if self.drain_error is not None:
                raise self.drain_error

        # Upper stack layers ship real providers. A None entry hides them, so each test sees only what it injects.
        self.enterContext(
            patch.dict(
                sys.modules,
                {
                    WRITERS_MODULE: _provider_module("intent_erasure_writers", "assert_writers_drained", drained),
                    STORAGE_MODULE: None,
                    ROLLUPS_MODULE: None,
                },
            )
        )

    def _prepare(self, token: UUID, *, team: Team | None = None, scope: str = "original") -> IntentErasure:
        return prepare_intent_erasure(
            source_team_id=(team or self.sibling).pk,
            invalidation_id=token,
            scope_fingerprint=scope,
            cluster=self.cluster,
        )

    def _delete_assignments(self, *team_ids: int) -> None:
        sync_execute(
            f"ALTER TABLE {MCP_INTENT_ASSIGNMENTS_DATA_TABLE} DELETE WHERE team_id IN %(team_ids)s "
            "SETTINGS mutations_sync = 2",
            {"team_ids": team_ids},
        )

    def _assignment_teams(self) -> set[int]:
        rows = sync_execute(
            f"SELECT DISTINCT team_id FROM {MCP_INTENT_ASSIGNMENTS_DATA_TABLE} WHERE team_id IN %(team_ids)s",
            {"team_ids": (self.team.pk, self.sibling.pk, self.other.pk)},
        )
        return {team_id for (team_id,) in rows}

    def _providers(self, calls: list[str], *, purge: bool = True) -> dict[str, types.ModuleType]:
        def drained(*, erasure: IntentErasure, cluster: object) -> None:
            calls.append("drain")

        def purge_storage(*, erasure: IntentErasure, cluster: object) -> None:
            calls.append("storage")
            if purge:
                self._delete_assignments(*erasure.source_team_ids)

        def purge_rollups(*, erasure: IntentErasure, cluster: object) -> None:
            calls.append("rollups")

        return {
            WRITERS_MODULE: _provider_module("intent_erasure_writers", "assert_writers_drained", drained),
            STORAGE_MODULE: _provider_module("intent_erasure_storage", "purge_intent_storage", purge_storage),
            ROLLUPS_MODULE: _provider_module("intent_erasure_rollups", "purge_rollups_and_caches", purge_rollups),
        }

    def test_complete_drains_then_purges_every_environment_and_reopens_with_a_retained_generation(self) -> None:
        for team in (self.team, self.sibling, self.other):
            _insert_assignment(team.pk, "a" * 64, "topic", intent_text="copied text")
        calls: list[str] = []
        with patch.dict(sys.modules, self._providers(calls)):
            erasure = self._prepare(uuid4())
            assert erasure.source_team_ids == (self.team.pk, self.sibling.pk)
            for team in (self.team, self.sibling):
                with self.assertRaises(IntentWritesFrozen), admit_writer(team):
                    self.fail("admitted a writer while the erasure was prepared")
            complete_intent_erasure(erasure=erasure, cluster=self.cluster)

        assert calls == ["drain", "drain", "storage", "rollups"]
        assert self._assignment_teams() == {self.other.pk}
        for team in (self.team, self.sibling):
            with admit_writer(team):
                pass
        with team_scope(self.team.pk):
            assert MCPIntentWriteBarrier.objects.get(team=self.team).generation == 1

    def test_provider_that_reports_success_cannot_reopen_while_copies_remain(self) -> None:
        _insert_assignment(self.sibling.pk, "a" * 64, "topic")
        calls: list[str] = []
        with patch.dict(sys.modules, self._providers(calls, purge=False)):
            erasure = self._prepare(uuid4())
            with self.assertRaisesMessage(IntentErasurePending, "survived the purge"):
                complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        assert self._assignment_teams() == {self.sibling.pk}
        with self.assertRaises(IntentWritesFrozen), admit_writer(self.sibling):
            self.fail("reopened writers with derived copies still present")
        with team_scope(self.team.pk):
            assert MCPIntentErasure.objects.get(team=self.team).completed_at is None

    def test_missing_writer_drain_proof_keeps_an_empty_project_frozen(self) -> None:
        with (
            patch.dict(sys.modules, {WRITERS_MODULE: None}),
            self.assertRaisesMessage(IntentErasurePending, "drain cannot be proved"),
        ):
            self._prepare(uuid4())
        with self.assertRaises(IntentWritesFrozen), admit_writer(self.sibling):
            self.fail("reopened writers without proof that in-flight writers finished")

    def test_stale_fill_is_rejected_after_an_erasure_froze_and_reopened_the_project(self) -> None:
        stale = snapshot_barrier(self.sibling)
        erasure = self._prepare(uuid4())
        complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        with self.assertRaises(IntentWritesFrozen), locked_fill(self.sibling, stale):
            self.fail("published a result computed before the erasure")
        with locked_fill(self.sibling, snapshot_barrier(self.sibling)):
            pass

    def test_retry_keeps_source_proof_required_when_copies_disappear_after_failed_drain(self) -> None:
        token = uuid4()
        _insert_assignment(self.team.pk, "a" * 64, "topic")
        self.drain_error = IntentErasurePending("writers still running")
        with self.assertRaises(IntentErasurePending):
            self._prepare(token)
        self.drain_error = None
        self._delete_assignments(self.team.pk)
        erasure = self._prepare(token)
        assert erasure.verify_sources
        assert not erasure.completed

    def test_changed_request_scope_cannot_take_over_a_failed_erasure(self) -> None:
        token = uuid4()
        _insert_assignment(self.team.pk, "a" * 64, "topic")
        self.drain_error = IntentErasurePending("writers still running")
        with self.assertRaises(IntentErasurePending):
            self._prepare(token)
        with self.assertRaisesMessage(IntentInvalidationConflict, "scope changed"):
            self._prepare(token, scope="different")
        with self.assertRaisesMessage(IntentInvalidationConflict, "Another intent erasure"):
            self._prepare(uuid4())

    @parameterized.expand([("session",), ("snapshot",), ("embedding_cache",)])
    def test_legacy_intent_stores_keep_erasure_frozen_until_their_writers_and_copies_are_handled(
        self, store: str
    ) -> None:
        with team_scope(self.team.pk):
            if store == "session":
                MCPSession.objects.create(team=self.team, session_id="example-session", intent="list example flags")
            elif store == "snapshot":
                MCPIntentClusterSnapshot.objects.create(
                    team=self.team, clusters={"clusters": [{"label": "example flags"}]}
                )
            else:
                MCPIntentEmbeddingCache.objects.create(
                    team=self.team, content_hash="a" * 64, model="example", embedding=b"example"
                )
        erasure = self._prepare(uuid4())
        with self.assertRaisesMessage(IntentErasurePending, "derived intent data exists"):
            complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        with self.assertRaises(IntentWritesFrozen), admit_writer(self.sibling):
            self.fail("a legacy intent store was treated as an empty project")

    def test_sessions_without_copied_intent_text_are_not_derived_state(self) -> None:
        with team_scope(self.team.pk):
            MCPSession.objects.create(team=self.team, session_id="example-session", intent=None)
            MCPIntentClusterSnapshot.objects.create(team=self.team)
        erasure = self._prepare(uuid4())
        complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        with admit_writer(self.sibling):
            pass

    def test_late_state_at_completion_persists_source_proof_requirement_after_rollback(self) -> None:
        token = uuid4()
        erasure = self._prepare(token)
        assert not erasure.verify_sources
        _insert_assignment(self.team.pk, "a" * 64, "late")
        with self.assertRaises(IntentErasurePending):
            complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        self._delete_assignments(self.team.pk)
        with self.assertRaisesMessage(IntentInvalidationConflict, "verify source deletion"):
            complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        assert self._prepare(token).verify_sources
        with self.assertRaises(IntentWritesFrozen), admit_writer(self.sibling):
            self.fail("a late writer cleared the source proof requirement")

    def test_sibling_retries_share_the_operation_and_completed_retries_do_not_reopen_a_new_freeze(self) -> None:
        token = uuid4()
        erasure = self._prepare(token)
        assert self._prepare(token, team=self.team) == erasure
        complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        assert self._prepare(token).completed
        replacement = self._prepare(uuid4())
        complete_intent_erasure(erasure=erasure, cluster=self.cluster)
        with team_scope(self.team.pk):
            assert MCPIntentWriteBarrier.objects.get(team=self.team).invalidation_id == replacement.invalidation_id
        with self.assertRaises(IntentWritesFrozen), admit_writer(self.sibling):
            self.fail("a completed retry reopened a different operation")
