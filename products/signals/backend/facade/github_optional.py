from products.signals.backend.github_optional import ResearchAccessPolicy


def github_optional_pilot_enabled(team_id: int) -> bool:
    return ResearchAccessPolicy.enabled(team_id)


def pilot_repository_integration_id(team_id: int, repository: str) -> int | None:
    return ResearchAccessPolicy.repository_integration_id(team_id, repository)


def require_repository_confirmation(
    team_id: int, report_id: str, confirmed_repository: str | None, implementation_repository: str | None
) -> None:
    from rest_framework.exceptions import ValidationError

    from products.signals.backend.models import SignalReportArtefact
    from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult

    row = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, type="repo_selection")
        .order_by("-created_at", "-id")
        .first()
    )
    selection = RepoSelectionResult.model_validate_json(row.content) if row else None
    if not confirmed_repository and not (selection and selection.requires_confirmation):
        return
    target = (selection.repository or "").casefold() if selection else ""
    if (
        not target
        or (confirmed_repository or "").casefold() != target
        or (implementation_repository or "").casefold() != target
    ):
        raise ValidationError({"repository": "Confirm the recommended repository before starting implementation."})
