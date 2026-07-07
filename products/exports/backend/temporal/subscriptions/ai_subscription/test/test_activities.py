from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import (
    _load_snapshot,
    _persist_ai_report,
    _report_diagnostic_counts,
    _snapshot_diagnostic_counts,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    QueryStepDiagnostic,
)
from products.exports.backend.temporal.subscriptions.types import (
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_SNAPSHOT_KEY,
)
from products.product_analytics.backend.models.insight import Insight

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
        },
        {
            "description": "reliability",
            "hogql": "SELECT bad",
            "ok": False,
            "error_type": "ResolutionError",
            "human_readable_error": None,
        },
    ]
    # The generating prompt is captured so the delivery is reproducible and the viewer can show it.
    assert snapshot[AI_REPORT_PROMPT_SNAPSHOT_KEY] == "weekly adoption + reliability report"


@pytest.mark.parametrize("prompt", [None, ""])
async def test_persist_ai_report_omits_blank_prompt(team, user, prompt) -> None:
    # A non-AI sub passes prompt=None and a cleared prompt passes ""; neither should write the key
    # (so the viewer doesn't render an empty "prompt at time of generation" block).
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(markdown="# report", diagnostics=()),
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
        assert _report_diagnostic_counts(result) == (expected_failed, expected_total, expected_types)

    def test_distinct_error_types_are_sorted_and_deduped(self):
        result = AiReportResult(
            markdown="report",
            diagnostics=(
                QueryStepDiagnostic(description="a", hogql="x", ok=False, error_type="ResolutionError"),
                QueryStepDiagnostic(description="b", hogql="y", ok=False, error_type="ExposedHogQLError"),
                QueryStepDiagnostic(description="c", hogql="z", ok=False, error_type="ResolutionError"),
            ),
        )
        assert _report_diagnostic_counts(result) == (3, 3, ["ExposedHogQLError", "ResolutionError"])


# On Temporal redispatch the report is already persisted, so the failure shape is read back from the
# snapshot rather than recomputed — the persist -> load -> count round-trip must match what was written.
async def test_snapshot_diagnostic_counts_reads_persisted_failure_shape(team, user) -> None:
    delivery = await _create_delivery(team, user)
    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="report",
            diagnostics=(
                QueryStepDiagnostic(description="ok step", hogql="SELECT 1", ok=True, error_type=None),
                QueryStepDiagnostic(description="bad step", hogql="SELECT bad", ok=False, error_type="ResolutionError"),
            ),
        ),
        prompt=None,
    )

    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == (1, 2, ["ResolutionError"])


async def test_snapshot_diagnostic_counts_handles_missing_diagnostics(team, user) -> None:
    delivery = await _create_delivery(team, user)
    # Empty content_snapshot (nothing persisted yet) and a fully-missing snapshot both report nothing failed.
    assert _snapshot_diagnostic_counts(await _load_snapshot(delivery.id)) == (0, 0, [])
    assert _snapshot_diagnostic_counts(None) == (0, 0, [])
