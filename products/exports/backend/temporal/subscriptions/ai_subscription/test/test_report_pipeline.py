import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError, ResolutionError

from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    _MAX_CONCURRENT_STEPS,
    QUERY_FAILED_PREFIX,
    AiReportStageError,
    QueryStepDiagnostic,
    _all_queries_failed_notice,
    _arequest_hogql_fix,
    _run_steps,
    _safe_error_message,
    generate_ai_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.schemas import (
    EnrichedPromptSpec,
    HogQLFix,
    QueryPlan,
    QueryPlanStep,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PromptRejectedError,
    ReportWindow,
)

_RP = "products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline"
# slo_operation emits through posthoganalytics.capture; patch that boundary to inspect the SLO events.
_SLO_CAPTURE = "posthog.slo.events.posthoganalytics.capture"

_WINDOW_END = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)


def _test_window() -> ReportWindow:
    return ReportWindow(start=_WINDOW_END - timedelta(days=1), end=_WINDOW_END)


def _spec(steps: int = 1) -> EnrichedPromptSpec:
    return EnrichedPromptSpec(
        cleaned_prompt="p",
        context_blob="c",
        plan=QueryPlan(
            overall_intent="i",
            steps=[QueryPlanStep(description=f"s{n}", hogql="SELECT 1") for n in range(steps)],
        ),
    )


def _slo_completed(capture_mock: MagicMock) -> dict:
    for call in capture_mock.call_args_list:
        if call.kwargs.get("event") == "slo_operation_completed":
            return call.kwargs["properties"]
    raise AssertionError("no slo_operation_completed event was captured")


async def test_user_none_raises_prompt_rejected() -> None:
    with pytest.raises(PromptRejectedError):
        await generate_ai_report(team=MagicMock(), user=None, prompt="x", window=_test_window())


@patch(f"{_RP}.build_enriched_prompt", side_effect=PromptRejectedError("empty"))
async def test_prompt_rejected_propagates_unwrapped(_mock_bep: object) -> None:
    # PromptRejectedError must NOT be wrapped as AiReportStageError — callers catch it by type.
    with pytest.raises(PromptRejectedError):
        await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="", window=_test_window())


@patch(f"{_RP}.build_enriched_prompt", side_effect=RuntimeError("planner boom"))
async def test_planner_failure_wrapped_with_stage(_mock_bep: object) -> None:
    with pytest.raises(AiReportStageError) as exc_info:
        await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())
    assert exc_info.value.stage == "planner"


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_successful_report_emits_slo_success(
    mock_bep: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, mock_capture: MagicMock
) -> None:
    mock_bep.return_value = _spec(steps=2)
    mock_run.return_value = (
        ["### s0\n\nok", "### s1\n\nok"],
        0,
        [
            QueryStepDiagnostic(description="s0", hogql="SELECT 1", ok=True, error_type=None),
            QueryStepDiagnostic(description="s1", hogql="SELECT 2", ok=True, error_type=None),
        ],
    )
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    assert result.markdown == "# Report"
    props = _slo_completed(mock_capture)
    assert props["operation"] == "ai_subscription_prompt_generation"
    assert props["outcome"] == "success"
    assert props["degraded"] is False
    assert props["query_coverage"] == 1.0
    assert props["total_steps"] == 2


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_degraded_report_still_synthesizes(
    mock_bep: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, mock_capture: MagicMock
) -> None:
    # One step failed (failed_count=1) but the report still ships — graceful degradation.
    mock_bep.return_value = _spec(steps=1)
    mock_run.return_value = (
        ["### s0\n\n_Query failed to run (ExposedHogQLError) — metric not computed, not empty data._"],
        1,
        [QueryStepDiagnostic(description="s0", hogql="SELECT bad", ok=False, error_type="ExposedHogQLError")],
    )
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Weekly report")

    result = await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    # Every query failed, so the delivered report leads with the deterministic failure notice
    # prepended to the synthesis output, not a bare confident-looking report.
    assert result.markdown == _all_queries_failed_notice(1) + "# Weekly report"
    # The failed step's generated HogQL + error type are surfaced for persistence/debugging.
    assert result.diagnostics == (
        QueryStepDiagnostic(description="s0", hogql="SELECT bad", ok=False, error_type="ExposedHogQLError"),
    )
    # A degraded-but-shipped report is an SLO success, tagged so the coverage signal survives.
    props = _slo_completed(mock_capture)
    assert props["outcome"] == "success"
    assert props["degraded"] is True
    assert props["failed_steps"] == 1
    assert props["query_coverage"] == 0.0


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_synthesis_failure_wrapped_with_stage(
    mock_bep: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, mock_capture: MagicMock
) -> None:
    mock_bep.return_value = _spec(steps=1)
    mock_run.return_value = (
        ["### s0\n\nok"],
        0,
        [QueryStepDiagnostic(description="s0", hogql="SELECT 1", ok=True, error_type=None)],
    )
    mock_chat.return_value.invoke.side_effect = RuntimeError("synth boom")

    with pytest.raises(AiReportStageError) as exc_info:
        await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())
    assert exc_info.value.stage == "synthesis"
    # A raised stage error burns the SLO error budget.
    assert _slo_completed(mock_capture)["outcome"] == "failure"


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.build_enriched_prompt", side_effect=PromptRejectedError("empty"))
async def test_prompt_rejected_marks_slo_success_not_failure(_mock_bep: MagicMock, mock_capture: MagicMock) -> None:
    # A rejected prompt is the input guard working — it must not count against the error budget.
    with pytest.raises(PromptRejectedError):
        await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="", window=_test_window())
    props = _slo_completed(mock_capture)
    assert props["outcome"] == "success"
    assert props["rejected"] is True


