"""Depot cost model for CI jobs.

GitHub's jobs API reports wall-clock time and the requested runner ``labels``, not Depot's billed
minutes, so every figure is an estimate: ``billed_minutes x tier_multiplier x reference_rate``.

GitHub stamps ``started_at`` when Depot accepts the job, and the machine boots before the first step
runs. Depot bills only the time after the boot, so the cost functions take
``billed_elapsed_seconds``, not the wall-clock duration.

The ``render_*`` functions give the same model as HogQL expressions. Each is generated from the
constants here, and a ClickHouse-backed parity test compares the two.
"""

from dataclasses import dataclass
from enum import StrEnum

# Depot list price for one billed minute at the 2-vCPU tier.
REFERENCE_RATE_USD_PER_MIN = 0.004

# Depot CI list price. Depot CI bills vCPU-seconds, not runner minutes.
DEPOT_CI_RATE_USD_PER_VCPU_SECOND = 0.00005

_MULTIPLIER_BY_VCPU: dict[int, int] = {2: 1, 4: 2, 8: 4, 16: 8, 32: 16, 64: 32}

# The size of a Depot runner whose label has no size suffix, such as ``depot-ubuntu-latest``.
_DEFAULT_DEPOT_VCPU = 2

_DEPOT_PREFIX = "depot-"


class RunnerProvider(StrEnum):
    DEPOT = "depot"
    GITHUB_HOSTED = "github_hosted"


