from products.signals.eval.agentic.cases.implementation import CASES as IMPLEMENTATION_CASES
from products.signals.eval.agentic.cases.repo_selection import CASES as REPOSITORY_SELECTION_CASES
from products.signals.eval.agentic.cases.research import CASES as RESEARCH_CASES
from products.signals.eval.agentic.repos import REGISTRY
from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo


def test_repository_selection_cases_use_portable_public_repositories() -> None:
    public_repositories = {repo.full_name for repo in REGISTRY.values()}
    for case in REPOSITORY_SELECTION_CASES:
        expected = case.expected.expected_repository
        repositories = (expected,) if isinstance(expected, str) else expected or ()
        assert set(repositories) <= public_repositories


def test_sandbox_workflow_cases_use_unauthenticated_public_repositories() -> None:
    repositories = [case.repo for case in RESEARCH_CASES] + [case.repo for case in IMPLEMENTATION_CASES]
    assert all(is_public_sandbox_repo(repository) for repository in repositories)
