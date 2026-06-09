"""Milestone 2 — dispatch cited findings to PostHog Code (mechanical) or humans (structural).

Routing (the trust-critical rule):
- MECHANICAL + cited + confident  → dispatch a coding task to PostHog Code, which reproduces the
  proven version-bump → data-migration → tests chain and opens **draft PRs** only.
- STRUCTURAL / UNCERTAIN / low-confidence → file a GitHub issue for humans. **Never auto-PR.**

The routing and the task/issue text are pure functions (unit-tested). Only ``dispatch_findings``
has side effects (creates Tasks / GitHub issues), and it honours ``dry_run`` so the plan can be
previewed without dispatching anything. Nothing here ever merges, deploys, or runs a migration —
PostHog Code opens drafts; humans take it from there.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from products.signals.backend.api_deprecation.schema import (
    MECHANICAL_CONFIDENCE_THRESHOLD,
    Classification,
    ResearchedDeprecation,
)


class RouteAction(str, Enum):
    DISPATCH_PR = "dispatch_pr"  # mechanical → PostHog Code draft PR
    FILE_ISSUE = "file_issue"  # structural/uncertain → human issue
    SKIP = "skip"  # not deprecated


def route_finding(
    finding: ResearchedDeprecation, *, confidence_threshold: float = MECHANICAL_CONFIDENCE_THRESHOLD
) -> RouteAction:
    """Decide what to do with a finding. Only mechanical+cited+confident findings are auto-remediated."""
    if not finding.is_deprecated:
        return RouteAction.SKIP
    is_mechanical = (
        finding.classification == Classification.MECHANICAL
        and finding.confidence >= confidence_threshold
        and bool(finding.evidence_url.strip())
    )
    return RouteAction.DISPATCH_PR if is_mechanical else RouteAction.FILE_ISSUE


def replace_key_for(finding: ResearchedDeprecation) -> str:
    """The `update_hog_function_code --replace-key` to add for the data migration (mirrors existing keys)."""
    return f"{finding.pin.vendor}-api-version-update"


def build_task_prompt(finding: ResearchedDeprecation) -> str:
    """The orchestration prompt for PostHog Code — reproduces the proven 3-PR remediation chain.

    Pure and self-contained: it carries the exact pin, the cited evidence, and the verify-before-open
    steps so PostHog Code can re-confirm and stop (comment, not PR) if it finds a contract change.
    """
    pin = finding.pin
    migration_step = (
        f"""3. **Data migration** (this pin is baked into existing rows). Existing destinations have
   `{pin.pinned_version}` compiled into their stored `HogFunction.hog`/`bytecode`, so the template
   bump alone won't fix them. Add a `{replace_key_for(finding)}` entry to
   `posthog/management/commands/update_hog_function_code.py` rewriting the `{pin.pinned_version}` →
   `{finding.recommended_version}` string, mirroring the existing `meta-ads-api-version-update`
   precedent (the command already skips uncompilable rows). Add fixtures + a test in
   `posthog/management/commands/test/test_update_hog_function_code.py`."""
        if pin.persisted_per_row
        else "3. **No data migration needed** — this pin is read at runtime, not persisted per row."
    )
    return f"""Bump a deprecated external-API version pin and open draft PR(s). This was classified MECHANICAL
(a version-number bump with no change to the fields we use), but you must re-verify before opening.

## The pin
- {pin.product} — host `{pin.host}`
- Pinned `{pin.pinned_version}` → recommend `{finding.recommended_version}`
- Code site: `{pin.file}:{pin.line}`{f" (endpoint {pin.endpoint})" if pin.endpoint else ""}
- Cited evidence: {finding.evidence_url}
  > {finding.evidence_quote}

## Steps
1. **Source bump.** Change `{pin.pinned_version}` → `{finding.recommended_version}` at the code site, and
   grep for any runtime version constant for the same vendor (e.g. an `api_version` field) and bump it
   too — mirroring PR #61214 which bumped both the template and the integration constant.
2. **Breaking-change review (gate).** From `{pin.pinned_version}` to `{finding.recommended_version}`, walk the
   vendor changelog against EVERY field/endpoint/auth used at `{pin.file}`. If any of those changed,
   this is NOT mechanical — **do not open a PR; post a comment** describing the structural change and stop.
{migration_step}
4. **Verify before opening.** Run the affected test suite, and if you added a migration, run
   `./manage.py update_hog_function_code --replace-key {replace_key_for(finding)} --dry-run` against
   local fixtures. Only proceed if both pass.
