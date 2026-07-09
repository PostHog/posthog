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
    AI_QUERY_PLAN_VERSION,
    PromptRejectedError,
    ReportWindow,
    StoredPlanInvalidError,
)

_RP = "products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline"
# slo_operation emits through posthoganalytics.capture; patch that boundary to inspect the SLO events.
_SLO_CAPTURE = "posthog.slo.events.posthoganalytics.capture"

_WINDOW_END = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)


def _test_window() -> ReportWindow:
    return ReportWindow(start=_WINDOW_END - timedelta(days=1), end=_WINDOW_END)


_ALL_FAILED_RUN = (
    ["### s0\n\n_Query failed to run (ExposedHogQLError)_"],
    1,
    [QueryStepDiagnostic("s0", "SELECT bad", False, "ExposedHogQLError")],
    ["SELECT count() FROM events WHERE {{date_range}}"],
)
_OK_RUN = (["### s\n\nok"], 0, [QueryStepDiagnostic("s", "SELECT count() FROM events", True, None)], ["SELECT 1"])


def _spec(steps: int = 1) -> EnrichedPromptSpec:
    return EnrichedPromptSpec(
        cleaned_prompt="p",
        context_blob="c",
        plan=QueryPlan(
            overall_intent="i",
            steps=[QueryPlanStep(description=f"s{n}", hogql="SELECT 1") for n in range(steps)],
        ),
    )


def _spec_with_window_placeholder() -> EnrichedPromptSpec:
    return EnrichedPromptSpec(
        cleaned_prompt="p",
        context_blob="c",
        plan=QueryPlan(
            overall_intent="i",
            steps=[QueryPlanStep(description="s0", hogql="SELECT count() FROM events WHERE {{date_range}}")],
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
        ["SELECT 1", "SELECT 2"],
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
        ["SELECT 1"],
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
        ["SELECT 1"],
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
    rendered, failed, diagnostics, _ = await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), _test_window(), None)
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
    await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), _test_window(), None)
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
        ["SELECT 1"],
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
    rendered, failed, diagnostics, final_hogql = await _run_steps(
        _spec(steps=1), MagicMock(), MagicMock(), _test_window(), None
    )
    assert failed == 0
    assert "formatted table" in rendered[0]
    mock_fix.assert_awaited_once()
    # The diagnostic tracks the fixed query (current_hogql), not the original SELECT 1.
    assert diagnostics[0].ok is True
    assert diagnostics[0].hogql == "SELECT fixed"
    # The freezable form is the post-fix query — freezing the original would re-run the fix every reuse.
    assert final_hogql == ["SELECT fixed"]


@patch(f"{_RP}._arequest_hogql_fix", new_callable=AsyncMock)
@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_breaks_early_when_fix_returns_same_query(
    mock_executor_cls: MagicMock, mock_fix: AsyncMock
) -> None:
    # The fix LLM echoes the original query back — re-running it is pointless, so we must stop and
    # degrade rather than burn the retry budget on an identical query.
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(side_effect=ExposedHogQLError("bad query"))
    mock_fix.return_value = "SELECT 1"  # identical to QueryPlanStep.hogql in _spec()
    rendered, failed, diagnostics, _ = await _run_steps(_spec(steps=1), MagicMock(), MagicMock(), _test_window(), None)
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

    await _run_steps(_spec(steps=_MAX_CONCURRENT_STEPS * 2), MagicMock(), MagicMock(), _test_window(), None)

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


