from datetime import datetime

import pytest
from unittest.mock import AsyncMock, call, patch

from temporalio.exceptions import ActivityError, ApplicationError

from products.signals.backend.temporal.drop_telemetry import summarize_drop_error
from products.signals.backend.temporal.grouping import (
    AssignAndEmitSignalOutput,
    FetchReportContextsOutput,
    GenerateEmbeddingOutput,
    GenerateSearchQueriesOutput,
    SignalBatchPrepError,
    _process_signal_batch,
    fetch_report_contexts_activity,
    generate_search_queries_activity,
    get_embedding_activity,
    match_signal_to_report_activity,
)
from products.signals.backend.temporal.grouping_v2 import (
    MAX_PREP_ATTEMPTS,
    MAX_PREP_BACKOFF,
    RETRY_BACKOFF,
    CollectedBatch,
    TeamSignalGroupingV2Workflow,
)
from products.signals.backend.temporal.signal_queries import (
    FetchSignalTypeExamplesOutput,
    RunSignalSemanticSearchOutput,
    run_signal_semantic_search_activity,
)
from products.signals.backend.temporal.types import (
    EmitSignalInputs,
    NewReportMatch,
    NoMatchMetadata,
    TeamSignalGroupingV2Input,
)

GROUPING_MODULE_PATH = "products.signals.backend.temporal.grouping"
GROUPING_V2_MODULE_PATH = "products.signals.backend.temporal.grouping_v2"

QUERY = "search query"


def _make_signal(source_id: str, description: str) -> EmitSignalInputs:
    return EmitSignalInputs(
        team_id=1,
        source_product="signals_scout",
        source_type="cross_source_issue",
        source_id=source_id,
        description=description,
        weight=0.7,
    )


def _connect_error() -> ActivityError:
    error = ActivityError(
        "Activity task failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="get_embedding_activity",
        activity_id="1",
        retry_state=None,
    )
    error.__cause__ = ApplicationError("the embedding worker is unreachable", type="ConnectError")
    return error


def _prep_error() -> SignalBatchPrepError:
    return SignalBatchPrepError("Failed to prepare a batch of 2 signals", _connect_error())


def _workflow(prep_failures: int) -> TeamSignalGroupingV2Workflow:
    instance = TeamSignalGroupingV2Workflow()
    instance._prep_failures = prep_failures
    return instance


def _collected() -> CollectedBatch:
    return CollectedBatch(
        signals=[_make_signal("a", "first finding"), _make_signal("b", "second finding")],
        object_keys=["key-1"],
    )


def _activity_dispatcher(unreachable_descriptions: set[str]):
    """Stand in for the whole batch pipeline, failing embedding for the given descriptions."""

    async def dispatch(activity, activity_input, **kwargs):
        if activity is get_embedding_activity:
            if activity_input.content in unreachable_descriptions:
                raise _connect_error()
            return GenerateEmbeddingOutput(embedding=[1.0, 0.0])
        if activity is generate_search_queries_activity:
            return GenerateSearchQueriesOutput(queries=[QUERY])
        if activity is run_signal_semantic_search_activity:
            return RunSignalSemanticSearchOutput(candidates=[])
        if activity is fetch_report_contexts_activity:
            return FetchReportContextsOutput(contexts={})
        if activity is match_signal_to_report_activity:
            return NewReportMatch(title="a title", summary="a summary", match_metadata=NoMatchMetadata(reason="new"))
        return AssignAndEmitSignalOutput(
            report_id="report-1",
            promoted=False,
            timestamp=datetime(2026, 9, 15),
            run_count=0,
        )

    return dispatch


