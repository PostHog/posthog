from dataclasses import dataclass

import structlog
from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.logic.services.sandbox import get_sandbox_class
from products.tasks.backend.logic.services.sandbox_memory import (
    MemoryPressureLevel,
    describe_memory_position,
    format_memory_size,
)
from products.tasks.backend.temporal.metrics import record_sandbox_memory_reading
from products.tasks.backend.temporal.observability import emit_agent_log

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CheckSandboxMemoryInput:
    sandbox_id: str
    run_id: str


@dataclass(frozen=False)
class CheckSandboxMemoryOutput:
    """One reading, or ``level = "unknown"`` when the sandbox could not answer.

    Every field has a default so a payload written by an older worker still decodes, and
    so an unknown reading is representable without a separate output type. The workflow
    schedules its next probe from this, so nothing here may depend on wall-clock time.
    """

    level: str = "unknown"
    used_bytes: int = 0
    limit_bytes: int = 0
    used_percent: int = 0
    position: str = ""
    top_processes: str = ""
    source: str = ""
    peak_bytes: int = 0
    oom_kills: int = 0


@activity.defn
@asyncify
def check_sandbox_memory(input: CheckSandboxMemoryInput) -> CheckSandboxMemoryOutput:
    """Read how close a sandbox is to its memory ceiling.

    Never raises: the caller reacts to an unknown reading by backing off, and a probe that
    fails must not retry into the run's critical path or fail the run.
    """
    try:
        sandbox = get_sandbox_class().get_by_id(input.sandbox_id)
        memory = sandbox.read_memory_usage()
    except Exception as e:
        logger.warning(
            "check_sandbox_memory_failed",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            error=str(e),
        )
        record_sandbox_memory_reading("unknown")
        return CheckSandboxMemoryOutput()

    if memory is None:
        record_sandbox_memory_reading("unknown")
        return CheckSandboxMemoryOutput()

    record_sandbox_memory_reading(memory.level.value)
    if memory.level is not MemoryPressureLevel.OK:
        logger.info(
            "sandbox_memory_pressure",
            sandbox_id=input.sandbox_id,
            run_id=input.run_id,
            level=memory.level.value,
            used_percent=memory.used_percent,
            source=memory.source,
            oom_kills=memory.oom_kills,
        )
        emit_agent_log(
            input.run_id,
            "debug",
            f"Sandbox memory {memory.level.value}: {describe_memory_position(memory)}",
        )

    return CheckSandboxMemoryOutput(
        level=memory.level.value,
        used_bytes=memory.used_bytes,
        limit_bytes=memory.limit_bytes,
        used_percent=memory.used_percent,
        position=describe_memory_position(memory),
        top_processes=", ".join(
            f"{process.name} ({format_memory_size(process.resident_bytes)})" for process in memory.top_processes
        ),
        source=memory.source,
        peak_bytes=memory.peak_bytes or 0,
        oom_kills=memory.oom_kills,
    )
