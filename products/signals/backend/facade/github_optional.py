from products.signals.backend.github_optional import ResearchAccessPolicy
from products.signals.backend.models import SignalReportArtefact
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult


def github_optional_pilot_enabled(team_id: int) -> bool:
    return ResearchAccessPolicy.enabled(team_id)


def pilot_repository_integration_id(team_id: int, repository: str) -> int | None:
    return ResearchAccessPolicy.repository_integration_id(team_id, repository)


def repository_confirmation_matches(
    team_id: int, report_id: str, confirmed_repository: str | None, implementation_repository: str | None
) -> bool:
    row = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="repo_selection")
        .order_by("-created_at", "-id")
        .first()
    )
    selection = RepoSelectionResult.model_validate_json(row.content) if row else None
    if not confirmed_repository and not (selection and selection.requires_confirmation):
        return True
    target = (selection.repository or "").casefold() if selection else ""
    return bool(
        target
        and (confirmed_repository or "").casefold() == target
        and (implementation_repository or "").casefold() == target
    )