class TestProcessSignalBatchPrep:
    @pytest.mark.asyncio
    async def test_preparation_failure_raises_without_reporting_drops(self):
        """The signals of a batch that could not be prepared are not lost until a caller says so."""
        batch = [_make_signal("a", "first finding"), _make_signal("b", "second finding")]

        with (
            patch(f"{GROUPING_MODULE_PATH}.workflow.patched", return_value=False),
            patch(
                f"{GROUPING_MODULE_PATH}.workflow.execute_activity",
                new_callable=AsyncMock,
                side_effect=_activity_dispatcher({"first finding", "second finding"}),
            ),
            patch(f"{GROUPING_MODULE_PATH}.capture_signal_dropped", new_callable=AsyncMock) as capture_dropped,
        ):
            with pytest.raises(SignalBatchPrepError) as raised:
                await _process_signal_batch(batch, cached_type_examples=FetchSignalTypeExamplesOutput(examples=[]))

        capture_dropped.assert_not_called()
        # The caller reports drops against this, so it has to keep naming the original failure
        assert summarize_drop_error(raised.value.cause)[0] == "ConnectError"


class TestHoldBatchAfterPrepFailure:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "prep_failures,expected_backoff",
        [(0, RETRY_BACKOFF), (3, RETRY_BACKOFF * 8), (MAX_PREP_ATTEMPTS - 2, MAX_PREP_BACKOFF)],
    )
    async def test_batch_is_held_and_backed_off_instead_of_dropped(self, prep_failures, expected_backoff):
        instance = _workflow(prep_failures)
        collected = _collected()

        with (
            patch(f"{GROUPING_V2_MODULE_PATH}.workflow.sleep", new_callable=AsyncMock) as sleep,
            patch(f"{GROUPING_V2_MODULE_PATH}.capture_batch_dropped", new_callable=AsyncMock) as capture_dropped,
        ):
            await instance._hold_batch_after_prep_failure(
                TeamSignalGroupingV2Input(team_id=1), collected, _prep_error()
            )

        capture_dropped.assert_not_called()
        assert instance._batch_key_buffer == ["key-1"]
        sleep.assert_awaited_once_with(expected_backoff)

    @pytest.mark.asyncio
    async def test_batch_is_dropped_once_it_has_been_held_long_enough(self):
        instance = _workflow(MAX_PREP_ATTEMPTS - 1)
        collected = _collected()

        with (
            patch(f"{GROUPING_V2_MODULE_PATH}.workflow.sleep", new_callable=AsyncMock) as sleep,
            patch(f"{GROUPING_V2_MODULE_PATH}.capture_batch_dropped", new_callable=AsyncMock) as capture_dropped,
        ):
            await instance._hold_batch_after_prep_failure(
                TeamSignalGroupingV2Input(team_id=1), collected, _prep_error()
            )

        capture_dropped.assert_awaited_once()
        assert [signal.source_id for signal in capture_dropped.call_args.args[0]] == ["a", "b"]
        assert instance._batch_key_buffer == []
        assert instance._prep_failures == 0
        sleep.assert_not_awaited()


class TestPrepFailureStreakAcrossRounds:
    @pytest.mark.asyncio
    async def test_a_failure_after_preparation_ends_the_streak(self):
        """A round that prepares and then fails later must not leave an older streak in place."""
        instance = _workflow(MAX_PREP_ATTEMPTS - 1)
        workflow_input = TeamSignalGroupingV2Input(team_id=1)

        with (
            patch(f"{GROUPING_V2_MODULE_PATH}.workflow.patched", return_value=True),
            patch(f"{GROUPING_V2_MODULE_PATH}.workflow.continue_as_new"),
            patch(f"{GROUPING_V2_MODULE_PATH}.workflow.sleep", new_callable=AsyncMock) as sleep,
            patch(f"{GROUPING_V2_MODULE_PATH}.capture_batch_dropped", new_callable=AsyncMock) as capture_dropped,
            patch.object(instance, "_collect_next_batch", new_callable=AsyncMock, return_value=_collected()),
            patch(
                f"{GROUPING_V2_MODULE_PATH}._process_signal_batch",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("the visibility wait timed out"), _prep_error()],
            ),
        ):
            await instance._run_new_collect_batch_path(workflow_input)
            assert instance._prep_failures == 0
            await instance._run_new_collect_batch_path(workflow_input)

        capture_dropped.assert_not_called()
        assert instance._prep_failures == 1
        assert sleep.await_args_list == [call(RETRY_BACKOFF), call(RETRY_BACKOFF)]
