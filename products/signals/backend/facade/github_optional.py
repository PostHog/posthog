from products.signals.backend.github_optional import ResearchAccessPolicy


def github_optional_pilot_enabled(team_id: int) -> bool:
    return ResearchAccessPolicy.enabled(team_id)


def pilot_repository_integration_id(team_id: int, repository: str) -> int | None:
    return ResearchAccessPolicy.repository_integration_id(team_id, repository)
