import re

import pytest

from products.tasks.evals.repo_selection.fixtures import (
    METRICS_DASHBOARD_RULE,
    REPOSITORIES,
    REPOSITORY_NAMES,
    ROUTING_CASES,
    SELECTOR_CASES,
    SUPPORT_DESK_RULE,
    SelectorExpectation,
)
from products.tasks.evals.repo_selection.scorers import judge_selection


@pytest.mark.parametrize("case", SELECTOR_CASES, ids=lambda case: case.scenario.name)
def test_selector_input_does_not_name_the_expected_repository(case):
    visible = case.scenario.context_block.lower()
    for repository in case.expected.accepted:
        assert repository.lower() not in visible
        assert not re.search(rf"\b{re.escape(repository.split('/', 1)[1])}\b", visible)


@pytest.mark.parametrize(
    "rule,topic_words",
    [(SUPPORT_DESK_RULE, ("support", "desk")), (METRICS_DASHBOARD_RULE, ("metric", "dashboard"))],
)
def test_routing_rule_is_the_only_link_to_its_repository(rule, topic_words):
    repo = next(repo for repo in REPOSITORIES if repo.full_name == rule.repository)
    cache_text = " ".join((repo.description, repo.readme, *repo.topics, *repo.tree_paths)).lower()
    assert not [word for word in topic_words if word in cache_text]


def test_cases_cover_the_preserved_scenarios_once():
    routing_names = [case.scenario.name for case in ROUTING_CASES]
    selector_names = [case.scenario.name for case in SELECTOR_CASES]
    assert len(routing_names) == len(set(routing_names)) == 17
    assert len(selector_names) == len(set(selector_names))
    assert all(
        case.expected.selector or case.expected.repository or case.expected.stage == "classifier"
        for case in ROUTING_CASES
    )
    assert {repo for case in SELECTOR_CASES for repo in case.expected.accepted} <= set(REPOSITORY_NAMES)


def test_expectation_names_a_repository_or_an_abstention():
    with pytest.raises(ValueError):
        SelectorExpectation()
    with pytest.raises(ValueError):
        SelectorExpectation(accepted=("fernhill/storefront",), abstain=True)
    with pytest.raises(ValueError):
        SelectorExpectation(accepted=("fernhill/not-in-catalog",))


ACCEPTED = {"accepted": ["fernhill/fernhill-ios", "fernhill/fernhill-android"], "abstain": False}
ABSTAIN = {"accepted": [], "abstain": True}


@pytest.mark.parametrize(
    "output,spec,expected",
    [
        ({"outcome": "found", "selected_repository": "Fernhill/Fernhill-Android"}, ACCEPTED, 1.0),
        ({"outcome": "found", "selected_repository": "fernhill/storefront"}, ACCEPTED, 0.0),
        ({"outcome": "no_match", "selected_repository": None}, ACCEPTED, 0.0),
        ({"outcome": "no_match", "selected_repository": None}, ABSTAIN, 1.0),
        ({"outcome": "found", "selected_repository": "fernhill/storefront"}, ABSTAIN, 0.0),
        ({"outcome": "rejected", "selected_repository": "fernhill/fernhill-ios-v2"}, ACCEPTED, 0.0),
        ({"outcome": "timeout"}, ABSTAIN, 0.0),
        ({"outcome": "error"}, ACCEPTED, 0.0),
        ({"exit_code": 1, "stderr": "case timeout after 600s"}, ABSTAIN, 0.0),
        (None, ABSTAIN, 0.0),
    ],
)
def test_judge_selection(output, spec, expected):
    assert judge_selection(output, spec)[0] == expected