@patch(f"{_RP}.MaxChatOpenAI")
async def test_request_hogql_fix_returns_fixed_query(mock_chat: MagicMock) -> None:
    structured = mock_chat.return_value.with_structured_output.return_value
    structured.invoke.return_value = HogQLFix(fixed_hogql="SELECT 2")
    result = await _arequest_hogql_fix(
        original_hogql="SELECT 1",
        error_message="boom",
        step_description="d",
        team=MagicMock(),
        user=MagicMock(),
        trace_correlation_id=None,
    )
    assert result == "SELECT 2"


@patch(f"{_RP}.MaxChatOpenAI")
async def test_request_hogql_fix_returns_none_on_wrong_type(mock_chat: MagicMock) -> None:
    structured = mock_chat.return_value.with_structured_output.return_value
    structured.invoke.return_value = "not a HogQLFix"
    result = await _arequest_hogql_fix(
        original_hogql="SELECT 1",
        error_message="boom",
        step_description="d",
        team=MagicMock(),
        user=MagicMock(),
        trace_correlation_id=None,
    )
    assert result is None


@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_non_retryable_error_degrades_to_placeholder(mock_executor_cls: MagicMock) -> None:
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(side_effect=RuntimeError("boom"))
    rendered, failed, diagnostics = await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), None)
    assert failed == 1
    assert "Query failed to run" in rendered[0]
    assert diagnostics[0].ok is False
    assert diagnostics[0].error_type == "RuntimeError"
    assert diagnostics[0].hogql == "SELECT 1"


@patch(f"{_RP}._arequest_hogql_fix", new_callable=AsyncMock)
@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_forwards_resolution_error_message_to_fix(
    mock_executor_cls: MagicMock, mock_fix: AsyncMock
) -> None:
    # ResolutionError names the field the planner referenced — its message, not just the type name,
    # must reach the fix LLM so it can actually repair the query.
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(
        side_effect=[ResolutionError("Unable to resolve field 'operaton'"), ("formatted table", None)]
    )
    mock_fix.return_value = "SELECT fixed"
    await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), None)
    assert mock_fix.await_args is not None
    assert mock_fix.await_args.kwargs["error_message"] == "Unable to resolve field 'operaton'"


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_synthesis_prompt_carries_the_failure_marker(
    mock_bep: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, _mock_capture: MagicMock
) -> None:
    # The marker is injected into the synthesis prompt from the same constant the placeholder renders, so
    # the prompt's "this is an error, not 'no data'" instruction can't drift from what _run_steps emits.
    mock_bep.return_value = _spec(steps=1)
    mock_run.return_value = (
        ["### s0\n\nfailed"],
        1,
        [QueryStepDiagnostic(description="s0", hogql="SELECT bad", ok=False, error_type="ExposedHogQLError")],
    )
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    (messages,) = mock_chat.return_value.invoke.call_args[0]
    system_message = messages[0][1]
    assert QUERY_FAILED_PREFIX in system_message  # {{{failure_marker}}} substituted from the constant
    assert "{{{" not in system_message  # no placeholder left unrendered


