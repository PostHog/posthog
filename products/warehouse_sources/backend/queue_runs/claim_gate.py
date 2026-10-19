from __future__ import annotations

import time

import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import PodMemory

logger = structlog.get_logger(__name__)

_LOG_INTERVAL_SECONDS = 60.0


class MemoryClaimGate:
    """Close the claim gate while the pod has less free memory than the reserve.

    This reads the pod's cgroup, not `MemoryGovernor.admit`: the governor sizes one upsert, and a
    claim starts a whole run whose size is not known yet. When the limit or the usage cannot be
    read, the gate stays open, so a pod without a cgroup still works.
    """

    def __init__(self, *, min_free_mb: float, pod_memory: PodMemory | None = None) -> None:
        self._min_free_mb = min_free_mb
        self._pod_memory = pod_memory or PodMemory()
        self._last_log_monotonic = 0.0

    def __call__(self) -> bool:
        limit_mb = self._pod_memory.limit_mb()
        current_mb = self._pod_memory.current_mb()
        if limit_mb is None or current_mb is None:
            return True
        free_mb = limit_mb - current_mb
        if free_mb >= self._min_free_mb:
            return True
        now = time.monotonic()
        if now - self._last_log_monotonic >= _LOG_INTERVAL_SECONDS:
            self._last_log_monotonic = now
            logger.info(
                "extract_claim_gate_closed",
                free_mb=round(free_mb, 1),
                min_free_mb=self._min_free_mb,
                limit_mb=round(limit_mb, 1),
            )
        return False
