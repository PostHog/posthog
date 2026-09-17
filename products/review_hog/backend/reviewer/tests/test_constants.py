import pytest

from posthog.temporal.oauth import has_write_scopes, resolve_scopes

import products.review_hog.backend.temporal.types as trigger_types
from products.review_hog.backend.reviewer.constants import (
    CHUNKING_MODEL,
    CHUNKING_REASONING_EFFORT,
    CHUNKING_RUNTIME_ADAPTER,
    DEDUP_MODEL,
    DEDUP_REASONING_EFFORT,
    DEDUP_RUNTIME_ADAPTER,
    DEFAULT_REVIEW_ARM,
    HUMAN_TRIGGER_SOURCES,
    RESOLUTION_MODEL,
    RESOLUTION_REASONING_EFFORT,
    RESOLUTION_RUNTIME_ADAPTER,
    REVIEW_ARMS_BY_TIER,
    REVIEW_MCP_SCOPES,
    REVIEW_MODEL,
    REVIEW_REASONING_EFFORT,
    REVIEW_RUNTIME_ADAPTER,
    VALIDATION_MODEL,
    VALIDATION_REASONING_EFFORT,
    VALIDATION_RUNTIME_ADAPTER,
    ReviewArm,
    ReviewTier,
    is_below_human_tier,
    resolve_review_arm,
    select_review_tier,
)
from products.review_hog.backend.temporal.types import TRIGGER_INBOX
from products.signals.backend.enums import ReportPriority
from products.tasks.backend.facade.run_config import (
    LLMProvider,
    ReasoningEffort,
    RuntimeAdapter,
    get_models_for_runtime_adapter,
    get_provider_for_runtime_adapter,
    get_reasoning_effort_error,
)


def test_review_runtime_is_a_registry_supported_combo() -> None:
    # The perspective review pins a hardcoded (adapter, model, effort). Bumping REVIEW_MODEL to a model
    # that doesn't support the pinned effort — or flipping the adapter — would make the agent server
    # reject/misroute the run, surfacing only at e2e. Lock the combo to the Tasks registry that gates it.
    assert get_reasoning_effort_error(REVIEW_RUNTIME_ADAPTER, REVIEW_MODEL, REVIEW_REASONING_EFFORT) is None
    assert get_provider_for_runtime_adapter(REVIEW_RUNTIME_ADAPTER) == LLMProvider.OPENAI


@pytest.mark.parametrize(
    "adapter,model,effort",
    [
        pytest.param(VALIDATION_RUNTIME_ADAPTER, VALIDATION_MODEL, VALIDATION_REASONING_EFFORT, id="validation"),
        pytest.param(RESOLUTION_RUNTIME_ADAPTER, RESOLUTION_MODEL, RESOLUTION_REASONING_EFFORT, id="resolution"),
    ],
)
def test_warm_session_runtime_is_a_registry_supported_combo_when_pinned(
    adapter: RuntimeAdapter | None, model: str | None, effort: ReasoningEffort | None
) -> None:
    # Same lock as the review combo, for the validation and resolution session pins. An unsupported
    # combo here hard-errors the agent server only AFTER the whole review stage has been paid for.
    # All-None (agent default) is a valid configuration and asserts nothing.
    if model is None:
        assert effort is None
        return
    assert get_reasoning_effort_error(adapter, model, effort) is None


@pytest.mark.parametrize(
    "adapter,model,effort",
    [
        pytest.param(CHUNKING_RUNTIME_ADAPTER, CHUNKING_MODEL, CHUNKING_REASONING_EFFORT, id="chunking"),
        pytest.param(DEDUP_RUNTIME_ADAPTER, DEDUP_MODEL, DEDUP_REASONING_EFFORT, id="dedup"),
    ],
)
def test_sandbox_fallback_runtime_is_a_registry_supported_combo(
    adapter: RuntimeAdapter, model: str, effort: ReasoningEffort
) -> None:
    # Same lock as the review combo, for the chunking/dedup sandbox-fallback pins. A bad combo only
    # surfaces over the one-shot gate — the rarely-exercised path — after the stage spend before it.
    assert get_reasoning_effort_error(adapter, model, effort) is None
    assert get_provider_for_runtime_adapter(adapter) == LLMProvider.ANTHROPIC