@patch(f"{_RP}._arequest_hogql_fix", new_callable=AsyncMock)
@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_retries_then_succeeds(mock_executor_cls: MagicMock, mock_fix: AsyncMock) -> None:
    # First attempt raises a retryable HogQL error, the LLM fix yields a new query, the rerun succeeds.
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(
        side_effect=[ExposedHogQLError("bad query"), ("formatted table", None)]
    )
    mock_fix.return_value = "SELECT fixed"
    rendered, failed, diagnostics = await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), None)
    assert failed == 0
    assert "formatted table" in rendered[0]
    mock_fix.assert_awaited_once()
    # The diagnostic tracks the fixed query (current_hogql), not the original SELECT 1.
    assert diagnostics[0].ok is True
    assert diagnostics[0].hogql == "SELECT fixed"


@patch(f"{_RP}._arequest_hogql_fix", new_callable=AsyncMock)
@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_breaks_early_when_fix_returns_same_query(
    mock_executor_cls: MagicMock, mock_fix: AsyncMock
) -> None:
    # The fix LLM echoes the original query back — re-running it is pointless, so we must stop and
    # degrade rather than burn the retry budget on an identical query.
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(side_effect=ExposedHogQLError("bad query"))
    mock_fix.return_value = "SELECT 1"  # identical to QueryPlanStep.hogql in _spec()
    rendered, failed, diagnostics = await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), None)
    assert failed == 1
    assert "Query failed to run" in rendered[0]
    # Executor ran exactly once (no rerun of the identical fixed query); the fix was requested once.
    assert mock_executor_cls.return_value.arun_and_format_query.await_count == 1
    mock_fix.assert_awaited_once()
    # An ExposedHogQLError is safe to surface, so the diagnostic carries the human-readable reason
    # (not just the type) for the delivery viewer to show.
    assert diagnostics[0].error_type == "ExposedHogQLError"
    assert diagnostics[0].human_readable_error == "bad query"


@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_bounds_concurrent_query_execution(mock_executor_cls: MagicMock) -> None:
    # The planner can emit many steps; they must not all hit ClickHouse at once. With more steps than
    # the cap, no more than _MAX_CONCURRENT_STEPS run their query simultaneously (a regression that drops
    # the semaphore would let every step fan out at once).
    concurrent = 0
    max_concurrent = 0
    saturated = asyncio.Event()

    async def _track(_query: object) -> tuple[str, None]:
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        if concurrent >= _MAX_CONCURRENT_STEPS:
            saturated.set()  # cap reached — release the held steps so the rest can run
        await saturated.wait()
        concurrent -= 1
        return ("formatted", None)

    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(side_effect=_track)

    await _run_steps(_spec(steps=_MAX_CONCURRENT_STEPS * 2), MagicMock(), MagicMock(), None)

    assert max_concurrent == _MAX_CONCURRENT_STEPS


def _wrap(
    outer: BaseException, *, cause: BaseException | None = None, context: BaseException | None = None
) -> BaseException:
    if cause is not None:
        outer.__cause__ = cause
    if context is not None:
        outer.__context__ = context
    return outer


@pytest.mark.parametrize(
    "exc,expected",
    [
        (ExposedHogQLError("Unable to resolve field 'operaton'"), "Unable to resolve field 'operaton'"),
        (ResolutionError("Unknown field: signups"), "Unknown field: signups"),
        # A plain InternalHogQLError (not a ResolutionError) can echo team-scoped data — stays type-only.
        (InternalHogQLError("internal detail with a team-scoped id"), None),
        (ValueError("boom"), None),
        # A generic error wrapping a safe error surfaces the wrapped message (executors wrap like this).
        (
            _wrap(Exception("wrapper"), cause=ResolutionError("Unable to resolve field 'x'")),
            "Unable to resolve field 'x'",
        ),
        (_wrap(RuntimeError("boom"), context=ExposedHogQLError("bad thing")), "bad thing"),
        # A generic error wrapping only generic errors stays type-only.
        (_wrap(Exception("outer"), cause=ValueError("inner")), None),
    ],
)
def test_safe_error_message_only_surfaces_query_structure_errors(exc, expected):
    assert _safe_error_message(exc) == expected
