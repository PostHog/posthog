"""Temporal activities for the foundry-run-gate workflow: provisioning the artifact
sandbox and running each declared check inside it.

Pure check logic (diff parsing, report parsing, heuristics) lives in ``logic/gauntlet.py``;
these activities are the thin sandbox-facing shell around it. Every check activity catches
its own sandbox-facing exceptions and returns a normal (failing) ``CheckOutcome`` rather than
raising, so a crash never leaves the workflow hanging — the workflow's own try/except around
each ``execute_activity`` call is a second net for anything that still escapes (e.g. the
sandbox itself failing to provision).
"""

from __future__ import annotations

import time
import shlex
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.facade.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class_for_backend

from ..logic import gauntlet
from .gate_constants import GATE_WORKDIR


def _resolve_sandbox_backend() -> str:
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    return provider if provider else "modal"


# ---- provisioning ----


@dataclass
class ProvisionGateSandboxInput:
    bet_id: str
    repo_url: str
    ref: str
    base_ref: str
    template: str = SandboxTemplate.SLIM_BASE.value


@dataclass
class ProvisionGateSandboxOutput:
    sandbox_id: str
    changed_files: list[str] = field(default_factory=list)
    diff_text: str = ""
    # Set when checkout/diff itself failed (bad repo_url/ref/base_ref) rather than any
    # individual check — sandbox-dependent checks all fail with this as their detail, but
    # sandbox-independent ones (reviewhog) still run.
    checkout_error: str | None = None


@activity.defn
@asyncify
def provision_gate_sandbox_activity(input: ProvisionGateSandboxInput) -> ProvisionGateSandboxOutput:
    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    sandbox = sandbox_class.create(
        SandboxConfig(name=f"foundry-gate-{input.bet_id}"[:63], template=SandboxTemplate(input.template))
    )
    clone = sandbox.execute(f"git clone {shlex.quote(input.repo_url)} {shlex.quote(GATE_WORKDIR)}", timeout_seconds=120)
    if clone.exit_code != 0:
        return ProvisionGateSandboxOutput(
            sandbox_id=sandbox.id, checkout_error=f"git clone failed: {clone.stderr[:300]}"
        )

    diff = sandbox.execute(
        f"cd {shlex.quote(GATE_WORKDIR)} && git checkout {shlex.quote(input.ref)} "
        f"&& git diff {shlex.quote(input.base_ref)} {shlex.quote(input.ref)}",
        timeout_seconds=60,
    )
    if diff.exit_code != 0:
        return ProvisionGateSandboxOutput(
            sandbox_id=sandbox.id, checkout_error=f"checkout/diff failed: {diff.stderr[:300]}"
        )

    return ProvisionGateSandboxOutput(
        sandbox_id=sandbox.id,
        changed_files=gauntlet.changed_files_from_diff(diff.stdout),
        diff_text=diff.stdout,
    )


@dataclass
class TeardownGateSandboxInput:
    sandbox_id: str


@activity.defn
@asyncify
def teardown_gate_sandbox_activity(input: TeardownGateSandboxInput) -> None:
    sandbox_class = get_sandbox_class_for_backend(_resolve_sandbox_backend())
    try:
        sandbox_class.get_by_id(input.sandbox_id).destroy()
    except Exception:
        activity.logger.exception(f"foundry gate: failed to destroy sandbox {input.sandbox_id}")


# ---- command check ----


@dataclass
class RunCommandCheckInput:
    sandbox_id: str
    command: str


@activity.defn
@asyncify
def run_command_check_activity(input: RunCommandCheckInput) -> gauntlet.CheckOutcome:
    sandbox = get_sandbox_class_for_backend(_resolve_sandbox_backend()).get_by_id(input.sandbox_id)
    try:
        result = sandbox.execute(f"cd {shlex.quote(GATE_WORKDIR)} && {input.command}", timeout_seconds=300)
    except Exception as e:
        return gauntlet.CheckOutcome(passed=False, detail=f"command crashed or timed out: {e}")
    if result.exit_code == 0:
        return gauntlet.CheckOutcome(passed=True, detail="exit code 0")
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
    return gauntlet.CheckOutcome(passed=False, detail=f"exit code {result.exit_code}:\n{tail}")


