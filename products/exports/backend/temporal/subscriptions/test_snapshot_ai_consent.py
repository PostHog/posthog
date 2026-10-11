import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import structlog
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import SnapshotInsightsInputs
from products.posthog_ai.backend.models.assistant import CoreMemory
from products.product_analytics.backend.facade.models import Insight

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def _run(inputs: SnapshotInsightsInputs):
    env = ActivityEnvironment()
    return await env.run(snapshot_subscription_insights, inputs)


@sync_to_async
def _set_ai_consent(subscription: Subscription, approved: bool) -> None:
    subscription.team.organization.is_ai_data_processing_approved = approved
    subscription.team.organization.save()


@sync_to_async
def _create_subscription(team, user, *, summary_enabled: bool = True) -> Subscription:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    return Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
        summary_enabled=summary_enabled,
    )


@sync_to_async
def _create_delivery(subscription: Subscription, content_snapshot: dict) -> SubscriptionDelivery:
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=subscription.team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot=content_snapshot,
    )


@sync_to_async
def _set_delivery_timing(delivery: SubscriptionDelivery, *, created_at: datetime, status: str) -> None:
    # created_at has auto_now_add=True, so it can only be backdated through an update(), not create().
    SubscriptionDelivery.objects.filter(pk=delivery.pk).update(created_at=created_at, status=status)


class _FakePhClient:
    """In-memory stand-in for the real PostHog client used by `ph_scoped_capture`.

    Collects every `capture(...)` kwargs dict into `self.captured` so tests can
    assert on events without hitting the network. `shutdown` is a no-op so the
    `with ph_scoped_capture()` context manager exits cleanly.
    """

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def capture(self, **kwargs) -> None:
        self.captured.append(kwargs)

    def shutdown(self) -> None:
        pass


def _install_fake_ph_client(monkeypatch) -> _FakePhClient:
    """Mock the two seams (`is_cloud` + `get_client`) that gate `ph_scoped_capture`."""
    client = _FakePhClient()
    monkeypatch.setattr("posthog.ph_client.is_cloud", lambda: True)
    monkeypatch.setattr("posthog.ph_client.get_client", lambda *a, **kw: client)
    return client


async def test_skips_summary_when_org_has_not_approved_ai(team, user):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=False)
    delivery = await _create_delivery(
        subscription,
        {"insights": [{"id": subscription.insight_id, "name": "Pageviews", "query_results": {"result": []}}]},
    )

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert result.summary_text is None
    # No-consent skips carry no user-facing notice — only over-budget skips do.
    assert result.summary_skipped_over_budget is False


async def test_runs_summary_when_org_has_approved_ai(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    called = {}

    def fake_generate(previous_states, current_states, **kwargs):
        called["ran"] = True
        return "- Pageviews is trending up"

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert called.get("ran") is True
    assert result.summary_text == "- Pageviews is trending up"


async def test_summary_compares_against_the_last_delivery_created_before_it(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    base_time = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))

    def _snapshot(insight_name: str) -> dict:
        return {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": insight_name,
                    "query_results": {"result": [{"label": insight_name, "data": [1, 2, 3]}]},
                }
            ]
        }

    d0 = await _create_delivery(subscription, _snapshot("D0 Insight"))
    d1 = await _create_delivery(subscription, _snapshot("Current Insight"))
    d2 = await _create_delivery(subscription, _snapshot("D2 Insight"))
    await _set_delivery_timing(d0, created_at=base_time, status=SubscriptionDelivery.Status.COMPLETED)
    await _set_delivery_timing(
        d1, created_at=base_time + timedelta(days=1), status=SubscriptionDelivery.Status.STARTING
    )
    # D2 is created after D1, so it must not be picked as "previous" even though it sorts
    # later than D0 by created_at.
    await _set_delivery_timing(
        d2, created_at=base_time + timedelta(days=2), status=SubscriptionDelivery.Status.COMPLETED
    )

    captured: dict = {}

    def fake_generate(previous_states, current_states, **kwargs):
        captured["previous_states"] = previous_states
        return "- summary"

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(d1.id),
        )
    )

    previous_states = captured.get("previous_states")
    assert previous_states is not None
    assert previous_states[0]["insight_name"] == "D0 Insight"


# A named function rather than a lambda because the fail-open param case needs to raise.
def _raise_quota_lookup_error(*args, **kwargs):
    raise RuntimeError("quota cache unavailable")


@pytest.mark.parametrize(
    "name,is_over_budget_impl,expect_summary_generated,expect_skipped_over_budget",
    [
        # Over budget: skip the summary entirely (generate is never called) and flag it so
        # the delivered report can show a notice.
        ("over_budget_skips", lambda *a, **kw: True, False, True),
        # Under budget: generate and deliver as normal.
        ("under_budget_runs", lambda *a, **kw: False, True, False),
        # Fail open: a quota-lookup error must not drop the summary — generate and deliver.
        ("credit_check_errors_fails_open", _raise_quota_lookup_error, True, False),
    ],
)
async def test_summary_generation_respects_ai_credit_budget(
    team, user, monkeypatch, name, is_over_budget_impl, expect_summary_generated, expect_skipped_over_budget
):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    summary_text = "- Pageviews is trending up"
    called = {}

    def fake_generate(*args, **kwargs):
        called["ran"] = True
        return summary_text

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.is_team_over_ai_credit_budget",
        is_over_budget_impl,
    )
    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    if expect_summary_generated:
        assert result.summary_text == summary_text
        assert called.get("ran") is True
    else:
        assert result.summary_text is None
        assert called.get("ran") is None
    assert result.summary_skipped_over_budget is expect_skipped_over_budget


