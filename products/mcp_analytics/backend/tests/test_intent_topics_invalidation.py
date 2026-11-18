from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from django.db import OperationalError, connection, connections

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.mcp_analytics.backend.intent_topics.invalidation import (
    IntentWritesFrozen,
    freeze_writes,
    has_pending_registered_writers,
)
from products.mcp_analytics.backend.intent_topics.persist import start_run
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentWriteBarrier

NOW = datetime(2026, 11, 1, tzinfo=UTC)


class TestWriterAdmission(NonAtomicBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization = Organization.objects.create(name="Writer admission tests")
        self.team = Team.objects.create(organization=self.organization, name="Writer admission tests")

    @parameterized.expand([("admission_first", False), ("freeze_first", True)])
    def test_admission_and_freeze_serialize_on_the_same_project(self, _name: str, freeze_first: bool) -> None:
        operation = uuid4()

        def start() -> None:
            start_run(self.team, kind="assign", run_id="concurrent", window_start=NOW, window_end=NOW)

        def freeze() -> None:
            freeze_writes(self.team, invalidation_id=operation)

        first, second = (freeze, start) if freeze_first else (start, freeze)
        model = MCPIntentWriteBarrier if freeze_first else MCPIntentClusteringRun
        original_save = model.save

        def contend() -> None:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '100ms'")
                with pytest.raises(OperationalError) as error:
                    second()
                cause = error.value.__cause__
                assert (getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)) == "55P03"
            finally:
                connections.close_all()

        def hold_before_commit(instance, *args, **kwargs):
            result = original_save(instance, *args, **kwargs)
            if not freeze_first or instance.invalidation_id is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    executor.submit(contend).result(timeout=10)
            return result

        with team_scope(self.team.pk):
            MCPIntentWriteBarrier.objects.create(team=self.team)
            with patch.object(model, "save", hold_before_commit):
                first()
            if freeze_first:
                with pytest.raises(IntentWritesFrozen):
                    start()
                assert not MCPIntentClusteringRun.objects.filter(run_id="concurrent").exists()
                assert not has_pending_registered_writers(self.team, invalidation_id=operation)
            else:
                freeze()
                assert has_pending_registered_writers(self.team, invalidation_id=operation)
