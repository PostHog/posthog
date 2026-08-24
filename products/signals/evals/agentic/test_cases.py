from products.signals.backend.scout_harness.lazy_seed import canonical_skill_names
from products.signals.evals.agentic.cases.implementation import CASES as IMPLEMENTATION_CASES
from products.signals.evals.agentic.cases.repo_selection import CASES as REPOSITORY_SELECTION_CASES
from products.signals.evals.agentic.cases.research import CASES as RESEARCH_CASES
from products.signals.evals.agentic.cases.scout import CASES as SCOUT_CASES
from products.signals.evals.agentic.repos import REGISTRY
from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo


def test_repository_selection_cases_use_portable_public_repositories() -> None:
    public_repositories = {repo.full_name for repo in REGISTRY.values()}
    for case in REPOSITORY_SELECTION_CASES:
        expected = case.expected.expected_repository
        repositories = (expected,) if isinstance(expected, str) else expected or ()
        assert set(repositories) <= public_repositories
        assert len(case.candidate_repos) == 2
        assert set(case.candidate_repos) <= public_repositories
        assert expected in case.candidate_repos
        assert case.judging_notes


def test_sandbox_workflow_cases_use_unauthenticated_public_repositories() -> None:
    repositories = [case.repo for case in RESEARCH_CASES] + [case.repo for case in IMPLEMENTATION_CASES]
    assert all(is_public_sandbox_repo(repository) for repository in repositories)


def test_research_cases_include_seeded_multisource_scenarios() -> None:
    seeded = [case for case in RESEARCH_CASES if case.seed]

    assert len(seeded) >= 3
    assert all(case.judging_notes for case in seeded)
    assert any(len(case.signals) > 1 for case in seeded)


def test_implementation_cases_include_multifile_product_flows() -> None:
    complex_case_ids = {
        "impl_hedgebox_download_flow",
        "impl_hedgebox_auth_return_path",
        "impl_hedgebox_bulk_delete",
        "impl_hedgebox_share_feedback",
    }
    cases = {case.case_id: case for case in IMPLEMENTATION_CASES}

    assert complex_case_ids <= cases.keys()
    assert all(cases[case_id].judging_notes for case_id in complex_case_ids)


def test_scout_cases_run_canonical_skills_against_seeded_data() -> None:
    canonical = canonical_skill_names()
    assert {case.skill_name for case in SCOUT_CASES} <= canonical
    assert all(case.seed for case in SCOUT_CASES)
    assert all(case.judging_notes for case in SCOUT_CASES)
    assert all(case.expected_query_tools for case in SCOUT_CASES)
    assert "signals-scout-web-vitals" in {case.skill_name for case in SCOUT_CASES}
