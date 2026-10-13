from products.tasks.backend.facade import repo_selection
from products.wizard.backend.facade.errors import MissingGitHubIntegrationError, RepositoryNotAccessibleError
from products.wizard.backend.logic.runs.validation import validate_git_repository_name
from products.wizard.backend.observability.tracing import wizard_span


@wizard_span("wizard.repository.authorize")
def authorize_git_repository_access(team_id: int, repository: str) -> int:
    validate_git_repository_name(repository)

    integration_id = repo_selection.resolve_team_github_integration_id(team_id)
    if integration_id is None:
        raise MissingGitHubIntegrationError

    if not repo_selection.repository_accessible_via_integration(team_id, integration_id, repository):
        raise RepositoryNotAccessibleError

    return integration_id
