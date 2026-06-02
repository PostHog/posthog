"""``astral-sh/setup-uv`` must pin an explicit ``version:``.

Without a pinned ``version``, setup-uv queries the GitHub API for the latest
release on every job. Across the hundreds of setup jobs this repo runs per hour
that drains the per-repo ``GITHUB_TOKEN`` rate-limit bucket (15,000 req/hr on
GitHub Enterprise Cloud, shared by every job of every run). Pinning a version
makes it a tool-cache hit with no API call — the same reasoning already noted
inline in ``ci-lint-workflows.yml``. This rule keeps that from regressing.
"""

from __future__ import annotations

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

SETUP_UV_PREFIX = "astral-sh/setup-uv@"


class SetupUvPinnedCheck(WorkflowCheck):
    id = "WF005-setup-uv-pinned"
    label = "setup-uv version pinned"
    description = "astral-sh/setup-uv must pin an explicit version: (unpinned calls the GitHub API every job)"

    @property
    def fix_hint(self) -> str | None:
        return "Add a pinned `version:` to the setup-uv step's `with:` block, e.g. `version: '0.11.14'`."

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                for step in job.steps:
                    if step.uses is None or not step.uses.startswith(SETUP_UV_PREFIX):
                        continue
                    version = (step.with_ or {}).get("version")
                    if isinstance(version, str) and version.strip():
                        continue
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            step=step.ref,
                            message=(
                                "astral-sh/setup-uv has no pinned `version:` — it queries the GitHub API "
                                "for the latest release on every job, draining the per-repo GITHUB_TOKEN bucket"
                            ),
                            file=str(wf.path),
                        )
                    )
        return result


__all__ = ["SetupUvPinnedCheck"]
