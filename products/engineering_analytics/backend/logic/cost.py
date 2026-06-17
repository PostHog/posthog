"""Depot CI cost model for engineering_analytics.

Estimates the Depot dollar cost of CI from GitHub Actions job data. GitHub's jobs
API exposes wall-clock (``started_at`` -> ``completed_at``) and the requested runner
``labels`` -- not Depot's billed minutes -- so every figure here is an estimate:
``elapsed_minutes x tier_multiplier x reference_rate``. This mirrors the model the
DevEx Depot cost tooling already uses (list price, per-vCPU multiplier ladder).

GitHub/Depot specifics (the ``depot-*`` label shapes, the rate ladder) live here in
the read layer per SPEC section 3; provider-neutral contract types stay in
``facade/contracts.py``.

Cost is fundamentally job-level: a workflow run fans into parallel jobs on different
runner tiers, so per-PR cost is a sum over jobs. ``github_workflow_runs`` alone -- one
wall-clock window, no runner label -- cannot produce it. These functions are pure and
source-agnostic so they are unit-tested today and wired to the ``github_workflow_jobs``
warehouse source once it lands (see SPEC section 6/9).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

# Depot list price for one billed minute at the 2-vCPU base tier. Depot bills 2cpu
# at 1x and doubles the multiplier per vCPU doubling, so billed = elapsed x multiplier
# and cost = elapsed_minutes x REFERENCE_RATE_USD_PER_MIN x multiplier. Hardcoded for
# v1 like KNOWN_BOT_HANDLES; a team-scoped rate + negotiated-discount config is the
# documented follow-up (SPEC section 7).
REFERENCE_RATE_USD_PER_MIN = 0.004

# Depot billing multiplier per vCPU count (2cpu = 1x, doubling each step).
_MULTIPLIER_BY_VCPU: dict[int, int] = {2: 1, 4: 2, 8: 4, 16: 8, 32: 16, 64: 32}

# A Depot Linux runner with no explicit size suffix is the 2-vCPU default
# (e.g. ``depot-ubuntu-latest``).
_DEFAULT_DEPOT_VCPU = 2

# Trailing vCPU size on a Depot label, e.g. the ``-4`` in ``depot-ubuntu-22.04-4``.
_DEPOT_SIZE_RE = re.compile(r"-(\d+)$")


class RunnerProvider(StrEnum):
    DEPOT = "depot"
    GITHUB_HOSTED = "github_hosted"


class RunnerOS(StrEnum):
    LINUX = "linux"
    MACOS = "macos"


@dataclass(frozen=True)
class RunnerTier:
    """A job's runner, classified from its ``labels`` (the ``runs-on`` values)."""

    provider: RunnerProvider
    os: RunnerOS
    vcpu: int


def classify_runner(labels: list[str]) -> RunnerTier | None:
    """Classify the runner a job ran on from its ``labels``.

    Prefers a ``depot-*`` label (only Depot runners are Depot-billed); falls back to
    a github-hosted label. Returns ``None`` when no label identifies a runner. A
    Depot label with no ``-<n>`` size suffix is the 2-vCPU default.
    """
    depot = next((label for label in labels if "depot" in label.lower()), None)
    if depot is not None:
        match = _DEPOT_SIZE_RE.search(depot)
        return RunnerTier(
            provider=RunnerProvider.DEPOT,
            os=_os_from_label(depot),
            vcpu=int(match.group(1)) if match else _DEFAULT_DEPOT_VCPU,
        )
    hosted = next((label for label in labels if _is_hosted_label(label)), None)
    if hosted is not None:
        return RunnerTier(provider=RunnerProvider.GITHUB_HOSTED, os=_os_from_label(hosted), vcpu=_DEFAULT_DEPOT_VCPU)
    return None


def _os_from_label(label: str) -> RunnerOS:
    return RunnerOS.MACOS if "macos" in label.lower() else RunnerOS.LINUX


def _is_hosted_label(label: str) -> bool:
    lowered = label.lower()
    return any(token in lowered for token in ("ubuntu", "macos", "windows"))


def billing_multiplier(tier: RunnerTier) -> int:
    """Depot billing multiplier for a tier; unknown sizes fall back to vcpu/2 (>=1)."""
    return _MULTIPLIER_BY_VCPU.get(tier.vcpu, max(1, tier.vcpu // 2))


def estimate_job_cost_usd(labels: list[str], elapsed_seconds: float | None) -> float | None:
    """Estimated Depot dollar cost for one job.

    ``None`` when the job is not Depot-billed (github-hosted), the runner can't be
    classified, or it ran on Depot macOS (a separate price tier not modeled yet -- so
    it is excluded rather than silently mis-costed). A non-positive / ``None`` elapsed
    (a queued or in-progress job) costs ``0.0``.
    """
    tier = classify_runner(labels)
    if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is RunnerOS.MACOS:
        return None
    if elapsed_seconds is None or elapsed_seconds <= 0:
        return 0.0
    return (elapsed_seconds / 60) * REFERENCE_RATE_USD_PER_MIN * billing_multiplier(tier)
