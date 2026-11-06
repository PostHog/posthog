from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.utils import get_instance_region

# A notebook sandbox costs its CPU rate plus its memory rate, for every hour it stays alive.
# The rates match managed warehouse compute, so the same sandbox shape costs the same in both
# products. They price what a sandbox reserves, not what it uses, because the reservation is
# what we hold for the user.
_US_CPU_RATE_PER_CORE_HOUR = 0.20
_US_MEMORY_RATE_PER_GB_HOUR = 0.025

# The EU region runs 15% above the US region.
_EU_RATE_MULTIPLIER = 1.15


@frozen
class ComputeRates:
    cpu_per_core_hour: float
    memory_per_gb_hour: float

    def hourly_price(self, *, cpu_cores: float, memory_gb: float) -> float:
        return round(cpu_cores * self.cpu_per_core_hour + memory_gb * self.memory_per_gb_hour, 4)


@frozen
class ComputeShape:
    """The cpu and memory a sandbox runs on, which is all the rates need to price it."""

    cpu_cores: float
    memory_gb: float


@frozen
class ComputePreset:
    key: str
    name: str
    description: str
    cpu_cores: float
    memory_gb: float


_US_RATES = ComputeRates(
    cpu_per_core_hour=_US_CPU_RATE_PER_CORE_HOUR,
    memory_per_gb_hour=_US_MEMORY_RATE_PER_GB_HOUR,
)
_EU_RATES = ComputeRates(
    cpu_per_core_hour=round(_US_CPU_RATE_PER_CORE_HOUR * _EU_RATE_MULTIPLIER, 5),
    memory_per_gb_hour=round(_US_MEMORY_RATE_PER_GB_HOUR * _EU_RATE_MULTIPLIER, 5),
)

# A preset only saves the user the sizing decision, because the two rates price any shape they
# pick. The shapes step apart far enough that a user who outgrows one knows which to take next.
COMPUTE_PRESETS: tuple[ComputePreset, ...] = (
    ComputePreset(
        key="small",
        name="Small",
        description="Exploring data and working with small dataframes.",
        cpu_cores=1,
        memory_gb=2,
    ),
    ComputePreset(
        key="balanced",
        name="Balanced",
        description="Most analysis work.",
        cpu_cores=4,
        memory_gb=8,
    ),
    ComputePreset(
        key="large",
        name="Large",
        description="Large joins and cells that run for a while.",
        cpu_cores=8,
        memory_gb=16,
    ),
    ComputePreset(
        key="high_memory",
        name="High memory",
        description="Dataframes that run out of memory on the other presets.",
        cpu_cores=8,
        memory_gb=32,
    ),
)

DEFAULT_COMPUTE_PRESET_KEY = "small"


def get_compute_rates(region: str | None = None) -> ComputeRates:
    """The rates that apply to this instance. Anything that is not EU is priced at US rates."""
    resolved_region = region if region is not None else get_instance_region()
    return _EU_RATES if resolved_region == "EU" else _US_RATES


def get_default_compute_preset() -> ComputePreset:
    return get_compute_preset(DEFAULT_COMPUTE_PRESET_KEY)


def get_compute_preset(key: str) -> ComputePreset:
    for preset in COMPUTE_PRESETS:
        if preset.key == key:
            return preset
    raise ValueError(f"Unknown compute preset: {key}")


def find_matching_preset(*, cpu_cores: float | None, memory_gb: float | None) -> ComputePreset | None:
    """The preset a sandbox shape came from, or None when the user tuned it themselves."""
    if cpu_cores is None or memory_gb is None:
        return None
    for preset in COMPUTE_PRESETS:
        if abs(preset.cpu_cores - cpu_cores) < 1e-6 and abs(preset.memory_gb - memory_gb) < 1e-6:
            return preset
    return None
