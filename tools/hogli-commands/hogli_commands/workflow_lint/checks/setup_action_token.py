"""``actions/setup-{node,python,go}`` should not resolve versions on the default ``GITHUB_TOKEN``.

Each of these actions resolves its version from the ``actions/{node,python,go}-versions``
manifest via an authenticated GitHub API call, then downloads — once per job —
whenever the pinned version is not already in the runner tool-cache. That call
is authenticated with the step's ``token`` input, which defaults to the
workflow ``GITHUB_TOKEN``:

    token: ${{ github.server_url == 'https://github.com' && github.token || '' }}

So the manifest call lands on the per-repo ``GITHUB_TOKEN`` bucket (15,000
req/hr on GitHub Enterprise Cloud, shared by every job of every run). The
actions document the ``token`` input as the rate-limit lever; passing an
app-scoped token moves the call off the shared default bucket — the same
offload pattern already used for ``dorny/paths-filter``.

This rule is non-blocking while the existing call sites are migrated: it warns
so new workflows are guided and the backlog is visible, without failing every
PR until the migration completes. Flip ``blocking = True`` once the tree is clean.
"""

from __future__ import annotations

import re

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

SETUP_PREFIXES = (
    "actions/setup-node@",
    "actions/setup-python@",
    "actions/setup-go@",
)

# Token expression that resolves to nothing but the default GITHUB_TOKEN — i.e.
# no app-scoped fallback. The accepted pattern, `${{ steps.app-token.outputs.token
# || github.token }}`, contains `outputs.token` and so does NOT match here.
_DEFAULT_TOKEN_ONLY = re.compile(
    r"^\$\{\{\s*(github\.token|secrets\.GITHUB_TOKEN)\s*\}\}$",
)


class SetupActionTokenCheck(WorkflowCheck):
    id = "WF005-setup-action-token"
    label = "setup-* off default token"
    description = "actions/setup-{node,python,go} should pass an app-scoped token: (not the default GITHUB_TOKEN)"
    blocking = False  # rollout: warn while existing call sites are migrated

    @property
    def fix_hint(self) -> str | None:
        return (
            "Mint a setup-action GitHub token in the job and pass it to the setup step's "
            "`token:` input, e.g.\n"
            "    - uses: actions/create-github-app-token@<sha>\n"
            "      id: setup-gh-token\n"
            "      if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository\n"
            "      continue-on-error: true  # no-op to the default token until the secret exists\n"
            "      with:\n"
            "        client-id: ${{ secrets.GH_APP_POSTHOG_DEVEX_GENERAL_APP_ID }}\n"
            "        private-key: ${{ secrets.GH_APP_POSTHOG_DEVEX_GENERAL_PRIVATE_KEY }}\n"
            "    - uses: actions/setup-python@<sha>\n"
            "      with:\n"
            "        python-version-file: pyproject.toml\n"
            "        token: ${{ steps.setup-gh-token.outputs.token || github.token }}\n"
            "This moves the version-manifest API call off the shared per-repo GITHUB_TOKEN bucket."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        for wf in workflows:
            for job in wf.jobs:
                for step in job.steps:
                    if step.uses is None or not step.uses.startswith(SETUP_PREFIXES):
                        continue
                    token = (step.with_ or {}).get("token")
                    if isinstance(token, str) and not _DEFAULT_TOKEN_ONLY.match(token.strip()):
                        continue  # references an app-scoped (or other non-default) token
                    detail = (
                        "no `token:` input (defaults to GITHUB_TOKEN)"
                        if token is None
                        else "uses the default GITHUB_TOKEN"
                    )
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            job=job.name,
                            step=step.ref,
                            message=(
                                f"{step.uses.split('@')[0]} {detail} — its version-manifest API call "
                                "counts against the shared per-repo GITHUB_TOKEN bucket; pass an app-scoped token"
                            ),
                            file=str(wf.path),
                        )
                    )
        return result


__all__ = ["SetupActionTokenCheck"]
