"""Shared memory-pressure probe plumbing for sandbox providers.

Where a sandbox keeps its memory ceiling depends on how the box was made. A container
reads its cgroup limit. A Modal VM has no cgroup limit, so its ceiling is the kernel's
own view in ``/proc/meminfo``. Older kernels use the cgroup v1 file names. One probe
reads every candidate in a single exec, and the parser takes the narrowest ceiling that
is actually set. Providers differ only in how they run a command, so the command text
and the parsing live here and must not fork between backends.
"""

from __future__ import annotations

import shlex
from enum import StrEnum

from posthog.dataclasses import frozen

_PROBE_MARKER = "@@"
_PROCESS_SECTION = "processes"
_TOP_PROCESS_COUNT = 5

# cgroup writes a sentinel this large when no limit is set. A ceiling at that scale is
# not a ceiling, so both cgroup versions are read through the same guard.
_CGROUP_UNLIMITED_BYTES = 0x7FFFFFFFFFFFF000

MEMORY_PROBE_TIMEOUT_SECONDS = 10

_PROBE_FILES = (
    ("cgroup2_current", "/sys/fs/cgroup/memory.current"),
    ("cgroup2_max", "/sys/fs/cgroup/memory.max"),
    ("cgroup2_peak", "/sys/fs/cgroup/memory.peak"),
    ("cgroup2_events", "/sys/fs/cgroup/memory.events"),
    ("cgroup1_current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ("cgroup1_max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ("cgroup1_peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"),
    ("meminfo", "/proc/meminfo"),
)


class MemoryPressureLevel(StrEnum):
    OK = "ok"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


# WATCH only labels the metric, so a rollout can see how many boxes sit in that band before
# anyone retunes these numbers. At WARNING the run probes more often and tells the person
# watching. At CRITICAL it interrupts the agent, so the threshold leaves enough headroom for
# a dev stack to shut down after the message lands.
MEMORY_WATCH_FRACTION = 0.70
MEMORY_WARNING_FRACTION = 0.85
MEMORY_CRITICAL_FRACTION = 0.93


def memory_pressure_level(used_fraction: float) -> MemoryPressureLevel:
    if used_fraction >= MEMORY_CRITICAL_FRACTION:
        return MemoryPressureLevel.CRITICAL
    if used_fraction >= MEMORY_WARNING_FRACTION:
        return MemoryPressureLevel.WARNING
    if used_fraction >= MEMORY_WATCH_FRACTION:
        return MemoryPressureLevel.WATCH
    return MemoryPressureLevel.OK


@frozen
class SandboxProcessMemory:
    name: str
    resident_bytes: int


@frozen
class SandboxMemory:
    """What one probe saw.

    ``peak_bytes`` is context for whoever reads the log, never a trigger. The kernel
    measures it from boot, so a build that has already finished would hold a healthy box
    above a threshold for the rest of the run.
    """

    used_bytes: int
    limit_bytes: int
    source: str
    peak_bytes: int | None = None
    oom_kills: int = 0
    top_processes: tuple[SandboxProcessMemory, ...] = ()

    def __post_init__(self) -> None:
        if self.limit_bytes <= 0:
            raise ValueError("limit_bytes must be positive")
        if self.used_bytes < 0:
            raise ValueError("used_bytes must not be negative")

    @property
    def used_fraction(self) -> float:
        return self.used_bytes / self.limit_bytes

    @property
    def used_percent(self) -> int:
        return round(self.used_fraction * 100)

    @property
    def level(self) -> MemoryPressureLevel:
        return memory_pressure_level(self.used_fraction)


@frozen
class _Reading:
    """One source's answer, before the narrowest ceiling is chosen."""

    used_bytes: int
    limit_bytes: int
    source: str
    peak_bytes: int | None = None


def build_memory_probe_command() -> str:
    """Read every candidate source in one shell invocation.

    Each section is preceded by a marker line and followed by a newline, so a source that
    does not exist contributes an empty section instead of shifting the ones after it. The
    command always exits 0: a missing file is an expected answer, not a failure.
    """
    parts = [
        f"printf '{_PROBE_MARKER}%s\\n' {shlex.quote(name)}; cat {shlex.quote(path)} 2>/dev/null; echo; "
        for name, path in _PROBE_FILES
    ]
    parts.append(
        f"printf '{_PROBE_MARKER}%s\\n' {shlex.quote(_PROCESS_SECTION)}; "
        f"ps -eo rss=,comm= --sort=-rss 2>/dev/null | head -n {_TOP_PROCESS_COUNT}; echo; "
    )
    return "".join(parts) + "exit 0"


def parse_memory_probe(stdout: str) -> SandboxMemory | None:
    """The sandbox's memory position, or None when no source could be read."""
    sections = _split_sections(stdout)
    readings = [
        reading
        for reading in (
            _cgroup_reading(sections, version=2),
            _cgroup_reading(sections, version=1),
            _meminfo_reading(sections.get("meminfo")),
        )
        if reading is not None
    ]
    if not readings:
        return None

    # Ties keep the earlier source, so a cgroup limit wins over an identical kernel total:
    # it is the one the OOM killer enforces.
    reading = min(readings, key=lambda candidate: candidate.limit_bytes)
    return SandboxMemory(
        used_bytes=min(reading.used_bytes, reading.limit_bytes),
        limit_bytes=reading.limit_bytes,
        source=reading.source,
        peak_bytes=reading.peak_bytes,
        oom_kills=_oom_kills(sections.get("cgroup2_events")),
        top_processes=_top_processes(sections.get(_PROCESS_SECTION)),
    )


def format_memory_size(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    return f"{round(value / 1024**2)} MB"


def describe_memory_position(memory: SandboxMemory) -> str:
    return (
        f"{format_memory_size(memory.used_bytes)} of {format_memory_size(memory.limit_bytes)} ({memory.used_percent}%)"
    )


def build_memory_pressure_nudge(*, position: str, top_processes: str) -> str:
    """The message that interrupts an agent whose sandbox is nearly out of memory.

    It names the run as the sender, because the agent must not read it as a turn from the
    person it is working for.
    """
    largest = f"Largest processes: {top_processes}\n" if top_processes else ""
    return (
        "System notice from this run's sandbox monitor. This is not a message from the user.\n\n"
        f"The sandbox is nearly out of memory. It is using {position}.\n"
        f"{largest}\n"
        "If the sandbox runs out of memory, it is killed, the run ends, and anything you have not "
        "committed and pushed is lost.\n\n"
        "Free memory before you continue:\n"
        "1. Stop what is using it. A local dev stack is the usual cause, so `hogli down` or "
        "`docker compose down` normally recovers the box.\n"
        "2. Rerun heavy work with a smaller footprint, or one piece at a time.\n\n"
        "This sandbox cannot be given more memory while it is running. If the work needs a bigger "
        "box, commit and push what you have, tell the user what it needs, and stop."
    )


def build_memory_exhaustion_error(*, position: str) -> str:
    """Why a run ended, when the sandbox was nearly full the last time anyone looked."""
    return (
        f"Sandbox stopped with memory nearly full ({position}); it most likely ran out of memory. "
        "Start a new run with less running inside it."
    )


def _split_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in stdout.splitlines():
        if line.startswith(_PROBE_MARKER):
            current = sections.setdefault(line[len(_PROBE_MARKER) :].strip(), [])
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _read_int(text: str | None) -> int | None:
    if text is None:
        return None
    value = text.strip()
    return int(value) if value.isdigit() else None


def _cgroup_reading(sections: dict[str, str], *, version: int) -> _Reading | None:
    prefix = f"cgroup{version}"
    used = _read_int(sections.get(f"{prefix}_current"))
    limit = _read_int(sections.get(f"{prefix}_max"))
    if used is None or limit is None or limit <= 0 or limit >= _CGROUP_UNLIMITED_BYTES:
        return None
    return _Reading(
        used_bytes=used,
        limit_bytes=limit,
        source=f"cgroup_v{version}",
        peak_bytes=_read_int(sections.get(f"{prefix}_peak")),
    )


def _meminfo_reading(text: str | None) -> _Reading | None:
    """The kernel's own view, which is the only ceiling a VM-backed sandbox has."""
    if not text:
        return None
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        if not separator or key not in ("MemTotal", "MemAvailable"):
            continue
        fields = rest.split()
        if fields and fields[0].isdigit():
            values[key] = int(fields[0]) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if total is None or available is None or total <= 0:
        return None
    return _Reading(used_bytes=max(0, total - available), limit_bytes=total, source="meminfo")


def _oom_kills(text: str | None) -> int:
    if not text:
        return 0
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if key == "oom_kill":
            return _read_int(value) or 0
    return 0


def _top_processes(text: str | None) -> tuple[SandboxProcessMemory, ...]:
    if not text:
        return ()
    processes: list[SandboxProcessMemory] = []
    for line in text.splitlines():
        resident, _, name = line.strip().partition(" ")
        name = name.strip()
        if not name or not resident.isdigit():
            continue
        processes.append(SandboxProcessMemory(name=name, resident_bytes=int(resident) * 1024))
    return tuple(processes)
