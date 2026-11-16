import asyncio
from uuid import uuid4

import pytest
from posthog.test.base import NonAtomicBaseTest

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.mcp_analytics.backend.intent_erasure_writers import (
    registered_intent_writer,
    registered_intent_writer_async,
)
from products.mcp_analytics.backend.intent_topics.invalidation import (
    IntentWritesFrozen,
    freeze_writes,
    has_pending_registered_writers,
)
from products.mcp_analytics.backend.models import MCPSession


class TestLegacyWriterAdmission(NonAtomicBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization = Organization.objects.create(name="Legacy writer tests")
        self.team = Team.objects.create(organization=self.organization, name="Legacy writer tests")

    @parameterized.expand([("sync", False), ("async", True)])
    def test_legacy_writer_remains_pending_until_its_last_write(self, _name: str, asynchronous: bool) -> None:
        operation = uuid4()

        def write_after_freeze() -> None:
            freeze_writes(self.team, invalidation_id=operation)
            assert has_pending_registered_writers(self.team, invalidation_id=operation)
            MCPSession.objects.create(team=self.team, session_id="in-flight", intent="Example summary")

        async def generate() -> None:
            async with registered_intent_writer_async(self.team, purpose="test"):
                await database_sync_to_async(write_after_freeze)()

        with team_scope(self.team.pk):
            if asynchronous:
                asyncio.run(generate())
            else:
                with registered_intent_writer(self.team, purpose="test"):
                    write_after_freeze()
            assert MCPSession.objects.get(team=self.team, session_id="in-flight").intent == "Example summary"
            assert not has_pending_registered_writers(self.team, invalidation_id=operation)

    @parameterized.expand([("sync", False), ("async", True)])
    def test_frozen_legacy_writer_cannot_persist_a_session(self, _name: str, asynchronous: bool) -> None:
        operation = uuid4()

        def write() -> None:
            MCPSession.objects.create(team=self.team, session_id="blocked", intent="Must not persist")

        async def generate() -> None:
            async with registered_intent_writer_async(self.team, purpose="test"):
                await database_sync_to_async(write)()

        with team_scope(self.team.pk):
            freeze_writes(self.team, invalidation_id=operation)
            with pytest.raises(IntentWritesFrozen):
                if asynchronous:
                    asyncio.run(generate())
                else:
                    with registered_intent_writer(self.team, purpose="test"):
                        write()
            assert not MCPSession.objects.filter(team=self.team).exists()
            assert not has_pending_registered_writers(self.team, invalidation_id=operation)

    @parameterized.expand([("failure", RuntimeError), ("cancellation", asyncio.CancelledError)])
    def test_uncertain_legacy_writer_keeps_deletion_pending(self, _name: str, error: type[BaseException]) -> None:
        operation = uuid4()

        async def generate() -> None:
            async with registered_intent_writer_async(self.team, purpose="test"):
                raise error()

        with team_scope(self.team.pk):
            with pytest.raises(error):
                asyncio.run(generate())
            freeze_writes(self.team, invalidation_id=operation)
            assert has_pending_registered_writers(self.team, invalidation_id=operation)
