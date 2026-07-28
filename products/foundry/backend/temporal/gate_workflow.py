"""The foundry-run-gate workflow: the gauntlet engine.

Provisions the artifact into a single sandbox and diffs it against ``base_ref``, then runs
every declared check (plus the implicit ``protected_paths`` check, when configured) against
that one sandbox — sequentially. Checks share a sandbox for cheapness (one clone, one
checkout), and run one at a time because mutation testing mutates the working tree in place
and cannot safely interleave with a concurrent command/coverage check; reviewhog is the only
check that isn't sandbox-bound, and runs in the same sequence for simplicity.

Every check emits a ``note`` BetEvent on start/finish for timeline visibility. The aggregate
always resolves to exactly one ``gate.result`` event — a check activity crashing or timing
out is caught and recorded as that check failing, never as the workflow hanging or erroring
out (see ``_execute_check``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import temporalio.workflow
from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

from .constants import RECORD_EVENT_RETRY_POLICY, RECORD_EVENT_TIMEOUT
from .gate_constants import (
    CHECK_RETRY_POLICY,
    COVERAGE_CHECK_TIMEOUT,
    DEFAULT_CHECK_TIMEOUT,
    PROVISION_TIMEOUT,
    REVIEWHOG_CHECK_TIMEOUT,
    REVIEWHOG_MAX_POLL_ATTEMPTS,
    REVIEWHOG_POLL_INTERVAL_SECONDS,
    TEARDOWN_TIMEOUT,
)

if TYPE_CHECKING:
    from ..logic.gauntlet import CheckOutcome

with temporalio.workflow.unsafe.imports_passed_through():
    from ..facade.enums import PROTECTED_PATHS_CHECK_TYPE, GateCheckType
    from .activities import RecordEventInput, record_bet_event_activity
    from .gate_activities import (
        ProvisionGateSandboxInput,
        ProvisionGateSandboxOutput,
        RunCommandCheckInput,
        RunCoverageCheckInput,
        RunFlagGuardCheckInput,
        RunMutationCheckInput,
        RunProtectedPathsCheckInput,
        RunReviewhogCheckInput,
        TeardownGateSandboxInput,
        provision_gate_sandbox_activity,
        run_command_check_activity,
        run_coverage_check_activity,
        run_flag_guard_check_activity,
        run_mutation_check_activity,
        run_protected_paths_check_activity,
        run_reviewhog_check_activity,
        teardown_gate_sandbox_activity,
    )


@dataclass
class GateRunInput:
    bet_id: str
    team_id: int
    bet_slug: str
    created_by_id: int | None
    gate_config: dict[str, Any]
    artifact: dict[str, Any]  # {repo_url, ref, base_ref, pr_url?}


@dataclass
class CheckResult:
    name: str
    check_type: str
    passed: bool
    required: bool
    details: str


async def _record(input: GateRunInput, kind: str, payload: dict[str, Any]) -> None:
    await workflow.execute_activity(
        record_bet_event_activity,
        RecordEventInput(bet_id=input.bet_id, team_id=input.team_id, kind=kind, payload=payload),
        start_to_close_timeout=RECORD_EVENT_TIMEOUT,
        retry_policy=RECORD_EVENT_RETRY_POLICY,
    )


async def _execute_check(
    input: GateRunInput,
    *,
    name: str,
    check_type: str,
    required: bool,
    activity_fn: Any,
    activity_input: Any,
    timeout: timedelta,
) -> CheckResult:
    await _record(input, "note", {"message": f"check '{name}' ({check_type}) starting"})
    try:
        outcome: CheckOutcome = await workflow.execute_activity(
            activity_fn,
            activity_input,
            start_to_close_timeout=timeout,
            retry_policy=CHECK_RETRY_POLICY,
        )
        result = CheckResult(name, check_type, outcome.passed, required, outcome.detail)
    except Exception as e:
        result = CheckResult(name, check_type, False, required, f"check crashed or timed out: {e}")
    verb = "passed" if result.passed else "failed"
    await _record(input, "note", {"message": f"check '{name}' ({check_type}) {verb}: {result.details[:200]}"})
    return result


def _cannot_run(
    name: str, check_type: str, required: bool, provision: ProvisionGateSandboxOutput | None
) -> CheckResult:
    reason = provision.checkout_error if provision is not None else "no artifact repo_url/ref provided"
    return CheckResult(name, check_type, False, required, f"cannot run: {reason}")


async def _run_declared_check(
    input: GateRunInput, check: dict[str, Any], provision: ProvisionGateSandboxOutput | None
) -> CheckResult:
    check_type = str(check["check_type"])
    name = str(check.get("name") or check_type)
    required = bool(check.get("required", True))
    params: dict[str, Any] = check.get("params") or {}

    if check_type == GateCheckType.REVIEWHOG:
        return await _execute_check(
            input,
            name=name,
            check_type=check_type,
            required=required,
            activity_fn=run_reviewhog_check_activity,
            activity_input=RunReviewhogCheckInput(
                team_id=input.team_id,
                created_by_id=input.created_by_id,
                pr_url=input.artifact.get("pr_url"),
                poll_interval_seconds=REVIEWHOG_POLL_INTERVAL_SECONDS,
                max_poll_attempts=REVIEWHOG_MAX_POLL_ATTEMPTS,
            ),
            timeout=REVIEWHOG_CHECK_TIMEOUT,
        )

    # Every other check type needs the artifact checked out and diffed.
    if provision is None or provision.checkout_error:
        return _cannot_run(name, check_type, required, provision)

    if check_type == GateCheckType.COMMAND:
        return await _execute_check(
            input,
            name=name,
            check_type=check_type,
            required=required,
            activity_fn=run_command_check_activity,
            activity_input=RunCommandCheckInput(sandbox_id=provision.sandbox_id, command=params["command"]),
            timeout=DEFAULT_CHECK_TIMEOUT,
        )

    if check_type == GateCheckType.COVERAGE:
        return await _execute_check(
            input,
            name=name,
            check_type=check_type,
            required=required,
            activity_fn=run_coverage_check_activity,
            activity_input=RunCoverageCheckInput(
                sandbox_id=provision.sandbox_id,
                command=params["command"],
                report_format=params["report_format"],
                report_path=params["report_path"],
                min_changed_line_pct=float(params["min_changed_line_pct"]),
                diff_text=provision.diff_text,
            ),
            timeout=COVERAGE_CHECK_TIMEOUT,
        )

    if check_type == GateCheckType.MUTATION:
        max_minutes = int(params.get("max_minutes") or 10)
        return await _execute_check(
            input,
            name=name,
            check_type=check_type,
            required=required,
            activity_fn=run_mutation_check_activity,
            activity_input=RunMutationCheckInput(
                sandbox_id=provision.sandbox_id,
                command_template=params.get("command") or "",
                changed_files=provision.changed_files,
                min_score_pct=float(params["min_score_pct"]),
                max_minutes=max_minutes,
            ),
            # A couple of minutes of slack over the sandbox-enforced time-box for the
            # activity's own bookkeeping (cat-ing the report, returning) — the sandbox
            # timeout, not this one, is what actually bounds the mutation run itself.
            timeout=timedelta(minutes=max_minutes + 2),
        )

    if check_type == GateCheckType.FLAG_GUARD:
        flag_key = params.get("flag_key") or f"bet-{input.bet_slug}"
        return await _execute_check(
            input,
            name=name,
            check_type=check_type,
            required=required,
            activity_fn=run_flag_guard_check_activity,
            activity_input=RunFlagGuardCheckInput(
                diff_text=provision.diff_text,
                changed_files=provision.changed_files,
                flag_key=flag_key,
                exempt_paths=list(params.get("exempt_paths") or []),
            ),
            timeout=DEFAULT_CHECK_TIMEOUT,
        )

    return CheckResult(name, check_type, False, required, f"unknown check_type '{check_type}'")


@workflow.defn(name="foundry-run-gate")
class FoundryGateWorkflow(PostHogWorkflow):
    inputs_cls = GateRunInput

    @workflow.run
    async def run(self, input: GateRunInput) -> dict[str, Any]:
        checks: list[dict[str, Any]] = list(input.gate_config.get("checks") or [])
        protected_paths: list[str] = list(input.gate_config.get("protected_paths") or [])
        artifact_config: dict[str, Any] = input.gate_config.get("artifact") or {}

        await _record(input, "note", {"message": "gauntlet: starting"})

        provision: ProvisionGateSandboxOutput | None = None
        if input.artifact.get("repo_url") and input.artifact.get("ref"):
            try:
                provision = await workflow.execute_activity(
                    provision_gate_sandbox_activity,
                    ProvisionGateSandboxInput(
                        bet_id=input.bet_id,
                        repo_url=input.artifact["repo_url"],
                        ref=input.artifact["ref"],
                        base_ref=input.artifact.get("base_ref") or "",
                        template=artifact_config.get("template") or "slim_base",
                    ),
                    start_to_close_timeout=PROVISION_TIMEOUT,
                    retry_policy=CHECK_RETRY_POLICY,
                )
            except Exception as e:
                provision = ProvisionGateSandboxOutput(sandbox_id="", checkout_error=str(e))

        results: list[CheckResult] = []
        try:
            if protected_paths:
                if provision is None or provision.checkout_error:
                    results.append(_cannot_run("protected_paths", PROTECTED_PATHS_CHECK_TYPE, True, provision))
                else:
                    results.append(
                        await _execute_check(
                            input,
                            name="protected_paths",
                            check_type=PROTECTED_PATHS_CHECK_TYPE,
                            required=True,
                            activity_fn=run_protected_paths_check_activity,
                            activity_input=RunProtectedPathsCheckInput(
                                changed_files=provision.changed_files, protected_paths=protected_paths
                            ),
                            timeout=DEFAULT_CHECK_TIMEOUT,
                        )
                    )

            for check in checks:
                results.append(await _run_declared_check(input, check, provision))
        finally:
            if provision is not None and provision.sandbox_id:
                try:
                    await workflow.execute_activity(
                        teardown_gate_sandbox_activity,
                        TeardownGateSandboxInput(sandbox_id=provision.sandbox_id),
                        start_to_close_timeout=TEARDOWN_TIMEOUT,
                        retry_policy=CHECK_RETRY_POLICY,
                    )
                except Exception:
                    pass

        checks_payload = [
            {"name": r.name, "type": r.check_type, "pass": r.passed, "required": r.required, "details": r.details}
            for r in results
        ]
        violations = [
            {"code": r.name, "message": r.details, "severity": "must_fix" if r.required else "advisory"}
            for r in results
            if not r.passed
        ]
        overall_pass = all(r.passed for r in results if r.required)
        await _record(input, "gate.result", {"pass": overall_pass, "checks": checks_payload, "violations": violations})
        return {"pass": overall_pass, "checks": checks_payload}