def _frozen_plan() -> dict:
    return {
        "version": AI_QUERY_PLAN_VERSION,
        "plan": QueryPlan(
            overall_intent="count events",
            steps=[QueryPlanStep(description="counts", hogql="SELECT count() FROM events WHERE {{date_range}}")],
        ).model_dump(),
    }


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_frozen_prompt")
@patch(f"{_RP}.build_enriched_prompt")
async def test_frozen_plan_reused_skips_planner_and_event_selection(
    mock_bep: MagicMock, mock_frozen: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, _mock_capture: MagicMock
) -> None:
    # The determinism guarantee: when a plan is frozen, the run reconstructs the spec from it and runs
    # NEITHER LLM pass the live path uses — build_enriched_prompt wraps both the planner and the
    # event-selection model, so asserting it's never called proves both are skipped.
    mock_frozen.return_value = _spec(steps=1)
    mock_run.return_value = (["### s0\n\nok"], 0, [QueryStepDiagnostic("s0", "SELECT 1", True, None)], ["SELECT 1"])
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(
        team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window(), ai_query_plan=_frozen_plan()
    )

    mock_bep.assert_not_called()  # planner + event-selection LLMs never run on a frozen sub
    mock_frozen.assert_called_once()
    # Nothing new to freeze on a reused run — the caller must not re-persist the same plan.
    assert result.plan_to_persist is None


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_unfrozen_run_returns_plan_to_persist(
    mock_bep: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, _mock_capture: MagicMock
) -> None:
    # First run (no frozen plan): the freshly-planned QueryPlan is returned for the caller to persist,
    # so the next delivery is deterministic. The shape must equal QueryPlan.model_dump() — that exact
    # dict is what build_frozen_prompt validates back on reuse, so this guards the persist↔reuse contract.
    spec = _spec_with_window_placeholder()
    mock_bep.return_value = spec
    mock_run.return_value = (
        ["### s0\n\nok"],
        0,
        [QueryStepDiagnostic("s0", "SELECT 1", True, None)],
        [spec.plan.steps[0].hogql],
    )
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    assert result.plan_to_persist == {"version": AI_QUERY_PLAN_VERSION, "plan": spec.plan.model_dump()}


@pytest.mark.parametrize(
    "fixed_hogql,expected_frozen_hogql",
    [
        # The fix LLM rewrote the step and the rerun succeeded: the frozen plan must carry the post-fix
        # query, or every reused delivery replays the broken original and re-bills the fix LLM.
        pytest.param(
            "SELECT uniq(person_id) FROM events WHERE {{date_range}}",
            "SELECT uniq(person_id) FROM events WHERE {{date_range}}",
            id="post_fix_hogql_is_frozen",
        ),
        # The fixer stripped the window placeholder: the guard applies to the post-fix text, so nothing
        # is frozen — freezing it would cement an unbounded scan.
        pytest.param("SELECT uniq(person_id) FROM events", None, id="fix_without_placeholder_not_frozen"),
    ],
)
@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._arequest_hogql_fix", new_callable=AsyncMock)
@patch(f"{_RP}.AssistantQueryExecutor")
@patch(f"{_RP}.build_enriched_prompt")
async def test_freeze_carries_post_fix_hogql(
    mock_bep: MagicMock,
    mock_executor_cls: MagicMock,
    mock_fix: AsyncMock,
    mock_chat: MagicMock,
    _mock_capture: MagicMock,
    fixed_hogql: str,
    expected_frozen_hogql: str | None,
) -> None:
    mock_bep.return_value = _spec_with_window_placeholder()
    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(
        side_effect=[ExposedHogQLError("bad query"), ("formatted table", None)]
    )
    mock_fix.return_value = fixed_hogql
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    if expected_frozen_hogql is None:
        assert result.plan_to_persist is None
    else:
        assert result.plan_to_persist is not None
        assert result.plan_to_persist["version"] == AI_QUERY_PLAN_VERSION
        assert result.plan_to_persist["plan"]["steps"][0]["hogql"] == expected_frozen_hogql


