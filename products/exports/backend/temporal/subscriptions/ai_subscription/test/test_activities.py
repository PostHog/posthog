import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from threading import Event
from typing import ParamSpec, TypeVar
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import (
    DiagnosticCounts,
    _load_snapshot,
    _persist_ai_report,
    _report_diagnostic_counts,
    _snapshot_diagnostic_counts,
    enrich_ai_subscription_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.charts import RenderedChart
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    QueryStepDiagnostic,
)
from products.exports.backend.temporal.subscriptions.types import (
    AI_REPORT_CHARTS_KEY,
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_RECOMMENDATION_INPUT_KEY,
    AI_REPORT_RECOMMENDATIONS_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    GenerateAIReportInputs,
)
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.contracts import (
    Recommendation,
    RecommendationCitation,
    RecommendationGenerationHandle,
    RecommendationGenerationState,
    RecommendationResult,
)
from products.subscriptions.backend.facade.proactive import (
    RecommendationAppendixDTO,
    read_recommendation_appendix,
    update_proactive_config,
)
from products.tasks.backend.facade.staged_execution import StagedRepositoryBinding

_WINDOW_END_UTC = "2026-06-25T12:00:00+00:00"

P = ParamSpec("P")
R = TypeVar("R")

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@sync_to_async
def _create_delivery(team, user) -> SubscriptionDelivery:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    subscription = Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot={},
    )


@sync_to_async
def _snapshot(delivery_id) -> dict:
    return SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)


@sync_to_async
def _create_proactive_delivery(team, user) -> SubscriptionDelivery:
    subscription = Subscription.objects.create(
        team=team,
        prompt="Find the most useful product improvement",
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )
    update_proactive_config(
        team_id=team.id,
        subscription_id=subscription.id,
        enabled=True,
        allow_public_web_research=True,
    )
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot={
            AI_REPORT_SNAPSHOT_KEY: "# Weekly report\n\nActivation fell this week.",
            AI_REPORT_PROMPT_SNAPSHOT_KEY: subscription.prompt,
        },
    )


async def test_persist_ai_report_writes_markdown_query_diagnostics_and_prompt(team, user) -> None:
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="# Weekly report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(
                QueryStepDiagnostic(description="adoption", hogql="SELECT count()", ok=True, error_type=None),
                QueryStepDiagnostic(
                    description="reliability",
                    hogql="SELECT bad",
                    ok=False,
                    error_type="QueryError",
                    error_code="hogql_query_error",
                    human_readable_error="Unable to resolve field 'reliability'",
                ),
            ),
        ),
        prompt="weekly adoption + reliability report",
    )

    snapshot = await _snapshot(delivery.id)
    assert snapshot[AI_REPORT_SNAPSHOT_KEY] == "# Weekly report"
    assert snapshot[AI_REPORT_DIAGNOSTICS_KEY] == [
        {
            "description": "adoption",
            "hogql": "SELECT count()",
            "ok": True,
            "error_type": None,
            "error_code": None,
            "human_readable_error": None,
            "chart_dropped_reason": None,
        },
        {
            "description": "reliability",
            "hogql": "SELECT bad",
            "ok": False,
            "error_type": "QueryError",
            "human_readable_error": "Unable to resolve field 'reliability'",
            "chart_dropped_reason": None,
            "error_code": "hogql_query_error",
        },
    ]
    # The generating prompt is captured so the delivery is reproducible and the viewer can show it.
    assert snapshot[AI_REPORT_PROMPT_SNAPSHOT_KEY] == "weekly adoption + reliability report"
    assert snapshot[AI_REPORT_CHARTS_KEY] == []


async def test_persist_ai_report_writes_chart_references_not_images(team, user) -> None:
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="# Weekly report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(),
            charts=(RenderedChart(export_asset_id=99, title="signups by day", step_index=0),),
        ),
        prompt="weekly report",
    )

    snapshot = await _snapshot(delivery.id)
    assert snapshot[AI_REPORT_CHARTS_KEY] == [{"export_asset_id": 99, "title": "signups by day", "step_index": 0}]


