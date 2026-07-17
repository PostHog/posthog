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

    Prefers a real Depot runner (only Depot runners are Depot-billed), else a github-hosted
    runner; returns ``None`` when no label names a recognized OS. A Depot runner label is
    ``depot-<os>-...`` — anchored to the prefix AND a known OS token so organizational/cache
    labels that merely contain "depot" (``depot-only``, ``depot-docker-cache``) or a
    ``depot-`` prefixed non-runner label (``depot-cache-linux``) are not costed as a runner.
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

    Depot labels are ``depot-<os>-<version>[-<vcpu>]`` (e.g. ``depot-ubuntu-22.04-4``), so the
    size is the segment after the version and is only ever the 4th-or-later segment. A
    bare-integer OS version (``depot-macos-14``, ``depot-windows-2022``) sits in the version
    slot and must not be read as a core count — hence the explicit segment position rather
    than a trailing-digits regex, which would mis-read those non-Linux versions as vCPUs.
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

    Returns ``(provider, label)`` where provider is ``'github_hosted'`` (free for open source),
    ``'self_hosted'`` (billable — currently Depot), or ``'unknown'``. Provider-neutral on purpose so
    other CI providers slot in. The label is the tier: ``'16-core'`` for self-hosted Linux, the raw
    ``runs-on`` (e.g. ``'ubuntu-latest'``) for GitHub-hosted, or the OS for non-Linux self-hosted.
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
    """Provider badge + human tier label from an already-classified ``(provider, os, vcpu)`` tuple — the
    display form of ``runner_descriptor`` for callers that group by the rendered tier columns (the job
    cost source's ``provider`` / ``os`` / ``vcpu``) rather than raw labels. Same mapping as
    ``runner_descriptor``, minus the raw-label fallback: grouped by tier there is no single ``runs-on``
    to echo, so a github-hosted or unclassified tier reads as its OS (or ``''``) instead of the label.
    ``provider`` is the ``render_provider`` output — ``'depot'`` / ``'github_hosted'`` / ``None``.
    """
    if provider is None:
        return "unknown", ""
    if provider == RunnerProvider.GITHUB_HOSTED.value:
        return "github_hosted", (os or "")
    # Depot is the only billed provider — it maps to the 'self_hosted' badge; Linux reads as '<vcpu>-core'.
    if os == RunnerOS.LINUX.value:
        return "self_hosted", f"{vcpu}-core"
    return "self_hosted", (os or "")


def estimate_job_cost_usd(labels: list[str], elapsed_seconds: float | None) -> float | None:
    """Estimated Depot dollar cost for one job, or ``None`` when no honest figure exists.

    ``None`` means "no Depot cost to report": the job is github-hosted, its runner can't be
    classified, it ran on a non-Linux Depot tier (macOS / Windows — separate price tiers not
    modeled yet, so excluded rather than mis-costed at the Linux rate), OR its elapsed time is
    unknown (a queued / not-yet-started job). That last case is deliberately distinct from a
    job that ran for no measurable time (``started_at == completed_at`` or clock skew), which
    is a real, measured ``0.0``: a consumer summing per-PR cost skips ``None`` jobs, so a queued
    job is never silently shown as ``$0.00``.
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

    ``billable_seconds`` and ``estimated_cost_usd`` cover only the costed jobs (billable Linux,
    finished). ``unsettled_jobs`` are billable Linux jobs with no elapsed time (still queued/running)
    — excluded from cost so a not-yet-finished job is never shown as ``$0.00``. ``excluded_jobs`` ran
    on provider-hosted (GitHub-hosted, free) or non-Linux runners, which carry no billable figure here.
    ``estimated_cost_usd`` is ``None`` when no job was costable, distinguishing "nothing to cost" from
    a real ``$0.00``.
    """

    billable_seconds: float
    estimated_cost_usd: float | None
    costed_jobs: int
    unsettled_jobs: int
    excluded_jobs: int


