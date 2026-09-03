from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import (
    DiagnosticCounts,
    _load_snapshot,
    _persist_ai_report,
    _report_diagnostic_counts,
    _snapshot_diagnostic_counts,
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
    AI_REPORT_SNAPSHOT_KEY,
)
from products.product_analytics.backend.facade.models import Insight

_WINDOW_END_UTC = "2026-06-25T12:00:00+00:00"

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
                    description="reliability", hogql="SELECT bad", ok=False, error_type="ResolutionError"
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
            "human_readable_error": None,
            "chart_dropped_reason": None,
        },
        {
            "description": "reliability",
            "hogql": "SELECT bad",
            "ok": False,
            "error_type": "ResolutionError",
            "human_readable_error": None,
            "chart_dropped_reason": None,
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
            ("all_ok", [True, True], 0, 2, []),
            ("partial", [True, False], 1, 2, ["ResolutionError"]),
            ("all_failed", [False, False], 2, 2, ["ResolutionError"]),
            ("none", [], 0, 0, []),
        ]
    )
    def test_counts_failures_and_distinct_error_types(
        self, _name, oks, expected_failed, expected_total, expected_types
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
        assert _report_diagnostic_counts(result) == DiagnosticCounts(
            failed_step_count=expected_failed, total_step_count=expected_total, error_types=expected_types
        )

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
        assert _report_diagnostic_counts(result) == DiagnosticCounts(
            failed_step_count=3, total_step_count=3, error_types=["ExposedHogQLError", "ResolutionError"]
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
                QueryStepDiagnostic(description="bad step", hogql="SELECT bad", ok=False, error_type="ResolutionError"),
            ),
        ),
        prompt=None,
    )

    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == DiagnosticCounts(
        failed_step_count=1, total_step_count=2, error_types=["ResolutionError"]
    )


async def test_snapshot_diagnostic_counts_handles_missing_diagnostics(team, user) -> None:
    delivery = await _create_delivery(team, user)
    # Empty content_snapshot (nothing persisted yet) and a fully-missing snapshot both report nothing failed.
    empty_counts = DiagnosticCounts(failed_step_count=0, total_step_count=0, error_types=[])
    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == empty_counts
    assert _snapshot_diagnostic_counts(None) == empty_counts