async def test_persist_ai_report_strips_null_bytes(team, user) -> None:
    # Regression witness: LLM output, diagnostics, and the prompt are untrusted NUL sources. Without
    # the scrub, the NUL reaches content_snapshot and Postgres rejects the whole save with a DataError,
    # so this test would fail on the write itself; with it, the NULs are gone and the rest survives.
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="# Weekly\x00 report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(
                QueryStepDiagnostic(description="adop\x00tion", hogql="SELECT co\x00unt()", ok=True, error_type=None),
            ),
        ),
        prompt="weekly\x00 report",
    )

    snapshot = await _snapshot(delivery.id)
    assert snapshot[AI_REPORT_SNAPSHOT_KEY] == "# Weekly report"
    assert snapshot[AI_REPORT_DIAGNOSTICS_KEY][0]["description"] == "adoption"
    assert snapshot[AI_REPORT_DIAGNOSTICS_KEY][0]["hogql"] == "SELECT count()"
    assert snapshot[AI_REPORT_PROMPT_SNAPSHOT_KEY] == "weekly report"


@pytest.mark.parametrize("prompt", [None, ""])
async def test_persist_ai_report_omits_blank_prompt(team, user, prompt) -> None:
    # A non-AI sub passes prompt=None and a cleared prompt passes ""; neither should write the key
    # (so the viewer doesn't render an empty "prompt at time of generation" block).
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(markdown="# report", diagnostics=(), window_end_utc=_WINDOW_END_UTC),
        prompt=prompt,
    )

    snapshot = await _snapshot(delivery.id)
    assert AI_REPORT_PROMPT_SNAPSHOT_KEY not in snapshot


class TestReportDiagnosticCounts:
    @parameterized.expand(
        [
            ("all_ok", [True, True], 0, 2, [], []),
            (
                "partial",
                [True, False],
                1,
                2,
                ["ResolutionError"],
                [{"type": "ResolutionError", "code": None, "message": None}],
            ),
            (
                "all_failed",
                [False, False],
                2,
                2,
                ["ResolutionError"],
                [
                    {"type": "ResolutionError", "code": None, "message": None},
                    {"type": "ResolutionError", "code": None, "message": None},
                ],
            ),
            ("none", [], 0, 0, [], []),
        ]
    )
    def test_counts_failures_and_distinct_error_types(
        self, _name, oks, expected_failed, expected_total, expected_types, expected_errors
    ):
        result = AiReportResult(
            markdown="report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=tuple(
                QueryStepDiagnostic(
                    description=f"step {i}",
                    hogql="SELECT 1",
                    ok=ok,
                    error_type=None if ok else "ResolutionError",
                )
                for i, ok in enumerate(oks)
            ),
        )
        counts = _report_diagnostic_counts(result)
        assert counts == DiagnosticCounts(
            failed_step_count=expected_failed,
            total_step_count=expected_total,
            query_errors=expected_errors,
        )
        assert counts.error_types == expected_types

    def test_distinct_error_types_are_sorted_and_deduped(self):
        result = AiReportResult(
            markdown="report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(
                QueryStepDiagnostic(description="a", hogql="x", ok=False, error_type="ResolutionError"),
                QueryStepDiagnostic(description="b", hogql="y", ok=False, error_type="ExposedHogQLError"),
                QueryStepDiagnostic(description="c", hogql="z", ok=False, error_type="ResolutionError"),
            ),
        )
        counts = _report_diagnostic_counts(result)
        assert counts == DiagnosticCounts(
            failed_step_count=3,
            total_step_count=3,
            query_errors=[
                {"type": "ResolutionError", "code": None, "message": None},
                {"type": "ExposedHogQLError", "code": None, "message": None},
                {"type": "ResolutionError", "code": None, "message": None},
            ],
        )
        assert counts.error_types == ["ExposedHogQLError", "ResolutionError"]

    def test_pairs_each_safe_query_error_with_its_type(self):
        result = AiReportResult(
            markdown="report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(
                QueryStepDiagnostic(
                    description="memory",
                    hogql="SELECT expensive",
                    ok=False,
                    error_type="ClickHouseQueryMemoryLimitExceeded",
                    error_code="clickhouse_memory_limit_exceeded",
                    human_readable_error="Query exceeded the memory limit.",
                ),
                QueryStepDiagnostic(
                    description="resolution",
                    hogql="SELECT bad",
                    ok=False,
                    error_type="QueryError",
                    error_code="hogql_query_error",
                    human_readable_error="Unable to resolve field 'bad'",
                ),
            ),
        )

        assert _report_diagnostic_counts(result) == DiagnosticCounts(
            failed_step_count=2,
            total_step_count=2,
            query_errors=[
                {
                    "type": "ClickHouseQueryMemoryLimitExceeded",
                    "code": "clickhouse_memory_limit_exceeded",
                    "message": "Query exceeded the memory limit.",
                },
                {
                    "type": "QueryError",
                    "code": "hogql_query_error",
                    "message": "Unable to resolve field 'bad'",
                },
            ],
        )