# --- HogQL renderer -------------------------------------------------------------------
# The same cost model, rendered as HogQL expression strings so a warehouse view can compute
# provider / os / vcpu / multiplier / billable_seconds / estimated_cost_usd in ClickHouse
# without leaving Python as the single source of truth. Every expression is generated from the
# constants above (never a literal duplicate of a rate, prefix, OS token, or multiplier), so the
# view SQL can only ever drift from the Python model if these constants change — which the
# ClickHouse-backed parity test guards against. Each renderer takes SQL expression strings for
# its inputs and returns a HogQL expression; the caller (logic.views.job_costs) threads them
# through nested subqueries so the two label picks (``render_depot_label`` / ``render_hosted_label``)
# and then provider/os/vcpu are each computed once per row and reused. Parity-critical notes mirror
# classify_runner / _depot_vcpu / billing_multiplier / estimate_job_cost_usd exactly.


def _has_os_token_sql(label_sql: str) -> str:
    """True when the label names a recognized OS — the substring test of ``_os_from_label``."""
    checks = " OR ".join(f"position(lowerUTF8({label_sql}), '{token}') > 0" for token in _OS_BY_TOKEN)
    return f"({checks})"


def _os_of_label_sql(label_sql: str) -> str:
    """The OS a label names, in ``_OS_BY_TOKEN`` priority order (ubuntu > macos > windows) — the
    ``multiIf`` form of ``_os_from_label``'s first-match-wins over the dict."""
    branches: list[str] = []
    for token, os_ in _OS_BY_TOKEN.items():
        branches.append(f"position(lowerUTF8({label_sql}), '{token}') > 0")
        branches.append(f"'{os_.value}'")
    return "multiIf(" + ", ".join(branches) + ", NULL)"


def _depot_vcpu_sql(label_sql: str) -> str:
    """vCPU from a Depot label's trailing size segment — the SQL form of ``_depot_vcpu``.

    Split on '-'; only the 4th-or-later segment can be a size, so a bare-integer OS version
    (``depot-macos-14``) in the version slot is never read as vcpu. ``match(..., '^[0-9]+$')`` is
    the parity of Python ``str.isdecimal`` (plain ASCII digits — ``isdecimal`` rejects the unicode
    digits ``int()`` would too, so an ASCII-only regex matches its accept set here).
    """
    segments = f"splitByChar('-', {label_sql})"
    last = f"arrayElement({segments}, length({segments}))"
    return f"if(length({segments}) >= 4 AND match({last}, '^[0-9]+$'), toInt({last}), {_DEFAULT_DEPOT_VCPU})"


def render_depot_label(labels_array_sql: str) -> str:
    """First label (array order) that is a real Depot runner: ``depot-`` prefixed AND names an OS.
    Empty string when none — Depot wins over hosted because provider/os/vcpu test this first.

    This is the expensive ``arrayFilter`` label scan, so the caller computes it once as its own
    column and feeds that column (not the array) into ``render_provider`` / ``render_os`` / ``render_vcpu``.
    """
    is_depot = f"(startsWith(lowerUTF8(_label), '{_DEPOT_PREFIX}') AND {_has_os_token_sql('_label')})"
    return f"arrayElement(arrayFilter(_label -> {is_depot}, {labels_array_sql}), 1)"


def render_hosted_label(labels_array_sql: str) -> str:
    """First label (array order) that names an OS but is NOT ``depot-`` prefixed — the
    github-hosted fallback (``hosted_os`` in ``classify_runner``). Empty string when none.

    Like ``render_depot_label``, the expensive ``arrayFilter`` scan — computed once as its own
    column and reused across the provider/os/vcpu renderers.
    """
    is_hosted = f"(NOT startsWith(lowerUTF8(_label), '{_DEPOT_PREFIX}') AND {_has_os_token_sql('_label')})"
    return f"arrayElement(arrayFilter(_label -> {is_hosted}, {labels_array_sql}), 1)"


def render_provider(depot_label_sql: str, hosted_label_sql: str) -> str:
    """RunnerProvider value ('depot' / 'github_hosted') or NULL — the SQL form of
    ``classify_runner(...).provider`` over the two precomputed label picks (``render_depot_label`` /
    ``render_hosted_label``). Depot before hosted (Depot is the only billed provider)."""
    return (
        f"multiIf({depot_label_sql} != '', '{RunnerProvider.DEPOT.value}', "
        f"{hosted_label_sql} != '', '{RunnerProvider.GITHUB_HOSTED.value}', NULL)"
    )


