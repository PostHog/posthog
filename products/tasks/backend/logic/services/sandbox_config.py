from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings

# Production: 6 hours (safety net; workflow inactivity timeout handles cleanup).
# Tests: 15 min so any sandbox orphaned by a crashed test auto-destroys quickly
# instead of burning Modal capacity for hours.
SANDBOX_TTL_SECONDS = 15 * 60 if settings.TEST else 6 * 60 * 60

# Default request floor for burstable sandboxes (used when SandboxConfig.burstable_resources is
# True): the box reserves only this much and bursts up to its configured cpu_cores / memory_gb.
# Modal bills max(request, actual), so an idle burstable box costs the floor, not the full size.
BURSTABLE_REQUEST_CPU_CORES = 0.5
BURSTABLE_REQUEST_MEMORY_MB = 1024

VM_SANDBOX_CPU_CORES = 8.0

# Upper bounds for per-task sandbox resource overrides. Override values are clamped
# to these so a bad or hostile value can't provision an oversized/long-lived sandbox.
MAX_SANDBOX_CPU_CORES = 16
MAX_SANDBOX_MEMORY_GB = 64
MAX_SANDBOX_TTL_SECONDS = SANDBOX_TTL_SECONDS

DEV_STACK_MEMORY_GB = 64.0
DEV_STACK_CPU_REQUEST_CORES = 4.0


@dataclass(frozen=True)
class SandboxResources:
    """Optional compute overrides for a task's sandbox. Unset fields keep the
    `SandboxConfig` defaults — callers pass only what they want to change."""

    cpu_cores: float | None = None
    memory_gb: float | None = None


class SandboxSize(StrEnum):
    """A named sandbox shape. The value reads vCPU x GiB of memory."""

    CPU_1_MEMORY_2 = "1x2"
    CPU_2_MEMORY_4 = "2x4"
    CPU_2_MEMORY_8 = "2x8"
    CPU_4_MEMORY_8 = "4x8"
    CPU_4_MEMORY_16 = "4x16"
    CPU_8_MEMORY_16 = "8x16"
    CPU_8_MEMORY_32 = "8x32"
    CPU_16_MEMORY_64 = "16x64"


def _shape(size: SandboxSize) -> SandboxResources:
    cpu_cores, memory_gb = size.value.split("x")
    return SandboxResources(cpu_cores=float(cpu_cores), memory_gb=float(memory_gb))


SANDBOX_SIZE_SHAPES: dict[SandboxSize, SandboxResources] = {size: _shape(size) for size in SandboxSize}

# Equal to the `SandboxConfig` default shape, so a run that names this size gets the same box
# as a run that names no size.
DEFAULT_SANDBOX_SIZE = SandboxSize.CPU_4_MEMORY_16

# Run state key that records the size a caller selected. Server-owned: the size decides the
# sandbox backend and the billed shape.
SANDBOX_SIZE_STATE_KEY = "sandbox_size"


def parse_sandbox_size(value: str) -> SandboxSize:
    try:
        return SandboxSize(value)
    except ValueError:
        valid = ", ".join(size.value for size in SandboxSize)
        raise ValueError(f"Unknown sandbox size '{value}'. Valid sizes: {valid}.") from None


def is_non_default_sandbox_size(state: dict | None) -> bool:
    """Whether the run state names a size other than the default one.

    An unknown value counts as non-default, so that a size this code cannot read is never
    sent to a backend that ignores resource overrides.
    """
    value = (state or {}).get(SANDBOX_SIZE_STATE_KEY)
    return value is not None and value != DEFAULT_SANDBOX_SIZE.value
