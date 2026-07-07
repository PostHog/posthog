"""Shared inputs + id helpers for the ReviewHog Temporal workflows.

Lives apart from `workflow.py` so the client (and any sync trigger) can build the workflow id and
input without importing the workflow code (which pulls in the heavy activity dependencies).
"""

from dataclasses import dataclass

# How a review run was triggered. Gates are trigger-aware: label → `review_labeled_prs`,
# inbox → `review_inbox_prs`, manual (CLI/eval) → ungated. Plain strings (not an Enum) so Temporal
# payloads stay forward/backward-compatible across deploys.
TRIGGER_LABEL = "label"
TRIGGER_INBOX = "inbox"
TRIGGER_MANUAL = "manual"


@dataclass
class ReviewPRWorkflowInputs:
    """Input for one single-turn `ReviewPRWorkflow`.

    The review target is either a PR (`pr_url` + `pr_number`, parsed from the URL by the trigger so
    the workflow stays free of the GitHub-URL parsing dependency) or a pushed branch with no PR yet
    (`head_branch`) — exactly one shape, validated in the client's `_build_inputs`. `(team_id,
    user_id)` are the explicit identity the sandbox tasks run under.

    `publish` is the per-run gate that replaces the old global `PUBLISH_REVIEW_ENABLED`: the cloud
    triggers set it true (post the review back to the PR); the eval CLI defaults it false. Defaults
    to false so any caller that forgets it cannot accidentally post to GitHub. A branch target with
    no resolvable PR stores the review instead — the target's shape decides, not a mode flag.

    `acting_user_id` overrides whose perspectives run: the label trigger leaves it None (the workflow
    resolves the PR author after fetch, skipping if not a PostHog user); the eval CLI and the inbox
    trigger set it explicitly (the inbox PR author is a bot, so it can't be resolved from GitHub).

    `trigger_source` / `signal_report_id` default so in-flight payloads serialized before these
    fields existed still deserialize.
    """

    team_id: int
    user_id: int
    pr_url: str | None = None
    owner: str = ""
    repo: str = ""
    pr_number: int | None = None
    publish: bool = False
    acting_user_id: int | None = None
    # Which trigger started this run (TRIGGER_LABEL / TRIGGER_INBOX / TRIGGER_MANUAL).
    trigger_source: str = TRIGGER_MANUAL
    # The signals report whose implementation this run reviews (inbox trigger only): stamped onto the
    # ReviewReport as provenance, and the target of the `code_review` artefact receipt.
    signal_report_id: str | None = None
    # Branch target (PR-less review): the pushed head branch to review when no PR URL is known.
    head_branch: str | None = None

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def properties_to_log(self) -> dict[str, object]:
        return {
            "team_id": self.team_id,
            "repository": self.repository,
            "pr_number": self.pr_number,
            "head_branch": self.head_branch,
            "trigger_source": self.trigger_source,
        }


def review_pr_workflow_id(*, team_id: int, owner: str, repo: str, pr_number: int) -> str:
    """Deterministic per-PR workflow id, so a re-trigger of the same PR review collapses by id.

    Lowercased (GitHub owner/repo are case-insensitive) so this id — and every sandbox workflow id
    prefixed with it — is searchable in the Temporal UI with one casing.
    """
    return f"review-pr:{team_id}:{owner}/{repo}:{pr_number}".lower()


def review_branch_workflow_id(*, team_id: int, owner: str, repo: str, head_branch: str) -> str:
    """Deterministic per-branch workflow id for PR-less targets, mirroring `review_pr_workflow_id`."""
    return f"review-branch:{team_id}:{owner}/{repo}:{head_branch}".lower()
