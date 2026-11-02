import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.egress.limiter.policies import Priority
from posthog.models.repo_routing_rule import RepoRoutingRule

from products.tasks.backend.logic.repo_selection.agent import (
    RepoSelectionRejectedError,
    RepoSelectionUsageLimitError,
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
            priority=Priority.NORMAL,
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
        (
            "states_a_candidate_and_rejects_another",
            '{"repository": "Acme/A", "reason": "acme/b does not own this',
            ["acme/a", "acme/b"],
            "acme/a",
        ),
    ]
)
def test_salvage_reads_a_lone_named_candidate(_name, text, candidates, expected) -> None:
    assert _salvage_repo_selection(text, candidates).repository == expected


@parameterized.expand(
    [
        ("names_two_candidates", "Both acme/a and acme/b match the request.", ["acme/a", "acme/b"]),
        ("names_no_candidate", "None of the connected repositories own this.", ["acme/a", "acme/b"]),
        ("names_a_non_candidate_that_extends_one", "The subject is acme/api-client.", ["acme/api", "acme/web"]),
        (
            "states_no_repository_and_cites_one",
            '{"repository": null, "reason": "I checked acme/b and it does not own this',
            ["acme/a", "acme/b"],
        ),
        (
            "states_a_non_candidate_and_cites_one",
            '{"repository": "acme/c", "reason": "acme/b is close, but',
            ["acme/a", "acme/b"],
        ),
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
            priority=Priority.NORMAL,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
        )

    assert selected.repository == "acme/b"


def test_select_repository_reports_a_usage_limit_refusal() -> None:
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [{"full_name": "acme/a"}, {"full_name": "acme/b"}]

    async def start(**kwargs):
        # The runner swallows a raising fallback and raises its own parse error instead.
        with pytest.raises(ValueError):
            kwargs["fallback_from_text"]("API Error: 402 Your team has used its monthly PostHog AI credits.")
        raise ValueError("No JSON in initial turn")

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/a", "acme/b"}),
        patch(f"{_AGENT}._routing_rules_block", return_value=None),
        patch(f"{_AGENT}.MultiTurnSession.start", AsyncMock(side_effect=start)),
        pytest.raises(RepoSelectionUsageLimitError),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        async_to_sync(select_repository)(
            1,
            1,
            "which repo?",
            origin_product=Task.OriginProduct.SLACK,
            priority=Priority.NORMAL,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
        )


def test_source_repository_section_included_only_when_given() -> None:
    base = _build_repo_selection_prompt("ctx", ["acme/a", "acme/b"])
    assert "## Source repository" not in base

    with_source = _build_repo_selection_prompt(
        "ctx",
        ["acme/a", "acme/b"],
        routing_rules="1. Support app asks → `acme/b`",
        source_repository="acme/b",
    )
    assert "filed as an issue in `acme/b`" in with_source
    assert (
        with_source.index("`acme/b`")
        < with_source.index("## Source repository")
        < with_source.index("Team routing rules")
    )


@pytest.mark.parametrize(
    "source,expected_in_prompt,routing_rules,past_corrections",
    [
        ("Acme/B", "acme/b", "1. Client library bugs belong in `acme/a`", None),
        (" acme/b ", "acme/b", None, "A reviewer corrected a client library report from `acme/b` to `acme/a`."),
        ("acme/gone", None, None, None),
    ],
)
def test_source_repository_is_a_default_for_the_agent_not_an_answer(
    source: str, expected_in_prompt: str | None, routing_rules: str | None, past_corrections: str | None
) -> None:
    result = RepoSelectionResult(repository="acme/a", reason="the code lives in acme/a")
    session = MagicMock()
    session.end = AsyncMock()
    start = AsyncMock(return_value=(session, result))
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [
        {"full_name": "acme/a", "private": False},
        {"full_name": "acme/b", "private": False},
        {"full_name": "acme/gone", "private": False},
    ]

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/a", "acme/b"}),
        patch(f"{_AGENT}._routing_rules_block", return_value=routing_rules),
        patch(f"{_AGENT}.MultiTurnSession.start", start),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        selected = async_to_sync(select_repository)(
            1,
            1,
            "which repo?",
            origin_product=Task.OriginProduct.SLACK,
            priority=Priority.NORMAL,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
            source_repository=source,
            past_corrections=past_corrections,
        )

    assert selected.repository == "acme/a"
    assert start.call_args.kwargs["context"].github_read_access is True
    prompt = start.call_args.kwargs["prompt"]
    if expected_in_prompt:
        assert f"filed as an issue in `{expected_in_prompt}`" in prompt
    else:
        assert "## Source repository" not in prompt
    if routing_rules:
        assert routing_rules in prompt
    if past_corrections:
        assert past_corrections in prompt


@pytest.mark.parametrize(
    "source_metadata,target_private,expected",
    [
        ({"private": True}, False, None),
        ({"private": True}, None, None),
        ({"private": True}, True, "acme/b"),
        ({"private": False}, False, "acme/b"),
        ({"private": False}, True, "acme/b"),
        ({}, False, None),
        (None, False, None),
        ({"private": "false"}, False, None),
        (None, True, "acme/b"),
    ],
)
def test_source_visibility_constrains_single_eligible_repository(
    source_metadata: dict[str, bool | str] | None, target_private: bool | None, expected: str | None
) -> None:
    github = MagicMock()
    cached_repositories = [{"full_name": "acme/b", "private": target_private}]
    if source_metadata is not None:
        cached_repositories.append({"full_name": "acme/a", **source_metadata})
    github.list_all_cached_repositories.return_value = cached_repositories
    start = AsyncMock()

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/b"}),
        patch(f"{_AGENT}.MultiTurnSession.start", start),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        selected = async_to_sync(select_repository)(
            1,
            1,
            "Find the repository for this issue.",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            priority=Priority.NORMAL,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
            source_repository=" Acme/A ",
        )

    assert selected.repository == expected
    assert "acme/a" not in selected.reason
    start.assert_not_awaited()


@pytest.mark.parametrize("source_private", [None, True])
def test_nonpublic_source_can_keep_its_repository(source_private: bool | None) -> None:
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [
        {"full_name": "acme/a", "private": source_private},
        {"full_name": "acme/b", "private": False},
    ]

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/a", "acme/b"}),
    ):
        cache.return_value.sync_full_cache = AsyncMock()
        selected = async_to_sync(select_repository)(
            1,
            1,
            "Find the repository for this issue.",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            priority=Priority.NORMAL,
            github=github,
            candidate_repos=["acme/a", "acme/b"],
            source_repository="acme/a",
        )

    assert selected.repository == "acme/a"