# ---- coverage check ----


@dataclass
class RunCoverageCheckInput:
    sandbox_id: str
    command: str
    report_format: str
    report_path: str
    min_changed_line_pct: float
    diff_text: str


@activity.defn
@asyncify
def run_coverage_check_activity(input: RunCoverageCheckInput) -> gauntlet.CheckOutcome:
    sandbox = get_sandbox_class_for_backend(_resolve_sandbox_backend()).get_by_id(input.sandbox_id)
    try:
        run_result = sandbox.execute(f"cd {shlex.quote(GATE_WORKDIR)} && {input.command}", timeout_seconds=600)
    except Exception as e:
        return gauntlet.CheckOutcome(passed=False, detail=f"coverage command crashed or timed out: {e}")
    if run_result.exit_code != 0:
        tail = "\n".join((run_result.stdout + run_result.stderr).splitlines()[-20:])
        return gauntlet.CheckOutcome(
            passed=False, detail=f"coverage command failed (exit {run_result.exit_code}):\n{tail}"
        )

    report_path = f"{GATE_WORKDIR}/{input.report_path}"
    try:
        cat_result = sandbox.execute(f"cat {shlex.quote(report_path)}", timeout_seconds=30)
    except Exception as e:
        return gauntlet.CheckOutcome(passed=False, detail=f"could not read coverage report: {e}")
    if cat_result.exit_code != 0:
        return gauntlet.CheckOutcome(passed=False, detail=f"coverage report not found at {input.report_path}")

    return gauntlet.coverage_check_outcome(
        diff_text=input.diff_text,
        report_content=cat_result.stdout,
        report_format=input.report_format,
        min_changed_line_pct=input.min_changed_line_pct,
    )


# ---- mutation check ----


@dataclass
class RunMutationCheckInput:
    sandbox_id: str
    command_template: str
    changed_files: list[str]
    min_score_pct: float
    max_minutes: int


@activity.defn
@asyncify
def run_mutation_check_activity(input: RunMutationCheckInput) -> gauntlet.CheckOutcome:
    sandbox = get_sandbox_class_for_backend(_resolve_sandbox_backend()).get_by_id(input.sandbox_id)
    command = gauntlet.resolve_mutation_command(input.command_template, input.changed_files)
    try:
        # The sandbox's own timeout is the time-box: max_minutes is never exceeded, whether
        # the run finishes, hangs, or mutmut itself takes too long.
        sandbox.execute(f"cd {shlex.quote(GATE_WORKDIR)} && {command}", timeout_seconds=input.max_minutes * 60)
    except Exception as e:
        return gauntlet.CheckOutcome(
            passed=False, detail=f"mutation testing crashed or exceeded max_minutes={input.max_minutes}: {e}"
        )

    report_path = f"{GATE_WORKDIR}/{gauntlet.MUTATION_REPORT_PATH}"
    try:
        cat_result = sandbox.execute(f"cat {shlex.quote(report_path)}", timeout_seconds=30)
    except Exception as e:
        return gauntlet.CheckOutcome(passed=False, detail=f"could not read mutation report: {e}")
    if cat_result.exit_code != 0:
        return gauntlet.CheckOutcome(passed=False, detail="mutation report not produced")

    return gauntlet.mutation_check_outcome(report_content=cat_result.stdout, min_score_pct=input.min_score_pct)


# ---- protected_paths + flag_guard (pure, but wrapped as activities for uniform note/crash handling) ----


@dataclass
class RunProtectedPathsCheckInput:
    changed_files: list[str]
    protected_paths: list[str]