async def test_skips_summary_when_summary_not_enabled(team, user):
    subscription = await _create_subscription(team, user, summary_enabled=False)
    await _set_ai_consent(subscription, approved=True)

    result = await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(uuid.uuid4()),
        )
    )

    assert result.summary_text is None
    # Summary-disabled skips carry no user-facing notice — only over-budget skips do.
    assert result.summary_skipped_over_budget is False


async def test_stored_prompt_guide_flows_into_summary(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await sync_to_async(Subscription.objects.filter(pk=subscription.pk).update)(summary_prompt_guide="focus on revenue")
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    seen_prompt_guides: list[str] = []

    def fake_generate(previous_states, current_states, *, prompt_guide: str = "", **kwargs):
        seen_prompt_guides.append(prompt_guide)
        return "- Pageviews is trending up"

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )
    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert seen_prompt_guides == ["focus on revenue"]


async def test_captures_analytics_event_when_summary_is_generated(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "- Pageviews is trending up",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert len(events) == 1, f"expected one capture, got {fake_client.captured}"
    event = events[0]
    assert event["distinct_id"] == str(user.distinct_id)
    props = event["properties"]
    assert props["subscription_id"] == subscription.id
    assert props["team_id"] == subscription.team_id
    assert props["delivery_id"] == str(delivery.id)
    assert props["target_type"] == subscription.target_type
    assert props["insight_count"] == 1
    assert props["image_count"] == 0
    assert props["has_previous_snapshot"] is False
    assert props["summary_text_length"] == len("- Pageviews is trending up")
    assert props["resource_type"] == "insight"


async def test_does_not_capture_analytics_event_when_summary_skipped(team, user, monkeypatch):
    subscription = await _create_subscription(team, user, summary_enabled=False)
    await _set_ai_consent(subscription, approved=True)

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(uuid.uuid4()),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert events == []


async def test_does_not_capture_analytics_event_for_empty_summary(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert events == [], "empty-string summaries should not count as generated"


async def test_captures_event_with_team_prefixed_distinct_id_when_no_creator(team, user, monkeypatch):
    """System-generated subs without a creator get a `team_<id>` distinct_id so they don't
    pollute real-user counts in product analytics.
    """
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    # Remove the creator link after creation so we hit the fallback branch.
    await sync_to_async(Subscription.objects.filter(pk=subscription.pk).update)(created_by=None)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        lambda *a, **kw: "- Pageviews is trending up",
    )

    fake_client = _install_fake_ph_client(monkeypatch)

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    events = [c for c in fake_client.captured if c.get("event") == "subscription_ai_summary_generated"]
    assert len(events) == 1
    assert events[0]["distinct_id"] == f"team_{team.id}"


@pytest.mark.parametrize(
    "stored_memory_text,expected_fragments",
    [
        pytest.param(
            "Company is PostHog.\nFlagship product is product analytics.",
            ["Company is PostHog.", "Flagship product is product analytics."],
            id="memory_present",
        ),
        pytest.param("", [], id="no_memory_row"),
    ],
)
async def test_core_memory_flows_into_change_summary(team, user, monkeypatch, stored_memory_text, expected_fragments):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    if stored_memory_text:
        await sync_to_async(CoreMemory.objects.create)(team=team, text=stored_memory_text)
    delivery = await _create_delivery(
        subscription,
        {
            "insights": [
                {
                    "id": subscription.insight_id,
                    "name": "Pageviews",
                    "query_results": {"result": [{"label": "Pageviews", "data": [1, 2, 3]}]},
                }
            ]
        },
    )

    seen_core_memory: list[str] = []

    def fake_generate(previous_states, current_states, *, core_memory_text: str = "", **kwargs):
        seen_core_memory.append(core_memory_text)
        return "- Pageviews is trending up"

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities.generate_change_summary",
        fake_generate,
    )

    await _run(
        SnapshotInsightsInputs(
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            delivery_id=str(delivery.id),
        )
    )

    assert len(seen_core_memory) == 1
    if expected_fragments:
        for fragment in expected_fragments:
            assert fragment in seen_core_memory[0]
    else:
        # No memory row → activity must pass through the empty string, not raise.
        assert seen_core_memory[0] == ""


async def test_unhandled_exception_is_logged_and_reraised(team, user, monkeypatch):
    subscription = await _create_subscription(team, user)
    await _set_ai_consent(subscription, approved=True)
    delivery = await _create_delivery(
        subscription,
        {"insights": [{"id": subscription.insight_id, "name": "Pageviews", "query_results": {"result": []}}]},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("boom while building states")

    monkeypatch.setattr(
        "products.exports.backend.temporal.subscriptions.snapshot_activities._build_states_from_content_snapshot",
        boom,
    )

    with structlog.testing.capture_logs() as captured_logs:
        with pytest.raises(RuntimeError, match="boom while building states"):
            await _run(
                SnapshotInsightsInputs(
                    subscription_id=subscription.id,
                    team_id=subscription.team_id,
                    delivery_id=str(delivery.id),
                )
            )

    failed_events = [log for log in captured_logs if log.get("event") == "snapshot_subscription_insights.failed"]
    assert len(failed_events) == 1, f"expected one .failed log, got {failed_events}"
    assert failed_events[0]["subscription_id"] == subscription.id
    assert failed_events[0]["delivery_id"] == str(delivery.id)
    assert failed_events[0]["log_level"] == "error"