class RunnerOS(StrEnum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


_OS_BY_TOKEN: dict[str, RunnerOS] = {
    "ubuntu": RunnerOS.LINUX,
    "macos": RunnerOS.MACOS,
    "windows": RunnerOS.WINDOWS,
}


@dataclass(frozen=True)
class RunnerTier:
    provider: RunnerProvider
    os: RunnerOS
    vcpu: int


def classify_runner(labels: list[str]) -> RunnerTier | None:
    """The runner a job's ``labels`` name, or None when no label names a recognized OS.

    The first Depot label wins over any GitHub-hosted label. A Depot label needs both the ``depot-``
    prefix and an OS token, so a label such as ``depot-docker-cache`` is not costed as a runner.
    """
    hosted_os: RunnerOS | None = None
    for label in labels:
        os_ = _os_from_label(label)
        if os_ is None:
            continue
        if label.lower().startswith(_DEPOT_PREFIX):
            return RunnerTier(provider=RunnerProvider.DEPOT, os=os_, vcpu=_depot_vcpu(label))
        hosted_os = hosted_os or os_
    if hosted_os is not None:
        return RunnerTier(provider=RunnerProvider.GITHUB_HOSTED, os=hosted_os, vcpu=_DEFAULT_DEPOT_VCPU)
    return None


def _os_from_label(label: str) -> RunnerOS | None:
    lowered = label.lower()
    return next((os_ for token, os_ in _OS_BY_TOKEN.items() if token in lowered), None)


def _depot_vcpu(label: str) -> int:
    """The vCPU count from a Depot label of the form ``depot-<os>-<version>[-<vcpu>]``.

    Only a fourth or later segment is a size. An integer OS version such as ``depot-macos-14`` sits
    in the third segment and is not a core count.
    """
    segments = label.split("-")
    # ``isdigit`` accepts unicode digits such as superscripts, which ``int()`` rejects.
    if len(segments) >= 4 and segments[-1].isdecimal():
        return int(segments[-1])
    return _DEFAULT_DEPOT_VCPU


def billing_multiplier(tier: RunnerTier) -> int:
    """The Depot billing multiplier for a tier. A size outside the ladder gets ``vcpu // 2``, at least 1."""
    return _MULTIPLIER_BY_VCPU.get(tier.vcpu, max(1, tier.vcpu // 2))


def runner_descriptor(labels: list[str]) -> tuple[str, str]:
    """``(provider, tier label)`` for display.

    The provider is ``'github_hosted'``, ``'self_hosted'`` (a Depot runner) or ``'unknown'``. The label
    is ``'<vcpu>-core'`` for self-hosted Linux, the OS for other self-hosted runners, and the first
    raw label otherwise.
    """
    tier = classify_runner(labels)
    if tier is None:
        return "unknown", (labels[0] if labels else "")
    if tier.provider is RunnerProvider.GITHUB_HOSTED:
        return "github_hosted", (labels[0] if labels else tier.os.value)
    if tier.os is RunnerOS.LINUX:
        return "self_hosted", f"{tier.vcpu}-core"
    return "self_hosted", tier.os.value


def runner_tier_descriptor(provider: str | None, os: str | None, vcpu: int | None) -> tuple[str, str]:
    """``runner_descriptor`` for a tier that ``render_provider``, ``render_os`` and ``render_vcpu`` already
    classified. With no raw label to show, a GitHub-hosted tier reads as its OS and an unclassified
    tier as ''.
    """
    if provider is None:
        return "unknown", ""
    if provider == RunnerProvider.GITHUB_HOSTED.value:
        return "github_hosted", (os or "")
    if os == RunnerOS.LINUX.value:
        return "self_hosted", f"{vcpu}-core"
    return "self_hosted", (os or "")


def billed_elapsed_seconds(elapsed_seconds: float | None, provisioning_seconds: float | None) -> float | None:
    """The seconds Depot bills for one job: wall-clock elapsed minus provisioning, at least 0.

    A None ``provisioning_seconds`` subtracts nothing. A None ``elapsed_seconds`` (a job that has not
    finished) returns None, so it never reads as a measured zero.
    """
    if elapsed_seconds is None:
        return None
    return max(elapsed_seconds - (provisioning_seconds or 0), 0)


def estimate_job_cost_usd(
    labels: list[str], elapsed_seconds: float | None, *, is_rerun_copy: bool = False
) -> float | None:
    """The estimated Depot cost of one job in dollars. ``elapsed_seconds`` is ``billed_elapsed_seconds``.

    Returns None when the runner is not Depot Linux (other Depot price tiers are not modeled), when
    the row is a re-run copy that never executed, or when the elapsed time is unknown. A job with a
    known elapsed of zero or less costs 0.0.
    """
    tier = classify_runner(labels)
    if tier is None or tier.provider is not RunnerProvider.DEPOT or tier.os is not RunnerOS.LINUX:
        return None
    if is_rerun_copy:
        return None
    if elapsed_seconds is None:
        return None
    if elapsed_seconds <= 0:
        return 0.0
    return (elapsed_seconds / 60) * REFERENCE_RATE_USD_PER_MIN * billing_multiplier(tier)


def estimate_depot_ci_cost_usd(elapsed_seconds: float) -> float:
    # Depot's API reports no runs-on, so every attempt is priced as the default 2-vCPU sandbox.
    return elapsed_seconds * _DEFAULT_DEPOT_VCPU * DEPOT_CI_RATE_USD_PER_VCPU_SECOND


@dataclass(frozen=True)
class PRCostAggregate:
    """One pull request's job costs.

    ``billable_seconds`` and ``estimated_cost_usd`` cover the finished Depot Linux jobs.
    ``unsettled_jobs`` are Depot Linux jobs with no elapsed time yet. ``excluded_jobs`` ran on another
    runner tier or are re-run copies. ``estimated_cost_usd`` is None when no job was costed.
    """

    billable_seconds: float
    estimated_cost_usd: float | None
    costed_jobs: int
    unsettled_jobs: int
    excluded_jobs: int


# Each renderer below takes SQL expression strings and returns a HogQL expression that must give the
# same value as the Python function it names.


def _has_os_token_sql(label_sql: str) -> str:
    checks = " OR ".join(f"position(lowerUTF8({label_sql}), '{token}') > 0" for token in _OS_BY_TOKEN)
    return f"({checks})"


def _os_of_label_sql(label_sql: str) -> str:
    """The SQL form of ``_os_from_label``, with the same first-match order over ``_OS_BY_TOKEN``."""
    branches: list[str] = []
    for token, os_ in _OS_BY_TOKEN.items():
        branches.append(f"position(lowerUTF8({label_sql}), '{token}') > 0")
        branches.append(f"'{os_.value}'")
    return "multiIf(" + ", ".join(branches) + ", NULL)"


def _depot_vcpu_sql(label_sql: str) -> str:
    """The SQL form of ``_depot_vcpu``."""
    segments = f"splitByChar('-', {label_sql})"
    last = f"arrayElement({segments}, length({segments}))"
    return f"if(length({segments}) >= 4 AND match({last}, '^[0-9]+$'), toInt({last}), {_DEFAULT_DEPOT_VCPU})"


def render_depot_label(labels_array_sql: str) -> str:
    """The first label that has the ``depot-`` prefix and names an OS, or '' when there is none.

    The array scan is expensive, so compute this once as a column and pass that column to
    ``render_provider``, ``render_os`` and ``render_vcpu``.
    """
    is_depot = f"(startsWith(lowerUTF8(_label), '{_DEPOT_PREFIX}') AND {_has_os_token_sql('_label')})"
    return f"arrayElement(arrayFilter(_label -> {is_depot}, {labels_array_sql}), 1)"


def render_hosted_label(labels_array_sql: str) -> str:
    """The first label that names an OS and has no ``depot-`` prefix, or '' when there is none.

    Compute it once as a column, like ``render_depot_label``.
    """
    is_hosted = f"(NOT startsWith(lowerUTF8(_label), '{_DEPOT_PREFIX}') AND {_has_os_token_sql('_label')})"
    return f"arrayElement(arrayFilter(_label -> {is_hosted}, {labels_array_sql}), 1)"


def render_provider(depot_label_sql: str, hosted_label_sql: str) -> str:
    """The SQL form of ``classify_runner(...).provider``, or NULL. The inputs are the
    ``render_depot_label`` and ``render_hosted_label`` columns."""
    return (
        f"multiIf({depot_label_sql} != '', '{RunnerProvider.DEPOT.value}', "
        f"{hosted_label_sql} != '', '{RunnerProvider.GITHUB_HOSTED.value}', NULL)"
    )


def render_os(depot_label_sql: str, hosted_label_sql: str) -> str:
    """The SQL form of ``classify_runner(...).os``, or NULL. Same inputs as ``render_provider``."""
    return (
        f"multiIf({depot_label_sql} != '', {_os_of_label_sql(depot_label_sql)}, "
        f"{hosted_label_sql} != '', {_os_of_label_sql(hosted_label_sql)}, NULL)"
    )


def render_vcpu(depot_label_sql: str, hosted_label_sql: str) -> str:
    """The SQL form of ``classify_runner(...).vcpu``, or NULL. Same inputs as ``render_provider``."""
    return (
        f"multiIf({depot_label_sql} != '', {_depot_vcpu_sql(depot_label_sql)}, "
        f"{hosted_label_sql} != '', {_DEFAULT_DEPOT_VCPU}, NULL)"
    )


def render_multiplier(vcpu_sql: str) -> str:
    """The SQL form of ``billing_multiplier``, or NULL when the vCPU count is NULL."""
    branches: list[str] = []
    for vcpu, multiplier in _MULTIPLIER_BY_VCPU.items():
        branches.append(f"{vcpu_sql} = {vcpu}")
        branches.append(f"{multiplier}")
    ladder = "multiIf(" + ", ".join(branches) + f", greatest(1, intDiv({vcpu_sql}, 2)))"
    return f"if({vcpu_sql} IS NULL, NULL, {ladder})"


def render_is_billable_tier(provider_sql: str, os_sql: str) -> str:
    """SQL predicate: the tier is Depot Linux. An unclassified tier is not billable.

    To decide whether a job row costs money, use ``render_is_billable_job``.
    """
    return f"ifNull({provider_sql} = '{RunnerProvider.DEPOT.value}' AND {os_sql} = '{RunnerOS.LINUX.value}', 0)"


def render_is_billable_job(provider_sql: str, os_sql: str, is_rerun_copy_sql: str) -> str:
    """SQL predicate: the job row is on a billable tier and is not a re-run copy.

    A re-run copy is a passed job that GitHub lists again under a later ``run_attempt`` without running
    it, so Depot billed nothing for it. Every cost consumer must partition on this predicate.
    """
    return f"({render_is_billable_tier(provider_sql, os_sql)} AND NOT {is_rerun_copy_sql})"


def render_billed_elapsed_seconds(elapsed_sql: str, provisioning_sql: str) -> str:
    """The SQL form of ``billed_elapsed_seconds``. NULL exactly when the elapsed is NULL."""
    return f"if({elapsed_sql} IS NULL, NULL, greatest({elapsed_sql} - ifNull({provisioning_sql}, 0), 0))"


def render_billable_seconds(provider_sql: str, os_sql: str, is_rerun_copy_sql: str, elapsed_sql: str) -> str:
    """The elapsed seconds of a billable job row, at least 0 and not weighted by the multiplier.
    NULL when the row is not billable or the elapsed is NULL."""
    billable = render_is_billable_job(provider_sql, os_sql, is_rerun_copy_sql)
    return f"if({billable} AND {elapsed_sql} IS NOT NULL, greatest({elapsed_sql}, 0), NULL)"


def render_estimated_cost_usd(
    provider_sql: str, os_sql: str, vcpu_sql: str, is_rerun_copy_sql: str, elapsed_sql: str
) -> str:
    """The SQL form of ``estimate_job_cost_usd``."""
    is_billable = render_is_billable_job(provider_sql, os_sql, is_rerun_copy_sql)
    cost = f"({elapsed_sql} / 60) * {REFERENCE_RATE_USD_PER_MIN} * {render_multiplier(vcpu_sql)}"
    return f"multiIf(NOT {is_billable}, NULL, {elapsed_sql} IS NULL, NULL, {elapsed_sql} <= 0, 0.0, {cost})"
