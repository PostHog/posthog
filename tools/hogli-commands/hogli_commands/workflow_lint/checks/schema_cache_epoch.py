"""Every ``SCHEMA_CACHE_EPOCH`` declaration must carry the same value.

ci-backend.yml saves the shared schema dump under
``posthog-schema-mig-<epoch>-<hash>`` on master pushes; ci-e2e-playwright.yml,
ci-dagster.yml, and ci-mcp.yml restore it by recomputing the same key from
their own copy of the epoch. Drift is silent in both directions: a consumer
left on an old epoch keeps restoring entries a bump was meant to abandon,
and a consumer bumped ahead of the saver never hits the cache again.
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

_ENV_KEY = "SCHEMA_CACHE_EPOCH"
_SAVER = "ci-backend.yml"


def _declarations(wf: Workflow) -> list[tuple[str | None, str | None, str]]:
    """Yield ``(job, step, value)`` for each env block declaring the epoch."""
    found: list[tuple[str | None, str | None, str]] = []
    env = wf.raw.get("env")
    if isinstance(env, dict) and _ENV_KEY in env:
        found.append((None, None, str(env[_ENV_KEY])))
    for job in wf.jobs:
        job_env = job.raw.get("env")
        if isinstance(job_env, dict) and _ENV_KEY in job_env:
            found.append((job.name, None, str(job_env[_ENV_KEY])))
        for step in job.steps:
            step_env = step.raw.get("env")
            if isinstance(step_env, dict) and _ENV_KEY in step_env:
                found.append((job.name, step.ref, str(step_env[_ENV_KEY])))
    return found


class SchemaCacheEpochCheck(WorkflowCheck):
    id = "WF007-schema-cache-epoch"
    label = "schema cache epoch sync"
    description = "every SCHEMA_CACHE_EPOCH declaration carries the same value"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Set SCHEMA_CACHE_EPOCH to the same value in every workflow that declares it. "
            "ci-backend.yml is the save side; a consumer left behind keeps restoring abandoned "
            "entries, and a consumer bumped ahead never hits the cache."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        decls: list[tuple[Workflow, str | None, str | None, str]] = []
        for wf in workflows:
            for job, step, value in _declarations(wf):
                decls.append((wf, job, step, value))
        if len({value for _, _, _, value in decls}) <= 1:
            return result

        saver_value = next((v for wf, _, _, v in decls if wf.path.name == _SAVER), None)
        # Without the saver in scope (e.g. a filtered --workflows-dir), any
        # deterministic reference value still surfaces the divergence.
        canonical = saver_value if saver_value is not None else sorted({v for _, _, _, v in decls})[0]
        reference = (
            f"'{canonical}' declared in {_SAVER} (the save side)" if saver_value is not None else f"'{canonical}'"
        )
        for wf, job, step, value in decls:
            if value == canonical:
                continue
            result.issues.append(
                Issue(
                    workflow=wf.path.name,
                    job=job,
                    step=step,
                    message=f"SCHEMA_CACHE_EPOCH is '{value}' but the shared schema cache key uses {reference}",
                    file=str(wf.path),
                )
            )
        return result
