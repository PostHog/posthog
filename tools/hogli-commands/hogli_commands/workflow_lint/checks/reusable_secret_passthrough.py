"""A reusable workflow's secret reads must be declared and passed by every caller.

Secrets do not flow into a ``workflow_call`` workflow on their own. A name the
callee reads must be declared under ``on.workflow_call.secrets`` and then
passed by each caller, or inherited wholesale with ``secrets: inherit``.
Miss either half and the reference interpolates to an empty string.

Nothing fails loudly when that happens. ``ci-turbo.yml`` reads
``secrets.GH_APP_POSTHOG_SETUP_ACTIONS_PRIVATE_KEY`` while declaring no
secrets at all, so its App token step fails under ``continue-on-error`` and
the install falls back to ``github.token`` — losing the dedicated rate-limit
bucket the App exists to provide, with a green check either way.

Two rules, because the halves fail independently:

- an undeclared read can never receive a value, whoever calls it;
- a read declared ``required: true`` still arrives empty from a caller that
  omits it.

The second rule follows the declaration rather than second-guessing it.
``required: false`` is the callee saying it tolerates absence, and callers rely
on that: ``rust-smoke-test-build.yml`` deliberately withholds the symbol upload
key so a smoke-test build does not publish symbols. Mark a secret
``required: true`` when every caller must supply it.

A caller that passes a *differently named* secret through to the callee's input
satisfies the second rule: ``rust-docker-build.yml`` deliberately feeds
``POSTHOG_UPLOAD_SYMBOLS_CLI_API_KEY`` from the sourcemap upload key, and the
mapping is what matters, not the name matching.
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

LOCAL_CALL_PREFIX = "./.github/workflows/"
INHERIT = "inherit"

IMPLICIT_SECRETS = frozenset({"GITHUB_TOKEN"})

_SECRET_REF = re.compile(r"secrets\.([A-Za-z0-9_]+)")


def _call_block(wf: Workflow) -> dict | None:
    on = wf.on
    if not isinstance(on, dict):
        return None
    call = on.get("workflow_call")
    if call is None and "workflow_call" in on:
        # `workflow_call:` with an empty body parses to None but is still callable.
        return {}
    return call if isinstance(call, dict) else None


def _declared(call: dict) -> set[str]:
    secrets = call.get("secrets")
    return set(secrets.keys()) if isinstance(secrets, dict) else set()


def _required(call: dict) -> set[str]:
    """Declared names whose callers must supply a value."""
    secrets = call.get("secrets")
    if not isinstance(secrets, dict):
        return set()
    return {name for name, body in secrets.items() if isinstance(body, dict) and body.get("required") is True}


def _reads(wf: Workflow) -> set[str]:
    text = wf.path.read_text(encoding="utf-8")
    return set(_SECRET_REF.findall(text)) - IMPLICIT_SECRETS


def _callee_name(uses: str) -> str | None:
    if not uses.startswith(LOCAL_CALL_PREFIX):
        return None
    return uses[len(LOCAL_CALL_PREFIX) :].partition("@")[0]


class ReusableSecretPassthroughCheck(WorkflowCheck):
    id = "WF011-reusable-secret-passthrough"
    label = "reusable secret pass-through"
    description = "reusable workflows declare the secrets they read, and callers pass them"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Declare the secret under `on.workflow_call.secrets` in the called workflow, "
            "then pass it from every caller's `secrets:` block (or use `secrets: inherit`)."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()

        callable_workflows: dict[str, tuple[Workflow, set[str], set[str]]] = {}
        for wf in workflows:
            call = _call_block(wf)
            if call is None:
                continue
            declared = _declared(call)
            reads = _reads(wf) - declared
            callable_workflows[wf.path.name] = (wf, _required(call), reads)

        for name, (wf, _required_names, undeclared_reads) in sorted(callable_workflows.items()):
            for secret in sorted(undeclared_reads):
                result.issues.append(
                    Issue(
                        workflow=name,
                        message=(
                            f"reads secrets.{secret} but does not declare it under "
                            "on.workflow_call.secrets, so it is always empty"
                        ),
                        file=str(wf.path),
                    )
                )

        for caller in workflows:
            for job in caller.jobs:
                if job.uses is None:
                    continue
                callee_name = _callee_name(job.uses)
                if callee_name is None or callee_name not in callable_workflows:
                    continue

                callee_wf, required_names, _ = callable_workflows[callee_name]
                needed = required_names & _reads(callee_wf)
                if not needed:
                    continue

                passed_block = job.raw.get("secrets")
                if passed_block == INHERIT:
                    continue
                passed = set(passed_block.keys()) if isinstance(passed_block, dict) else set()

                for secret in sorted(needed - passed):
                    result.issues.append(
                        Issue(
                            workflow=caller.path.name,
                            job=job.name,
                            message=(f"calls {callee_name}, which reads secrets.{secret}, but does not pass it"),
                            file=str(caller.path),
                        )
                    )

        return result