# On Temporal redispatch the report is already persisted, so the failure shape is read back from the
# snapshot rather than recomputed — the persist -> load -> count round-trip must match what was written.
async def test_snapshot_diagnostic_counts_reads_persisted_failure_shape(team, user) -> None:
    delivery = await _create_delivery(team, user)
    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="report",
            window_end_utc=_WINDOW_END_UTC,
            diagnostics=(
                QueryStepDiagnostic(description="ok step", hogql="SELECT 1", ok=True, error_type=None),
                QueryStepDiagnostic(
                    description="bad step",
                    hogql="SELECT bad",
                    ok=False,
                    error_type="QueryError",
                    error_code="hogql_query_error",
                    human_readable_error="Unable to resolve field 'bad'",
                ),
            ),
        ),
        prompt=None,
    )

    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == DiagnosticCounts(
        failed_step_count=1,
        total_step_count=2,
        query_errors=[
            {
                "type": "QueryError",
                "code": "hogql_query_error",
                "message": "Unable to resolve field 'bad'",
            }
        ],
    )


async def test_snapshot_diagnostic_counts_handles_missing_diagnostics(team, user) -> None:
    delivery = await _create_delivery(team, user)
    # Empty content_snapshot (nothing persisted yet) and a fully-missing snapshot both report nothing failed.
    empty_counts = DiagnosticCounts(failed_step_count=0, total_step_count=0, query_errors=[])
    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == empty_counts
    assert _snapshot_diagnostic_counts(None) == empty_counts


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_appends_a_completed_result_once(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    settings.PULSE_PUBLIC_RESEARCH_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    handle = RecommendationGenerationHandle(staged_run_id=uuid4(), task_id=uuid4(), analysis_run_id=uuid4())
    state = RecommendationGenerationState(
        status="completed",
        result=RecommendationResult(
            recommendations=(
                Recommendation(
                    kind="investigation",
                    title="Investigate the activation drop",
                    rationale="Activation fell in the saved report.",
                    target="activation",
                    why_now="The latest period moved down.",
                    confidence=0.8,
                    effort="small",
                    metric_name="activation rate",
                    metric_direction="increase",
                    expected_metric_movement="recover the recent decline",
                    citation_ids=("report",),
                    semantic_key="investigate-activation-drop",
                ),
            ),
            citations=(RecommendationCitation(id="report", title="Subscription report"),),
        ),
    )
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.subscriptions.backend.facade.proactive.start_recommendation_generation",
            return_value=handle,
        ) as start_generation,
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.read_recommendation_generation",
            return_value=state,
        ),
    ):
        await enrich_ai_subscription_report(inputs)
        await enrich_ai_subscription_report(inputs)

    snapshot = await _snapshot(delivery.id)
    assert start_generation.call_count == 1
    assert snapshot[AI_REPORT_SNAPSHOT_KEY].count("Investigate the activation drop") == 1
    assert "## Recommendations" in snapshot[AI_REPORT_RECOMMENDATIONS_KEY]