@patch(f"{_RP}.AssistantQueryExecutor")
async def test_run_steps_substitutes_fresh_window_into_placeholder_sql(mock_executor_cls: MagicMock) -> None:
    # The frozen HogQL keeps the {{date_range}} placeholder; the executor substitutes THIS run's bounds.
    # Two runs of the same frozen step at different `now` must execute different window literals (so the
    # window advances) while the rest of the SQL is byte-identical (so the metric structure is frozen).
    captured: list[str] = []

    async def _capture(query: object) -> tuple[str, None]:
        captured.append(query.query)  # type: ignore[attr-defined]
        return ("formatted", None)

    mock_executor_cls.return_value.arun_and_format_query = AsyncMock(side_effect=_capture)
    spec = EnrichedPromptSpec(
        cleaned_prompt="p",
        context_blob="c",
        plan=QueryPlan(
            overall_intent="i",
            steps=[QueryPlanStep(description="s", hogql="SELECT count() FROM events WHERE {{date_range}}")],
        ),
    )
    early = ReportWindow(start=_WINDOW_END - timedelta(days=1), end=_WINDOW_END)
    later = ReportWindow(start=_WINDOW_END, end=_WINDOW_END + timedelta(days=1))

    await _run_steps(spec, MagicMock(), MagicMock(), early, None)
    await _run_steps(spec, MagicMock(), MagicMock(), later, None)

    assert "{{date_range}}" not in captured[0]  # placeholder fully resolved before execution
    assert captured[0] != captured[1]  # window advanced run-to-run
    # Same structure: only the substituted bounds differ. Stripping the window predicate makes them equal.
    skeleton_0 = captured[0].replace(early.window_filter_sql, "")
    skeleton_1 = captured[1].replace(later.window_filter_sql, "")
    assert skeleton_0 == skeleton_1


@pytest.mark.parametrize(
    "spec,run_result",
    [
        # All steps failed: freezing would replay a broken plan every delivery instead of re-planning.
        pytest.param(_spec_with_window_placeholder(), _ALL_FAILED_RUN, id="all_failed"),
        # No window placeholder: freezing would cement an unbounded, window-less scan forever.
        pytest.param(_spec(steps=1), _OK_RUN, id="missing_window_placeholder"),
    ],
)
@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_enriched_prompt")
async def test_unfreezable_plans_are_not_frozen(
    mock_bep: MagicMock,
    mock_run: AsyncMock,
    mock_chat: MagicMock,
    _mock_capture: MagicMock,
    spec: EnrichedPromptSpec,
    run_result: tuple,
) -> None:
    mock_bep.return_value = spec
    mock_run.return_value = run_result
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window())

    assert result.plan_to_persist is None


@patch(_SLO_CAPTURE)
@patch(f"{_RP}.MaxChatOpenAI")
@patch(f"{_RP}._run_steps", new_callable=AsyncMock)
@patch(f"{_RP}.build_frozen_prompt", side_effect=StoredPlanInvalidError("malformed"))
@patch(f"{_RP}.build_enriched_prompt")
async def test_invalid_stored_plan_self_heals_by_replanning(
    mock_bep: MagicMock, _mock_frozen: MagicMock, mock_run: AsyncMock, mock_chat: MagicMock, _mock_capture: MagicMock
) -> None:
    # A stored plan that no longer validates (e.g. QueryPlan schema changed) must re-plan live, not fail
    # the delivery — otherwise a schema change would auto-disable every frozen subscription.
    mock_bep.return_value = _spec_with_window_placeholder()
    mock_run.return_value = (
        ["### s0\n\nok"],
        0,
        [QueryStepDiagnostic("s0", "SELECT 1", True, None)],
        ["SELECT count() FROM events WHERE {{date_range}}"],
    )
    mock_chat.return_value.invoke.return_value = MagicMock(content="# Report")

    result = await generate_ai_report(
        team=MagicMock(), user=MagicMock(), prompt="x", window=_test_window(), ai_query_plan={"bad": "plan"}
    )

    mock_bep.assert_called_once()  # self-healed by re-planning live
    assert result.markdown == "# Report"
    assert result.plan_to_persist is not None  # the fresh re-plan is frozen for next time
