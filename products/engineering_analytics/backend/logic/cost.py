"""Depot CI cost model for engineering_analytics.

Estimates the Depot dollar cost of CI from GitHub Actions job data. GitHub's jobs API exposes
wall-clock and the requested runner ``labels`` -- not Depot's billed minutes -- so every figure is an
estimate: ``elapsed_minutes x tier_multiplier x reference_rate`` (mirrors the DevEx Depot cost tooling).

GitHub/Depot specifics (label shapes, rate ladder) live here per SPEC §3; provider-neutral contract
types stay in ``facade/contracts.py``. Cost is job-level (a run fans into parallel jobs on different
tiers, so per-PR cost is a sum over jobs); ``github_workflow_runs`` alone can't produce it. These
functions are pure and source-agnostic -- unit-tested today, wired to ``github_workflow_jobs`` once it
lands (SPEC §6/9).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# Depot list price per billed minute at the 2-vCPU base tier (1x; multiplier doubles per vCPU doubling,
# so cost = elapsed_minutes x rate x multiplier). Hardcoded for v1; a team-scoped rate + discount config
# is the documented follow-up (SPEC §7).
REFERENCE_RATE_USD_PER_MIN = 0.004

# Depot billing multiplier per vCPU count (2cpu = 1x, doubling each step).
_MULTIPLIER_BY_VCPU: dict[int, int] = {2: 1, 4: 2, 8: 4, 16: 8, 32: 16, 64: 32}

# A Depot Linux runner with no explicit size suffix is the 2-vCPU default (``depot-ubuntu-latest``).
_DEFAULT_DEPOT_VCPU = 2

# Depot runner labels are ``depot-<os>-...`` — the prefix is what makes a runner Depot-billed.
_DEPOT_PREFIX = "depot-"


class RunnerProvider(StrEnum):
    DEPOT = "depot"
    GITHUB_HOSTED = "github_hosted"


class RunnerOS(StrEnum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


# The OS a runner label names, keyed by the token that appears in both Depot and github-hosted
# labels (``depot-ubuntu-22.04-4`` / ``ubuntu-latest`` / ``macos-14`` / ``windows-latest``).
_OS_BY_TOKEN: dict[str, RunnerOS] = {
    "ubuntu": RunnerOS.LINUX,
    "macos": RunnerOS.MACOS,
    "windows": RunnerOS.WINDOWS,
}


@dataclass(frozen=True)
class RunnerTier:
    """A job's runner, classified from its ``labels`` (the ``runs-on`` values)."""

    provider: RunnerProvider
    os: RunnerOS
    vcpu: int


def classify_runner(labels: list[str]) -> RunnerTier | None:
    """Classify the runner a job ran on from its ``labels``.

    Prefers a real Depot runner (only Depot is Depot-billed), else github-hosted; ``None`` when no
    label names a recognized OS. A Depot label is anchored to the ``depot-`` prefix AND a known OS
    token so labels that merely contain "depot" (``depot-only``, ``depot-cache-linux``) aren't costed.
    """
    hosted_os: RunnerOS | None = None
    for label in labels:
        os_ = _os_from_label(label)
        if os_ is None:
            continue
        if label.lower().startswith(_DEPOT_PREFIX):
            return RunnerTier(provider=RunnerProvider.DEPOT, os=os_, vcpu=_depot_vcpu(label))
        hosted_os = hosted_os or os_  # first recognized hosted label; Depot still wins if one follows
    if hosted_os is not None:
        return RunnerTier(provider=RunnerProvider.GITHUB_HOSTED, os=hosted_os, vcpu=_DEFAULT_DEPOT_VCPU)
    return None


def _os_from_label(label: str) -> RunnerOS | None:
    """The OS a runner label names, or ``None`` when it names no recognized OS."""
    lowered = label.lower()
    return next((os_ for token, os_ in _OS_BY_TOKEN.items() if token in lowered), None)


def _depot_vcpu(label: str) -> int:
    """vCPU count from a Depot label's optional trailing size segment.

    Depot labels are ``depot-<os>-<version>[-<vcpu>]``, so the size is only ever the 4th-or-later
    segment. A bare-integer OS version (``depot-macos-14``) sits in the version slot and must not be
    read as a core count — hence the segment-position check rather than a trailing-digits regex.
    """
    segments = label.split("-")
    # isdecimal (not isdigit): isdigit accepts unicode digits like superscripts that int() rejects.
    if len(segments) >= 4 and segments[-1].isdecimal():
        return int(segments[-1])
    return _DEFAULT_DEPOT_VCPU


