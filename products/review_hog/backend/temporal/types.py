"""Shared inputs + id helpers for the ReviewHog Temporal workflows.

Lives apart from `workflow.py` so the client (and any sync trigger) can build the workflow id and
input without importing the workflow code (which pulls in the heavy activity dependencies).
"""

from dataclasses import dataclass


@dataclass
class ReviewPRWorkflowInputs:
    """Input for one single-turn `ReviewPRWorkflow`.

    `owner` / `repo` / `pr_number` are parsed from `pr_url` by the trigger so the workflow itself
    stays free of the GitHub-URL parsing dependency. `(team_id, user_id)` are the explicit identity
    the sandbox tasks run under (the PR's author and their team, when triggered in the cloud).

    `publish` is the per-run gate that replaces the old global `PUBLISH_REVIEW_ENABLED`: the cloud
    label trigger sets it true (post the review back to the PR); the eval CLI defaults it false.
    Defaults to false so any caller that forgets it cannot accidentally post to GitHub.

    `acting_user_id` overrides whose enabled perspectives drive the review. The cloud trigger leaves
    it None (the workflow resolves the PR author after fetch, and skips the review if the author isn't
    a PostHog org user); the eval CLI sets it explicitly to test a known user's perspectives.
    """

    team_id: int
    user_id: int
    pr_url: str
    owner: str
    repo: str
    pr_number: int
    publish: bool = False
    acting_user_id: int | None = None

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def properties_to_log(self) -> dict[str, object]:
        return {
            "team_id": self.team_id,
            "repository": self.repository,
            "pr_number": self.pr_number,
        }


def review_pr_workflow_id(*, team_id: int, owner: str, repo: str, pr_number: int) -> str:
    """Deterministic per-PR workflow id, so a re-trigger of the same PR review collapses by id."""
    return f"review-pr:{team_id}:{owner}/{repo}:{pr_number}"