5. **Open DRAFT PR(s) only.** Never merge, never run the migration outside `--dry-run`.

Proven shape: PRs #61214 (source bump + breaking-change review), #61413 (data migration), #62106 (skip-uncompilable resilience)."""


def build_issue(finding: ResearchedDeprecation) -> tuple[str, str, list[str]]:
    """Title/body/labels for the human-review GitHub issue (structural/uncertain findings)."""
    pin = finding.pin
    title = f"[api-deprecation] {pin.product} {pin.pinned_version}: needs human review ({finding.classification.value})"
    body = f"""An automated deprecation check flagged a pinned external-API version that should **not** be
auto-remediated — it needs a human.

- **Pin:** `{pin.host}` `{pin.pinned_version}` at `{pin.file}:{pin.line}`
- **Recommended:** `{finding.recommended_version or "see changelog"}`
- **Classification:** `{finding.classification.value}` (confidence {finding.confidence})
- **Affected fields/endpoints:** {", ".join(finding.affected_fields) or "see changelog"}
- **Cutoff:** {finding.cutoff_date.isoformat() if finding.cutoff_date else "no published date"}
- **Evidence:** {finding.evidence_url}
  > {finding.evidence_quote}

This was classified structural/uncertain (an endpoint/auth/payload change, or low confidence), so the
loop did not open a PR. A human should scope the migration.

_Filed by the API deprecation watch loop. {finding.reasoning}_"""
    return title, body, ["api-deprecation", "needs-human"]


# ----------------------------------------------------------------------
# Side effects (Tasks / GitHub issues). Not exercised without the stack.
# ----------------------------------------------------------------------


_GITHUB_API_VERSION = "2022-11-28"


@dataclass
class DispatchOutcome:
    dedup_key: str
    action: RouteAction
    task_id: str | None = None
    issue_url: str | None = None
    dry_run: bool = False


def _file_github_issue(team, repository: str, finding: ResearchedDeprecation) -> str | None:
    """Open a GitHub issue via the team's GitHub integration. Returns the issue URL, or None if no integration."""
    import requests  # noqa: PLC0415

    from posthog.models.integration import GitHubIntegration, Integration  # noqa: PLC0415

    integration = Integration.objects.filter(team=team, kind="github").first()
    if integration is None:
        return None
    title, body, labels = build_issue(finding)
    access_token = GitHubIntegration(integration).get_access_token()
    resp = requests.post(
        f"https://api.github.com/repos/{repository}/issues",
        json={"title": title, "body": body, "labels": labels},
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("html_url")


def dispatch_findings(
    *,
    team_id: int,
    report_id: str,
    findings: list[ResearchedDeprecation],
    repository: str = "posthog/posthog",
    dry_run: bool = False,
) -> list[DispatchOutcome]:
    """Route each finding and (unless dry_run) create the Task / issue. Returns the plan/outcomes."""
    # Imported here so the pure helpers + tests don't pull Django.
    from posthog.models import Team  # noqa: PLC0415

    from products.signals.backend.models import SignalReportTask  # noqa: PLC0415
    from products.signals.backend.temporal.agentic import resolve_user_id_for_team  # noqa: PLC0415
    from products.tasks.backend.models import Task  # noqa: PLC0415

    team = Team.objects.select_related("organization").get(id=team_id)
    outcomes: list[DispatchOutcome] = []

    for finding in findings:
        action = route_finding(finding)
        if action == RouteAction.SKIP or dry_run:
            outcomes.append(DispatchOutcome(finding.dedup_key, action, dry_run=dry_run))
            continue

        if action == RouteAction.DISPATCH_PR:
            task = Task.create_and_run(
                team=team,
                title=f"Bump {finding.pin.product} {finding.pin.pinned_version} → {finding.recommended_version}",
                description=build_task_prompt(finding),
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                user_id=resolve_user_id_for_team(team_id),
                repository=repository,
                signal_report_id=report_id,
                posthog_mcp_scopes="read_only",
                interaction_origin="signal_report",  # → PostHog Code auto-pushes and opens a DRAFT PR
            )
            SignalReportTask.objects.create(
                team_id=team_id,
                report_id=report_id,
                task=task,
                relationship=SignalReportTask.Relationship.IMPLEMENTATION,
            )
            outcomes.append(DispatchOutcome(finding.dedup_key, action, task_id=str(task.id)))
        else:  # FILE_ISSUE
            outcomes.append(
                DispatchOutcome(finding.dedup_key, action, issue_url=_file_github_issue(team, repository, finding))
            )

    return outcomes