@pytest.mark.usefixtures("settings")
async def test_proactive_polling_releases_the_shared_database_executor(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    settings.PULSE_PROACTIVE_TIMEOUT_SECONDS = 2
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    handle = RecommendationGenerationHandle(staged_run_id=uuid4(), task_id=uuid4(), analysis_run_id=uuid4())
    completed = RecommendationGenerationState(
        status="completed",
        result=RecommendationResult(recommendations=(), citations=()),
    )
    poll_started = Event()
    states = iter((RecommendationGenerationState(status="pending"), completed))
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=1) as executor:

        def constrained_database_sync_to_async(
            function: Callable[P, R], thread_sensitive: bool = True
        ) -> Callable[P, Awaitable[R]]:
            async def call(*args: P.args, **kwargs: P.kwargs) -> R:
                return await loop.run_in_executor(executor, partial(function, *args, **kwargs))

            return call

        def read_generation(*_args: object) -> RecommendationGenerationState:
            poll_started.set()
            return next(states)

        with (
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
                return_value=True,
            ),
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
                return_value=False,
            ),
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities.database_sync_to_async",
                constrained_database_sync_to_async,
            ),
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities._PULSE_POLL_INTERVAL_SECONDS",
                1,
            ),
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities.temporalio.activity.heartbeat"
            ),
            patch(
                "products.subscriptions.backend.facade.proactive.start_recommendation_generation",
                return_value=handle,
            ),
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.activities.read_recommendation_generation",
                side_effect=read_generation,
            ),
        ):
            enrichment = asyncio.create_task(enrich_ai_subscription_report(inputs))
            while not poll_started.is_set():
                await asyncio.sleep(0)
            competing_read = constrained_database_sync_to_async(lambda: "available", thread_sensitive=False)()
            try:
                executor_result = await asyncio.wait_for(competing_read, timeout=0.5)
            except TimeoutError:
                executor_result = "blocked"
            await enrichment

    assert executor_result == "available"


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_failure_is_terminal_and_preserves_the_base_report(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    start_generation = MagicMock(side_effect=RuntimeError("generation unavailable"))

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.subscriptions.backend.facade.proactive.start_recommendation_generation",
            start_generation,
        ),
    ):
        await enrich_ai_subscription_report(inputs)
        await enrich_ai_subscription_report(inputs)

    snapshot = await _snapshot(delivery.id)
    assert start_generation.call_count == 1
    assert snapshot[AI_REPORT_SNAPSHOT_KEY] == "# Weekly report\n\nActivation fell this week."
    assert AI_REPORT_RECOMMENDATIONS_KEY not in snapshot


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_timeout_is_terminal(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    settings.PULSE_PROACTIVE_TIMEOUT_SECONDS = 0
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    handle = RecommendationGenerationHandle(staged_run_id=uuid4(), task_id=uuid4(), analysis_run_id=uuid4())

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.subscriptions.backend.facade.proactive.start_recommendation_generation",
            return_value=handle,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.read_recommendation_generation",
            return_value=RecommendationGenerationState(status="pending"),
        ),
    ):
        await enrich_ai_subscription_report(inputs)

    appendix = await sync_to_async(read_recommendation_appendix)(
        team_id=team.id,
        delivery_id=delivery.id,
    )
    assert appendix is not None
    assert appendix.status == "failed"
    assert appendix.failure_code == "timeout"


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_respects_the_existing_credit_gate(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix"
        ) as generate_appendix,
    ):
        await enrich_ai_subscription_report(inputs)

    assert generate_appendix.call_count == 0
    snapshot = await _snapshot(delivery.id)
    assert snapshot[AI_REPORT_SNAPSHOT_KEY] == "# Weekly report\n\nActivation fell this week."
    assert snapshot[AI_REPORT_PROMPT_SNAPSHOT_KEY] == "Find the most useful product improvement"
    assert snapshot[AI_REPORT_RECOMMENDATION_INPUT_KEY]["prompt"] == snapshot[AI_REPORT_PROMPT_SNAPSHOT_KEY]
    assert AI_REPORT_RECOMMENDATIONS_KEY not in snapshot


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_reuses_the_frozen_delivery_input(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    generate_appendix = AsyncMock(
        return_value=RecommendationAppendixDTO(
            status="failed", recommendations=(), citations=(), failure_code="unavailable"
        )
    )

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix",
            generate_appendix,
        ),
    ):
        await enrich_ai_subscription_report(inputs)
        await sync_to_async(Subscription.objects.filter(id=delivery.subscription_id).update)(prompt="new prompt")
        await enrich_ai_subscription_report(inputs)

    first_input = generate_appendix.call_args_list[0].kwargs["input"]
    replay_input = generate_appendix.call_args_list[1].kwargs["input"]
    assert first_input.prompt == "Find the most useful product improvement"
    assert replay_input.prompt == first_input.prompt
    assert replay_input.contexts == first_input.contexts


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_honors_a_research_opt_out_on_retry(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    settings.PULSE_PUBLIC_RESEARCH_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    generate_appendix = AsyncMock(
        return_value=RecommendationAppendixDTO(
            status="failed", recommendations=(), citations=(), failure_code="unavailable"
        )
    )

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix",
            generate_appendix,
        ),
    ):
        await enrich_ai_subscription_report(inputs)
        await sync_to_async(update_proactive_config)(
            team_id=team.id,
            subscription_id=delivery.subscription_id,
            enabled=True,
            allow_public_web_research=False,
        )
        await enrich_ai_subscription_report(inputs)

    assert generate_appendix.call_count == 1
    assert generate_appendix.call_args.kwargs["input"].public_web_research is True


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_requires_current_project_access(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._actor_has_project_access",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix"
        ) as generate_appendix,
    ):
        await enrich_ai_subscription_report(inputs)

    generate_appendix.assert_not_called()


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_resolves_draft_repository_consent_before_analysis(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    await sync_to_async(update_proactive_config)(
        team_id=team.id,
        subscription_id=delivery.subscription_id,
        enabled=True,
        allow_public_web_research=True,
        create_draft_pr=True,
        repository="posthog/posthog",
        repository_integration_id=123,
    )
    binding = StagedRepositoryBinding(
        repository="posthog/posthog",
        base_sha="a" * 40,
        base_branch="master",
        github_integration_id=123,
        github_user_integration_id=uuid4(),
        github_installation_id="456",
        grant_version="stable-grant",
    )
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    generate_appendix = AsyncMock(
        return_value=RecommendationAppendixDTO(
            status="failed", recommendations=(), citations=(), failure_code="timeout"
        )
    )

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.resolve_draft_repository_binding",
            return_value=binding,
        ) as resolve_binding,
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix",
            generate_appendix,
        ),
    ):
        await enrich_ai_subscription_report(inputs)

    resolve_binding.assert_called_once()
    generation_input = generate_appendix.call_args.kwargs["input"]
    assert generation_input.repository == binding
    assert generation_input.create_draft_pr is True
    assert generation_input.repository_name == "posthog/posthog"
    assert generation_input.repository_integration_id == 123


@pytest.mark.usefixtures("settings")
async def test_proactive_enrichment_continues_without_repository_consent(team, user, settings) -> None:
    settings.PULSE_PROACTIVE_ENABLED = True
    delivery = await _create_proactive_delivery(team, user)
    await sync_to_async(update_proactive_config)(
        team_id=team.id,
        subscription_id=delivery.subscription_id,
        enabled=True,
        allow_public_web_research=True,
        create_draft_pr=True,
        repository="posthog/posthog",
    )
    inputs = GenerateAIReportInputs(subscription_id=delivery.subscription_id, delivery_id=delivery.id)
    generate_appendix = AsyncMock(
        return_value=RecommendationAppendixDTO(
            status="failed", recommendations=(), citations=(), failure_code="timeout"
        )
    )

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.posthoganalytics.feature_enabled",
            return_value=True,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.is_team_over_ai_credit_budget",
            return_value=False,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities.resolve_draft_repository_binding",
            return_value=None,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.ai_subscription.activities._generate_recommendation_appendix",
            generate_appendix,
        ),
    ):
        await enrich_ai_subscription_report(inputs)

    assert generate_appendix.call_args.kwargs["input"].repository is None