def render_os(depot_label_sql: str, hosted_label_sql: str) -> str:
    """RunnerOS value ('linux' / 'macos' / 'windows') or NULL — the OS of the winning label (the
    precomputed Depot label if any, else the hosted one), matching ``classify_runner(...).os``. Both
    inputs are the label-pick columns from ``render_depot_label`` / ``render_hosted_label``, so this is
    a cheap ``multiIf`` over string columns, not a re-scan of the labels array."""
    return (
        f"multiIf({depot_label_sql} != '', {_os_of_label_sql(depot_label_sql)}, "
        f"{hosted_label_sql} != '', {_os_of_label_sql(hosted_label_sql)}, NULL)"
    )


def render_vcpu(depot_label_sql: str, hosted_label_sql: str) -> str:
    """vCPU of the winning runner or NULL — Depot reads its size segment, github-hosted is the
    2-vCPU default (``_DEFAULT_DEPOT_VCPU``), matching ``classify_runner(...).vcpu``. Both inputs are
    the precomputed label-pick columns (``render_depot_label`` / ``render_hosted_label``)."""
    return (
        f"multiIf({depot_label_sql} != '', {_depot_vcpu_sql(depot_label_sql)}, "
        f"{hosted_label_sql} != '', {_DEFAULT_DEPOT_VCPU}, NULL)"
    )


def render_multiplier(vcpu_sql: str) -> str:
    """Depot billing multiplier for a vCPU count, or NULL when vcpu is NULL — the SQL form of
    ``billing_multiplier``: the ``_MULTIPLIER_BY_VCPU`` ladder, else ``max(1, vcpu // 2)``."""
    branches: list[str] = []
    for vcpu, multiplier in _MULTIPLIER_BY_VCPU.items():
        branches.append(f"{vcpu_sql} = {vcpu}")
        branches.append(f"{multiplier}")
    ladder = "multiIf(" + ", ".join(branches) + f", greatest(1, intDiv({vcpu_sql}, 2)))"
    return f"if({vcpu_sql} IS NULL, NULL, {ladder})"


def render_is_billable_tier(provider_sql: str, os_sql: str) -> str:
    """SQL predicate: True when a job's classified tier is billable — self-hosted Linux (Depot Linux,
    the only modeled billed tier). Generated from the enums so ``'depot'`` / ``'linux'`` never appear
    as string literals in the query layer. NULL-safe: an unclassified tier (``provider`` NULL) reads as
    not billable. This is the one place the billable-partition rule is spelled out; the endpoint cost
    aggregates and the two renderers below all read it, so the three-bucket split can't drift."""
    return f"ifNull({provider_sql} = '{RunnerProvider.DEPOT.value}' AND {os_sql} = '{RunnerOS.LINUX.value}', 0)"


def render_billable_seconds(provider_sql: str, os_sql: str, elapsed_sql: str) -> str:
    """Raw billable wall-clock seconds (NOT multiplier-weighted): ``greatest(elapsed, 0)`` only for
    a billable self-hosted Linux job with a known elapsed, else NULL — mirrors the ``max(0, elapsed)``
    a costed job contributes to a PR's ``billable_seconds``."""
    billable = render_is_billable_tier(provider_sql, os_sql)
    return f"if({billable} AND {elapsed_sql} IS NOT NULL, greatest({elapsed_sql}, 0), NULL)"


def render_estimated_cost_usd(provider_sql: str, os_sql: str, vcpu_sql: str, elapsed_sql: str) -> str:
    """Estimated Depot dollar cost for one job — the SQL form of ``estimate_job_cost_usd``:
    NULL when not billable (non-Depot / non-Linux / unclassified) and NULL for an unsettled job
    (elapsed unknown, never $0.00), a real 0.0 for non-positive elapsed, else
    ``(elapsed / 60) * REFERENCE_RATE_USD_PER_MIN * multiplier``."""
    is_depot_linux = render_is_billable_tier(provider_sql, os_sql)
    cost = f"({elapsed_sql} / 60) * {REFERENCE_RATE_USD_PER_MIN} * {render_multiplier(vcpu_sql)}"
    return f"multiIf(NOT {is_depot_linux}, NULL, {elapsed_sql} IS NULL, NULL, {elapsed_sql} <= 0, 0.0, {cost})"