def billing_multiplier(tier: RunnerTier) -> int:
    """Depot billing multiplier for a tier; unknown sizes fall back to vcpu/2 (>=1)."""
    return _MULTIPLIER_BY_VCPU.get(tier.vcpu, max(1, tier.vcpu // 2))


def runner_descriptor(labels: list[str]) -> tuple[str, str]:
    """Provider + human tier label for a job's runner, for display badges.

    Returns ``(provider, label)`` where provider is ``'github_hosted'`` (free), ``'self_hosted'``
    (billable — currently Depot), or ``'unknown'``. The label is the tier: ``'16-core'`` for
    self-hosted Linux, the raw ``runs-on`` for GitHub-hosted, or the OS for non-Linux self-hosted.
    """
    tier = classify_runner(labels)
    if tier is None:
        return "unknown", (labels[0] if labels else "")
    if tier.provider is RunnerProvider.GITHUB_HOSTED:
        return "github_hosted", (labels[0] if labels else tier.os.value)
    if tier.os is RunnerOS.LINUX:
        return "self_hosted", f"{tier.vcpu}-core"
    return "self_hosted", tier.os.value


def estimate_job_cost_usd(labels: list[str], elapsed_seconds: float | None) -> float | None:
    """Estimated Depot dollar cost for one job, or ``None`` when no honest figure exists.

    ``None`` means "no Depot cost to report": github-hosted, unclassifiable runner, a non-Linux Depot
    tier (macOS/Windows not modeled yet), OR unknown elapsed time (queued/not-started). That last case
    is deliberately distinct from a job that ran for no measurable time (``started_at == completed_at``
    or clock skew), a real measured ``0.0`` — summing skips ``None`` jobs, so a queued job is never
    shown as ``$0.00``.
    """
    tier = classify_runner(labels)
    if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is not RunnerOS.LINUX:
        return None
    if elapsed_seconds is None:
        return None
    if elapsed_seconds <= 0:
        return 0.0
    return (elapsed_seconds / 60) * REFERENCE_RATE_USD_PER_MIN * billing_multiplier(tier)


@dataclass(frozen=True)
class PRCostAggregate:
    """One PR's job costs rolled up — billable (self-hosted Linux) runners only.

    ``billable_seconds`` / ``estimated_cost_usd`` cover only the costed jobs (billable Linux, finished).
    ``unsettled_jobs`` are billable Linux jobs with no elapsed (still queued/running), excluded from
    cost. ``excluded_jobs`` ran on provider-hosted or non-Linux runners. ``estimated_cost_usd`` is
    ``None`` when no job was costable, distinguishing "nothing to cost" from a real ``$0.00``.
    """

    billable_seconds: float
    estimated_cost_usd: float | None
    costed_jobs: int
    unsettled_jobs: int
    excluded_jobs: int


def aggregate_pr_cost(jobs: Iterable[tuple[list[str], float | None]]) -> PRCostAggregate:
    """Sum per-job cost over a PR's jobs, partitioning each by why it does (or doesn't) count.

    Each input is one job's ``(labels, elapsed_seconds)``. A job counts only when its runner is a
    billable self-hosted Linux tier AND it has elapsed time; else it lands in ``unsettled_jobs``
    (Linux, no elapsed) or ``excluded_jobs`` (provider-hosted / non-Linux). Currently Depot-shaped.
    """
    billable_seconds = 0.0
    total_cost = 0.0
    costed = unsettled = excluded = 0
    for labels, elapsed_seconds in jobs:
        tier = classify_runner(labels)
        if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is not RunnerOS.LINUX:
            excluded += 1
            continue
        if elapsed_seconds is None:
            unsettled += 1
            continue
        billable_seconds += max(0.0, elapsed_seconds)
        total_cost += estimate_job_cost_usd(labels, elapsed_seconds) or 0.0
        costed += 1
    return PRCostAggregate(
        billable_seconds=billable_seconds,
        estimated_cost_usd=total_cost if costed else None,
        costed_jobs=costed,
        unsettled_jobs=unsettled,
        excluded_jobs=excluded,
    )
