"""The required status checks on master still exist, and can still fail.

A required check gates every merge. It stops gating in two silent ways.

Renaming the job that produces it leaves the ruleset waiting for a check that
will never report, so every pull request waits until someone with a bypass
lands it by hand. `.depot/workflows/ci-backend.yml` already carries a comment
asking people to keep its gate names in sync with the ruleset, which is the
kind of note that gets missed.

Putting `continue-on-error` on that job makes GitHub report success whatever the
job does, so the required check is present, green and meaningless. Only the
job-level key is flagged: a step-level `continue-on-error` on the failure path is
a deliberate way to keep a gate's reporting steps from masking its verdict.

A check can also exist without a job: `.depot/workflows/ci-backend.yml` posts
`Backend CI on Depot / Test results` from a step, because Depot's own checks
carry no output. That counts as produced only when the name appears inside the
step that posts it through the checks API, not anywhere in any script, so
renaming or deleting the posting step still fails the rule while a leftover
`echo` of the name does not pass it.

The live list lives in the `master` ruleset, outside this repository, so it is
mirrored to `.github/required-status-checks.txt` and read from there: changing
the required set then shows up as a diff. Refresh it with
`bin/refresh-required-status-checks`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Job, Workflow, read_workflows

SNAPSHOT = Path(".github") / "required-status-checks.txt"
DEPOT_WORKFLOWS = Path(".depot") / "workflows"


def _display_name(job: Job) -> str:
    return str(job.raw.get("name") or job.name)


def _read_snapshot(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            names.append(entry)
    return names


def _is_continue_on_error(job: Job) -> bool:
    return bool(job.raw.get("continue-on-error"))


CHECK_POSTING = re.compile(r"check-runs|check_runs|checks\.create|createCheckRun")
# A check name is passed as a quoted literal or assigned to a name-ish variable.
QUOTED_LITERAL = re.compile(r"[\"'][^\"'\n]+[\"']")
ASSIGNED_NAME = re.compile(r"(?i)\bname=(\"[^\"\n]*\"|'[^'\n]*'|[^\s'\"]+)")


def _posted_names(page: list[Workflow]) -> set[str]:
    """The check names a posting step can actually post, as whole names.

    Two things matter for correctness here. Only steps that call the checks API
    count, so a comment or an `echo` elsewhere in the tree cannot claim a check.
    And the name has to be the *whole* value, not a substring: the block used to be
    joined and searched with `name in blob`, so a check renamed to
    `Test results v2` still satisfied `Test results` and the rename guard passed on
    a missing producer.

    Step `env:` values count because that is where the name is usually built
    (`GATE_CHECK: Some Posted Check`, then `-f name="$GATE_CHECK"`). `with:` inputs
    deliberately do not: a posting step's action inputs are telemetry about the
    check (`status-job:`), and counting them let a renamed job keep the rule green
    on an input that merely mentioned its old name.
    """
    names: set[str] = set()
    for wf in page:
        for job in wf.jobs:
            for step in job.steps:
                if not (step.run and CHECK_POSTING.search(step.run)):
                    continue
                env = step.raw.get("env")
                if isinstance(env, dict):
                    names.update(str(value).strip() for value in env.values())
                names.update(match.group(0)[1:-1] for match in QUOTED_LITERAL.finditer(step.run))
                names.update(match.group(1) for match in ASSIGNED_NAME.finditer(step.run))
    return {name for name in names if name}


def _contexts_named_in(posted: set[str], wanted: list[str]) -> set[str]:
    return {name for name in wanted if name in posted}


def _producers(root: Path, github_workflows: list[Workflow]) -> dict[str, tuple[str, Job]]:
    found: dict[str, tuple[str, Job]] = {}
    for wf in github_workflows:
        for job in wf.jobs:
            found.setdefault(_display_name(job), (wf.path.name, job))
    depot_dir = root / DEPOT_WORKFLOWS
    if depot_dir.is_dir():
        for wf in read_workflows(depot_dir):
            for job in wf.jobs:
                found.setdefault(f"{wf.name} / {_display_name(job)}", (str(DEPOT_WORKFLOWS / wf.path.name), job))
    return found


class RequiredStatusChecksCheck(WorkflowCheck):
    id = "WF017-required-status-checks"
    label = "required status checks"
    description = "every check required by the master ruleset is produced by a job that can fail"

    @property
    def fix_hint(self) -> str | None:
        return (
            "Update `.github/required-status-checks.txt` and the `master` ruleset together, or restore "
            "the job name it lists. Run `bin/refresh-required-status-checks` to re-read the ruleset."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        if not workflows:
            return result
        root = workflows[0].path.parents[2]
        snapshot = root / SNAPSHOT
        if not snapshot.is_file():
            return result
        required = _read_snapshot(snapshot)
        producers = _producers(root, workflows)

        pages = [workflows]
        if (root / DEPOT_WORKFLOWS).is_dir():
            pages.append(list(read_workflows(root / DEPOT_WORKFLOWS)))
        posted = _contexts_named_in(set().union(*(_posted_names(page) for page in pages)), required)

        for name in required:
            if name not in producers and name not in posted:
                result.issues.append(
                    Issue(
                        workflow=str(SNAPSHOT),
                        message=f"required check '{name}' is produced by no job in the repo",
                        file=str(snapshot),
                    )
                )

        for name in required:
            producer = producers.get(name)
            if producer is None:
                continue
            source, job = producer
            if _is_continue_on_error(job):
                result.issues.append(
                    Issue(
                        workflow=source,
                        job=job.name,
                        message=(
                            f"required check '{name}' cannot fail: the job sets continue-on-error, "
                            "so GitHub reports it green whatever the job does"
                        ),
                        file=str(root / (source if source.startswith(".depot") else f".github/workflows/{source}")),
                    )
                )
        return result


__all__ = ["RequiredStatusChecksCheck", "SNAPSHOT"]