@pytest.mark.parametrize("arm", [pytest.param(arm, id=tier.value) for tier, arm in REVIEW_ARMS_BY_TIER.items()])
def test_tier_arm_is_a_registry_supported_combo(arm: ReviewArm) -> None:
    # Same lock as the pinned combos, per tier: a bad combo is persisted onto every report in the
    # tier and fails only mid-review in prod. A Codex arm without "full-access" stalls every
    # headless unit on MCP approval — the exact failure the bundle exists to prevent. Membership is
    # asserted because resolve_review_arm enforces it: an off-list arm would be persisted and then
    # silently resolved back to the default pins (xhigh) on every unit, so a typo'd cheap tier
    # costs money instead of failing.
    assert arm.model in get_models_for_runtime_adapter(arm.runtime_adapter)
    assert get_reasoning_effort_error(arm.runtime_adapter, arm.model, arm.reasoning_effort) is None
    if arm.runtime_adapter == RuntimeAdapter.CODEX:
        assert arm.initial_permission_mode == "full-access"


def test_every_tier_has_an_arm() -> None:
    # A tier the table forgets raises KeyError at report creation, after the PR was fetched.
    assert set(REVIEW_ARMS_BY_TIER) == set(ReviewTier)


@pytest.mark.parametrize(
    "agent_pr,priority,expected_tier,expected_effort",
    [
        pytest.param(False, None, ReviewTier.HUMAN, ReasoningEffort.XHIGH, id="human"),
        # A person's PR reviews at full strength whatever a linked report might say.
        pytest.param(False, ReportPriority.P4, ReviewTier.HUMAN, ReasoningEffort.XHIGH, id="human-ignores-priority"),
        pytest.param(True, ReportPriority.P0, ReviewTier.AGENT_P0_P1, ReasoningEffort.XHIGH, id="agent-p0"),
        pytest.param(True, ReportPriority.P1, ReviewTier.AGENT_P0_P1, ReasoningEffort.XHIGH, id="agent-p1"),
        pytest.param(True, ReportPriority.P2, ReviewTier.AGENT_P2, ReasoningEffort.MEDIUM, id="agent-p2"),
        pytest.param(True, ReportPriority.P3, ReviewTier.AGENT_P3_P4, ReasoningEffort.LOW, id="agent-p3"),
        pytest.param(True, ReportPriority.P4, ReviewTier.AGENT_P3_P4, ReasoningEffort.LOW, id="agent-p4"),
        # No readable judgment fails expensive, under its own label so it stays visible.
        pytest.param(True, None, ReviewTier.AGENT_UNPRIORITIZED, ReasoningEffort.XHIGH, id="agent-unprioritized"),
    ],
)
def test_select_review_tier_follows_the_tier_table(
    agent_pr: bool, priority: ReportPriority | None, expected_tier: ReviewTier, expected_effort: ReasoningEffort
) -> None:
    # The table IS the product decision (which PRs get the cheaper reviewer); a swapped bucket
    # silently changes review quality and spend for a whole class of PRs.
    tier = select_review_tier(agent_pr=agent_pr, signal_priority=priority)
    assert tier is expected_tier
    assert REVIEW_ARMS_BY_TIER[tier].reasoning_effort is expected_effort
    assert REVIEW_ARMS_BY_TIER[tier].model == REVIEW_MODEL


def test_every_report_priority_maps_to_a_tier() -> None:
    # A priority the table forgets raises KeyError at report creation, after the PR was fetched.
    for priority in ReportPriority:
        select_review_tier(agent_pr=True, signal_priority=priority)