@activity.defn
@asyncify
def run_protected_paths_check_activity(input: RunProtectedPathsCheckInput) -> gauntlet.CheckOutcome:
    return gauntlet.protected_paths_check_outcome(input.changed_files, input.protected_paths)


@dataclass
class RunFlagGuardCheckInput:
    diff_text: str
    changed_files: list[str]
    flag_key: str
    exempt_paths: list[str]


@activity.defn
@asyncify
def run_flag_guard_check_activity(input: RunFlagGuardCheckInput) -> gauntlet.CheckOutcome:
    return gauntlet.flag_guard_check_outcome(
        diff_text=input.diff_text,
        changed_files=input.changed_files,
        flag_key=input.flag_key,
        exempt_paths=input.exempt_paths,
    )


# ---- reviewhog check ----


@dataclass
class RunReviewhogCheckInput:
    team_id: int
    created_by_id: int | None
    pr_url: str | None
    poll_interval_seconds: int = 15
    max_poll_attempts: int = 40


@activity.defn
@asyncify
def run_reviewhog_check_activity(input: RunReviewhogCheckInput) -> gauntlet.CheckOutcome:
    """Trigger a ReviewHog review turn for the artifact's PR and poll it to completion.

    Never fails the gate on ReviewHog being unavailable, unconfigured, or too slow to finish
    in time — this preserves ADR-2's contract that the state machine is never blocked on
    ReviewHog. Those outcomes come back ``passed=True`` with a 'skipped: ...' detail,
    regardless of whether this check is ``required``. Only a genuine crash (an exception
    escaping this function) surfaces as a real failure, via the workflow's crash handling.

    No ``activity.heartbeat()`` in the poll loop: this function runs under ``@asyncify``,
    which hands the call to Django's ``sync_to_async`` thread — a different thread than the
    one the Temporal SDK associates with this activity's execution context, so a heartbeat
    call here can't reach it. The workflow's ``start_to_close_timeout`` alone bounds the poll.
    """
    # Deferred: review_hog's temporal client (pulled in transitively via its facade) drags in
    # temporalio, which we'd rather not load on every foundry activity-module import.
    from products.review_hog.backend.facade import api as review_hog_api  # noqa: PLC0415

    if not input.pr_url:
        return gauntlet.CheckOutcome(passed=True, detail="skipped: no pr_url on the artifact")
    if not review_hog_api.is_review_available_for_team(input.team_id):
        return gauntlet.CheckOutcome(passed=True, detail="skipped: ReviewHog is not enabled for this project")
    if input.created_by_id is None:
        return gauntlet.CheckOutcome(passed=True, detail="skipped: bet has no creator to run the review as")

    trigger = review_hog_api.trigger_review(team_id=input.team_id, user_id=input.created_by_id, pr_url=input.pr_url)
    if not trigger.started:
        return gauntlet.CheckOutcome(
            passed=True, detail=f"skipped: {trigger.reason or 'ReviewHog could not start a review'}"
        )

    for _attempt in range(input.max_poll_attempts):
        status = review_hog_api.get_review_status(team_id=input.team_id, pr_url=input.pr_url)
        if status is not None and not status.in_progress:
            violations: list[dict[str, Any]] = [
                {"code": v.code, "message": v.message, "severity": v.severity} for v in status.violations
            ]
            blocking = [v for v in violations if v["severity"] == "must_fix"]
            if blocking:
                return gauntlet.CheckOutcome(
                    passed=False,
                    detail=f"{len(blocking)} blocking finding(s): " + "; ".join(v["message"] for v in blocking),
                )
            return gauntlet.CheckOutcome(passed=True, detail=f"review passed ({len(violations)} advisory finding(s))")
        time.sleep(input.poll_interval_seconds)
    return gauntlet.CheckOutcome(passed=True, detail="skipped: timed out waiting for the ReviewHog review")