@pytest.mark.parametrize("selected_repository", ["acme/b", "acme/c"])
def test_source_visibility_constrains_agent_selection(selected_repository: str) -> None:
    result = RepoSelectionResult(repository=selected_repository, reason="Matching code.")
    session = MagicMock()
    session.end = AsyncMock()
    start = AsyncMock(return_value=(session, result))
    github = MagicMock()
    github.list_all_cached_repositories.return_value = [
        {"full_name": "acme/a", "private": True},
        {"full_name": "acme/b", "private": True},
        {"full_name": "acme/c", "private": False},
        {"full_name": "acme/d", "private": True},
    ]

    with (
        patch(f"{_AGENT}.GitHubRepositoryFullCache") as cache,
        patch(f"{_AGENT}._list_eligible_full_names", return_value={"acme/b", "acme/c", "acme/d"}),
        patch(f"{_AGENT}._routing_rules_block", return_value=None),
        patch(f"{_AGENT}.MultiTurnSession.start", start),
    ):
        cache.return_value.sync_full_cache = AsyncMock()

        def select() -> RepoSelectionResult:
            return async_to_sync(select_repository)(
                1,
                1,
                "Find the repository for this issue.",
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                priority=Priority.NORMAL,
                github=github,
                candidate_repos=["acme/b", "acme/c", "acme/d"],
                source_repository="acme/a",
            )

        if selected_repository == "acme/c":
            with pytest.raises(RepoSelectionRejectedError):
                select()
        else:
            assert select().repository == "acme/b"

    prompt = start.call_args.kwargs["prompt"]
    assert "1. `acme/b` (private)" in prompt
    assert "2. `acme/d` (private)" in prompt
    assert "`acme/c`" not in prompt
    session.end.assert_awaited_once()
