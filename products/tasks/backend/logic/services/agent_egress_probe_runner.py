from __future__ import annotations

import sys
import time
import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from uuid import uuid4

from django.db import connections
from django.utils import timezone

from products.tasks.backend.logic.services.agent_egress_lifecycle import AgentEgressLifecycle
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig

logger = logging.getLogger(__name__)


class AgentEgressProbeRunner:
    def __init__(self, config: AgentEgressProbeConfig, *, report: Callable[[dict[str, object]], None]) -> None:
        self.config = config
        self.report = report

    @staticmethod
    def _request(lifecycle: AgentEgressLifecycle) -> dict[int, int]:
        try:
            return lifecycle.probe()
        finally:
            connections.close_all()

    def _probe(self, lifecycle: AgentEgressLifecycle) -> dict[int, int]:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            pending = executor.submit(self._request, lifecycle)
            while True:
                try:
                    return pending.result(timeout=10)
                except TimeoutError:
                    if pending.done():
                        return pending.result()
                    lifecycle.renew()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def run(self) -> None:
        self.config.eligible_run()
        lifecycle = AgentEgressLifecycle(
            self.config,
            execution_id=uuid4(),
            workflow_run_id=f"local-{uuid4()}",
            provisioning_deadline=timezone.now().timestamp() + 180,
        )
        sandbox_id: str | None = None
        reason = "failed"
        try:
            sandbox_id = lifecycle.prepare()
            self.report({"sandbox_id": sandbox_id, "execution_id": str(lifecycle.execution_id)})
            deadline = time.monotonic() + self.config.duration_seconds
            counts: Counter[int] = Counter()
            while time.monotonic() < deadline:
                lifecycle.renew()
                result = self._probe(lifecycle)
                counts.update(result)
                self.report({"statuses": result})
                time.sleep(max(0, min(10, deadline - time.monotonic())))
            self.report({"total_statuses": dict(counts)})
            reason = "completed"
        except KeyboardInterrupt:
            reason = "cancelled"
            raise
        finally:
            active_error = sys.exception()
            try:
                lifecycle.close(reason=reason, sandbox_id=sandbox_id)
            except Exception:
                if active_error is None:
                    raise
                logger.exception("agent_egress_probe_cleanup_failed")
