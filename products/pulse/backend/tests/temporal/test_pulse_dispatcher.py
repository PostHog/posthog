import datetime as dt

import pytest

from django.utils import timezone

from asgiref.sync import sync_to_async

from posthog.models.scoping import team_scope

from products.pulse.backend.models import PulseDigest, PulseDigestStatus, PulseSubscription, PulseSubscriptionFrequency
from products.pulse.backend.temporal.dispatcher import (
    build_child_workflow_id,
    build_scan_inputs,
    list_eligible_team_ids_activity,
    reconcile_stale_digests_activity,
)


async def _create_subscription(team, *, enabled: bool, frequency: PulseSubscriptionFrequency) -> None:
    @sync_to_async
    def _create() -> None:
        with team_scope(team.id, canonical=True):
            PulseSubscription.objects.create(team=team, enabled=enabled, frequency=frequency)

    await _create()


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_eligible_teams_respects_flag(monkeypatch, ateam, flag_enabled):
    await _create_subscription(ateam, enabled=True, frequency=PulseSubscriptionFrequency.WEEKLY)

    captured = {}

    def fake_feature_enabled(
        key,
        distinct_id,
        *,
        groups=None,
        group_properties=None,
        only_evaluate_locally=False,
        send_feature_flag_events=True,
    ):
        captured["key"] = key
        return flag_enabled

    monkeypatch.setattr(
        "products.pulse.backend.temporal.dispatcher.posthoganalytics.feature_enabled",
        fake_feature_enabled,
    )

    result = await list_eligible_team_ids_activity(PulseSubscriptionFrequency.WEEKLY.value, None)

    assert captured["key"] == "max-pulse"
    assert (ateam.id in result) is flag_enabled


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_eligible_teams_excludes_disabled_subscriptions(monkeypatch, ateam):
    await _create_subscription(ateam, enabled=False, frequency=PulseSubscriptionFrequency.WEEKLY)
    monkeypatch.setattr(
        "products.pulse.backend.temporal.dispatcher.posthoganalytics.feature_enabled",
        lambda *a, **k: True,
    )
    result = await list_eligible_team_ids_activity(PulseSubscriptionFrequency.WEEKLY.value, None)
    assert ateam.id not in result


class TestChildWorkflowIdentity:
    def test_child_id_is_deterministic_per_period(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        a = build_child_workflow_id(42, now, PulseSubscriptionFrequency.WEEKLY)
        b = build_child_workflow_id(42, now, PulseSubscriptionFrequency.WEEKLY)
        assert a == b == "pulse-scan-42-2026-W22"

    def test_child_id_daily(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        assert build_child_workflow_id(7, now, PulseSubscriptionFrequency.DAILY) == "pulse-scan-7-2026-05-29"

    def test_scan_inputs_carry_period(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        inputs = build_scan_inputs(42, now, PulseSubscriptionFrequency.WEEKLY)
        assert inputs.team_id == 42
        assert inputs.period_key == "2026-W22"
        # Bounds snap to the prior completed ISO week, independent of the exact run time.
        assert inputs.period_start == dt.datetime(2026, 5, 18, tzinfo=dt.UTC).isoformat()
        assert inputs.period_end == dt.datetime(2026, 5, 25, tzinfo=dt.UTC).isoformat()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_reconcile_marks_stale_generating_digests_failed(ateam):
    @sync_to_async
    def _make(*, minutes_old: int, status: PulseDigestStatus) -> str:
        now = timezone.now()
        with team_scope(ateam.id, canonical=True):
            digest = PulseDigest.objects.create(
                team=ateam,
                period_start=now - dt.timedelta(days=7),
                period_end=now,
                status=status,
            )
        # created_at is auto_now_add; backdate it via update() to simulate an old run.
        PulseDigest.objects.unscoped().filter(id=digest.id).update(created_at=now - dt.timedelta(minutes=minutes_old))
        return str(digest.id)

    stale_id = await _make(minutes_old=120, status=PulseDigestStatus.GENERATING)
    fresh_id = await _make(minutes_old=5, status=PulseDigestStatus.GENERATING)
    delivered_id = await _make(minutes_old=120, status=PulseDigestStatus.DELIVERED)

    swept = await reconcile_stale_digests_activity()
    assert swept == 1

    @sync_to_async
    def _status(digest_id: str) -> str:
        return PulseDigest.objects.unscoped().get(id=digest_id).status

    assert await _status(stale_id) == PulseDigestStatus.FAILED
    assert await _status(fresh_id) == PulseDigestStatus.GENERATING
    assert await _status(delivered_id) == PulseDigestStatus.DELIVERED