@pytest.mark.parametrize(
    "tier,expected",
    [
        pytest.param(ReviewTier.AGENT_P3_P4, True, id="low-lifts"),
        pytest.param(ReviewTier.AGENT_P2, True, id="medium-lifts"),
        # Already on the human arm: the lift buys a person a stronger review, not a relabel.
        pytest.param(ReviewTier.AGENT_P0_P1, False, id="xhigh-keeps-its-label"),
        pytest.param(ReviewTier.AGENT_UNPRIORITIZED, False, id="unprioritized-keeps-its-label"),
        pytest.param(ReviewTier.HUMAN, False, id="human-is-the-ceiling"),
    ],
)
def test_only_tiers_cheaper_than_human_lift_on_a_human_trigger(tier: ReviewTier, expected: bool) -> None:
    assert is_below_human_tier(tier) is expected


def test_human_triggers_cover_every_trigger_but_the_inbox() -> None:
    # The set is spelled out in constants.py (persistence cannot import the temporal package). A
    # trigger added to types.py but not here would leave a person's ask on a cheap tier, so the
    # expected set is derived from the module rather than spelled out a second time.
    every_trigger = {value for name, value in vars(trigger_types).items() if name.startswith("TRIGGER_")}
    assert HUMAN_TRIGGER_SOURCES == every_trigger - {TRIGGER_INBOX}


# A registry-valid arm that differs from the default pins on every field, so honored-verbatim
# assertions cannot pass by falling back to the default. This is also the live prod scenario:
# reports that drew the Claude arm while it was in the experiment keep it for life.
_SONNET_ARM = ReviewArm(
    runtime_adapter=RuntimeAdapter.CLAUDE,
    model="claude-sonnet-5",
    reasoning_effort=ReasoningEffort.XHIGH,
    initial_permission_mode=None,
)


@pytest.mark.parametrize(
    "persisted,expected",
    [
        # Pre-experiment rows carry NULLs and must run the default pins.
        pytest.param((None, None, None, None), DEFAULT_REVIEW_ARM, id="null-bundle"),
        # A persisted assignment that differs from the default pins is honored verbatim.
        pytest.param(("claude", "claude-sonnet-5", "xhigh", None), _SONNET_ARM, id="persisted-claude-arm"),
        # A model that outlived its registration must degrade to the default reviewer, not send an
        # unroutable pin into a paid sandbox turn. Pinned at "high" deliberately: the Codex effort
        # registry accepts any unknown model at <=high, so only the membership check catches this.
        pytest.param(("codex", "gpt-9-vanished", "high", "full-access"), DEFAULT_REVIEW_ARM, id="stale-model"),
        pytest.param(("warp", "gpt-5.6-sol", "xhigh", None), DEFAULT_REVIEW_ARM, id="unknown-adapter"),
        # A Codex assignment without "full-access" stalls every headless unit on MCP approval, so it
        # must fall back rather than reach a sandbox turn.
        pytest.param(("codex", "gpt-5.6-sol", "xhigh", None), DEFAULT_REVIEW_ARM, id="codex-without-full-access"),
    ],
)
def test_resolve_review_arm_honors_valid_assignments_and_falls_back(
    persisted: tuple[str | None, str | None, str | None, str | None], expected: ReviewArm
) -> None:
    assert resolve_review_arm(*persisted) == expected


def test_review_mcp_scopes_open_a_session_and_stay_read_only() -> None:
    # The MCP server resolves the calling user when a session opens, so a token without `user:read`
    # is refused outright and the agent runs without its skill. Lock both halves of the pin: the
    # handshake scope is present, and the token still carries no user-facing write scope.
    resolved = resolve_scopes(REVIEW_MCP_SCOPES)
    assert "user:read" in resolved
    assert "llm_skill:read" in resolved
    assert not has_write_scopes(REVIEW_MCP_SCOPES)
