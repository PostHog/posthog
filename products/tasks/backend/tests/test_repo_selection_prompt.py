import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.repo_routing_rule import RepoRoutingRule

from products.tasks.backend.logic.repo_selection.agent import (
    _build_repo_selection_prompt,
    _routing_rules_block,
    _salvage_repo_selection,
    select_repository,
)
from products.tasks.backend.logic.repo_selection.types import RepoSelectionResult
from products.tasks.backend.models import Task

_AGENT = "products.tasks.backend.logic.repo_selection.agent"


def test_corrections_section_included_only_when_given() -> None:
    base = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"])
    assert "Past selection corrections" not in base

    with_corrections = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"], past_corrections="- 2026-01-01: entry")
    assert "- 2026-01-01: entry" in with_corrections
    # The section sits between the candidate list and the cache instructions, so the agent reads
    # the corrections together with the candidates they constrain.
    assert (
        with_corrections.index("`acme/b`")
        < with_corrections.index("Past selection corrections")
        < with_corrections.index("## The cache")
    )


def test_routing_rules_section_included_only_when_given() -> None:
    base = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"])
    assert "Team routing rules" not in base

    with_rules = _build_repo_selection_prompt(
        "ctx",
        ["acme/a", "acme/b"],
        past_corrections="- correction entry",
        routing_rules="1. Support app asks → `acme/b`",
    )
    assert "1. Support app asks → `acme/b`" in with_rules
    # Rules sit between the candidate list and the corrections, so the agent reads them together
    # with the candidates they constrain.
    assert (
        with_rules.index("`acme/b`")
        < with_rules.index("Team routing rules")
        < with_rules.index("Past selection corrections")
    )


@pytest.mark.django_db
def test_routing_rules_block_orders_filters_and_lowercases(team) -> None:
    RepoRoutingRule.objects.create(team=team, rule_text="Second\nrule", repository="Acme/B", priority=1)
    RepoRoutingRule.objects.create(team=team, rule_text="First rule", repository="acme/a", priority=0)
    RepoRoutingRule.objects.create(team=team, rule_text="Disconnected", repository="acme/gone", priority=2)

    block = _routing_rules_block(team.id, ["acme/a", "acme/b"])

    assert block == "1. First rule → `acme/a`\n2. Second rule → `acme/b`"


def test_prompt_labels_candidate_visibility() -> None:
    prompt = _build_repo_selection_prompt(
        "ctx", ["acme/a", "acme/b", "acme/c"], visibility={"acme/a": True, "acme/b": False}
    )

    assert "1. `acme/a` (private)" in prompt
    assert "2. `acme/b` (public)" in prompt
    assert "3. `acme/c` (visibility unknown)" in prompt
    assert "**Source privacy.**" in prompt
    assert "source privacy rule" in prompt


def test_prompt_text_caps_over_long_legacy_rules() -> None:
    rule = RepoRoutingRule(rule_text="term " * 100)
    assert len(rule.prompt_text) == RepoRoutingRule.MAX_RULE_TEXT_LENGTH


@pytest.mark.django_db
def test_routing_rules_block_empty_when_no_rules_match(team) -> None:
    assert _routing_rules_block(team.id, ["acme/a"]) is None

    RepoRoutingRule.objects.create(team=team, rule_text="Disconnected", repository="acme/gone", priority=0)
    assert _routing_rules_block(team.id, ["acme/a"]) is None


def test_select_repository_renders_team_rules_and_visibility_into_prompt() -> None:
    result = RepoSelectionResult(repository="acme/b", reason="rule match")
    session = MagicMock()
    session.end = AsyncMock()
    start = AsyncMock(return_value=(session, result))
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [
        {"full_name": "Acme/A", "private": True},
        {"full_name": "acme/b"},
    ]

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/a", "acme/b"}),
        patch(f"{_AGENT}._routing_rules_block", return_value="1. Support app asks → `acme/b`"),
        patch(f"{_AGENT}.MultiTurnSession.start", start),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        selected = async_to_sync(select_repository)(
            1,
            1,
            "which repo?",
            origin_product=Task.OriginProduct.SLACK,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
        )

    assert selected.repository == "acme/b"
    prompt = start.call_args.kwargs["prompt"]
    assert "Team routing rules" in prompt
    assert "1. Support app asks → `acme/b`" in prompt
    assert "1. `acme/a` (private)" in prompt
    assert "2. `acme/b` (visibility unknown)" in prompt


@parameterized.expand(
    [
        ("names_one_candidate", "I checked both trees. The subject is Acme/B.", ["acme/a", "acme/b"], "acme/b"),
        (
            "names_one_candidate_in_broken_json",
            '{"repository": "acme/b", "reason":',
            ["acme/a", "acme/b"],
            "acme/b",
        ),
        (
            "names_a_candidate_that_extends_another",
            "The subject is acme/api-client.",
            ["acme/api", "acme/api-client"],
            "acme/api-client",
        ),
        ("names_a_candidate_at_sentence_end", "The subject is acme/api.", ["acme/api", "acme/api-client"], "acme/api"),
    ]
)
def test_salvage_reads_a_lone_named_candidate(_name, text, candidates, expected) -> None:
    assert _salvage_repo_selection(text, candidates).repository == expected


@parameterized.expand(
    [
        ("names_two_candidates", "Both acme/a and acme/b match the request.", ["acme/a", "acme/b"]),
        ("names_no_candidate", "None of the connected repositories own this.", ["acme/a", "acme/b"]),
        ("names_a_non_candidate_that_extends_one", "The subject is acme/api-client.", ["acme/api", "acme/web"]),
    ]
)
def test_salvage_raises_when_the_reply_is_ambiguous(_name, text, candidates) -> None:
    # Answering "no repository" here would read as a decision the agent made, and guessing between
    # two would open work against the wrong repository. Raising keeps the caller's own fallback.
    with pytest.raises(ValueError):
        _salvage_repo_selection(text, candidates)


def test_select_repository_salvages_an_unreadable_end_turn() -> None:
    # An end turn that does not validate used to fail the whole selection, and the Slack caller
    # then dropped the user into a manual repository picker.
    session = MagicMock()
    session.end = AsyncMock()
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [{"full_name": "acme/a"}, {"full_name": "acme/b"}]

    async def start(**kwargs):
        return session, kwargs["fallback_from_text"]("After checking the trees, acme/b owns this.")

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/a", "acme/b"}),
        patch(f"{_AGENT}._routing_rules_block", return_value=None),
        patch(f"{_AGENT}.MultiTurnSession.start", AsyncMock(side_effect=start)),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        selected = async_to_sync(select_repository)(
            1,
            1,
            "which repo?",
            origin_product=Task.OriginProduct.SLACK,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
        )

    assert selected.repository == "acme/b"
