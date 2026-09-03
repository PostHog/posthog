import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync

from posthog.models.repo_routing_rule import RepoRoutingRule

from products.tasks.backend.logic.repo_selection.agent import (
    _build_repo_selection_prompt,
    _routing_rules_block,
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


@pytest.mark.django_db
def test_routing_rules_block_empty_when_no_rules_match(team) -> None:
    assert _routing_rules_block(team.id, ["acme/a"]) is None

    RepoRoutingRule.objects.create(team=team, rule_text="Disconnected", repository="acme/gone", priority=0)
    assert _routing_rules_block(team.id, ["acme/a"]) is None


def test_select_repository_renders_team_rules_into_prompt() -> None:
    result = RepoSelectionResult(repository="acme/b", reason="rule match")
    session = MagicMock()
    session.end = AsyncMock()
    start = AsyncMock(return_value=(session, result))

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
            github=MagicMock(),
            candidate_repos=["acme/a", "acme/b"],
        )

    assert selected.repository == "acme/b"
    prompt = start.call_args.kwargs["prompt"]
    assert "Team routing rules" in prompt
    assert "1. Support app asks → `acme/b`" in prompt
