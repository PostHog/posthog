from posthog.dataclasses import frozen

from products.reaper_hog.backend.logic.constants import MAX_OPEN_REAPER_PRS, MAX_VERIFICATIONS_PER_RUN

REAP_SCOPE_WORKFLOW = "reap-scope"


@frozen
class ReapScopeInputs:
    team_id: int
    user_id: int
    repository: str
    scope: str
    repo_path: str
    branch: str = "master"
    verify: bool = True
    harvest: bool = True
    max_clusters: int = MAX_VERIFICATIONS_PER_RUN
    max_prs: int = MAX_OPEN_REAPER_PRS

    @property
    def properties_to_log(self) -> dict[str, object]:
        return {"team_id": self.team_id, "repository": self.repository, "scope": self.scope}


@frozen
class ScanActivityResult:
    inventory_id: str
    head_sha: str
    hit_count: int
    cluster_count: int
    strong_count: int


def reap_workflow_id(*, team_id: int, repository: str, scope: str) -> str:
    return f"reap:{team_id}:{repository}:{scope}".lower()
