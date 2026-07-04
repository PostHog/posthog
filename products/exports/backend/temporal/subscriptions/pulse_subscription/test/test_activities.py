from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.pulse_subscription.activities import (
    PULSE_BRIEF_ID_SNAPSHOT_KEY,
    PULSE_BRIEF_REPORT_SNAPSHOT_KEY,
    mark_pulse_brief_generation_skipped,
    prepare_pulse_brief_subscription,
    render_pulse_brief_for_delivery,
)
from products.exports.backend.temporal.subscriptions.pulse_subscription.delivery import QUIET_BRIEF_NOTE
from products.exports.backend.temporal.subscriptions.types import (
    MarkPulseBriefSkippedInputs,
    PreparePulseBriefInputs,
    RenderPulseBriefInputs,
)
from products.pulse.backend.models import BriefConfig, ProductBrief

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

_DISABLED_EMAIL = "ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription"


@sync_to_async
def _set_ai_consent(team, approved: bool) -> None:
    team.organization.is_ai_data_processing_approved = approved
    team.organization.save(update_fields=["is_ai_data_processing_approved"])


@sync_to_async
def _create_config(team, **kwargs) -> BriefConfig:
    return BriefConfig.objects.for_team(team.id).create(team=team, name="Growth focus", **kwargs)


@sync_to_async
def _create_pulse_subscription(team, user, config_id) -> Subscription:
    return Subscription.objects.create(
        team=team,
        created_by=user,
        pulse_brief_config_id=config_id,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="pulse@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )


@sync_to_async
def _create_delivery(subscription) -> SubscriptionDelivery:
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=subscription.team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot={},
    )


@sync_to_async
def _snapshot(delivery_id) -> dict:
    return SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)


@sync_to_async
def _brief_count(team) -> int:
    return ProductBrief.objects.for_team(team.id).count()


@sync_to_async
def _get_brief(team, brief_id) -> ProductBrief:
    return ProductBrief.objects.for_team(team.id).get(id=brief_id)


@sync_to_async
def _create_brief(team, user, **kwargs) -> ProductBrief:
    return ProductBrief.objects.for_team(team.id).create(
        team_id=team.id,
        created_by=user,
        trigger=ProductBrief.Trigger.SCHEDULED,
        **kwargs,
    )


async def test_prepare_creates_scheduled_brief_and_is_idempotent(team, user) -> None:
    await _set_ai_consent(team, True)
    config = await _create_config(team)
    subscription = await _create_pulse_subscription(team, user, config.id)
    delivery = await _create_delivery(subscription)
    inputs = PreparePulseBriefInputs(subscription_id=subscription.id, delivery_id=delivery.id)

    first = await ActivityEnvironment().run(prepare_pulse_brief_subscription, inputs)
    second = await ActivityEnvironment().run(prepare_pulse_brief_subscription, inputs)

    assert not first.aborted
    assert first.config_id == str(config.id)
    assert first.period_days == 7  # weekly cadence → 7-day window
    assert second.brief_id == first.brief_id, "activity retry must reuse the brief, not mint a duplicate"
    assert await _brief_count(team) == 1
    brief = await _get_brief(team, first.brief_id)
    assert brief.trigger == ProductBrief.Trigger.SCHEDULED
    assert brief.status == ProductBrief.Status.GENERATING
    snapshot = await _snapshot(delivery.id)
    assert snapshot[PULSE_BRIEF_ID_SNAPSHOT_KEY] == first.brief_id


@pytest.mark.parametrize(
    "name,consent,config_kwargs,delete_config",
    [
        ("consent_revoked", False, {}, False),
        ("config_disabled", True, {"enabled": False}, False),
        ("config_deleted", True, {}, True),
    ],
)
async def test_prepare_aborts_and_auto_disables_on_terminal_state(
    team, user, name: str, consent: bool, config_kwargs: dict, delete_config: bool
) -> None:
    await _set_ai_consent(team, consent)
    config = await _create_config(team, **config_kwargs)
    subscription = await _create_pulse_subscription(team, user, config.id)
    if delete_config:
        await sync_to_async(config.delete)()
    delivery = await _create_delivery(subscription)

    with patch(_DISABLED_EMAIL):
        result = await ActivityEnvironment().run(
            prepare_pulse_brief_subscription,
            PreparePulseBriefInputs(subscription_id=subscription.id, delivery_id=delivery.id),
        )

    assert result.aborted
    assert result.recipient_results and result.recipient_results[0].status == "failed"
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.enabled is False, "terminal states must auto-disable so the sub stops re-firing"
    assert await _brief_count(team) == 0


@pytest.mark.parametrize(
    "name,status,expected_deliverable",
    [
        ("ready", ProductBrief.Status.READY, True),
        ("quiet", ProductBrief.Status.QUIET, True),
        ("failed", ProductBrief.Status.FAILED, False),
        ("still_generating", ProductBrief.Status.GENERATING, False),
    ],
)
async def test_render_by_brief_status(team, user, name: str, status: str, expected_deliverable: bool) -> None:
    config = await _create_config(team)
    subscription = await _create_pulse_subscription(team, user, config.id)
    delivery = await _create_delivery(subscription)
    brief = await _create_brief(
        team,
        user,
        config=config,
        status=status,
        sections=[{"title": "What happened", "markdown": "Conversion dropped.", "citations": ["insight:abc"]}],
    )

    result = await ActivityEnvironment().run(
        render_pulse_brief_for_delivery,
        RenderPulseBriefInputs(
            subscription_id=subscription.id, team_id=team.id, brief_id=str(brief.id), delivery_id=delivery.id
        ),
    )

    assert result.deliverable is expected_deliverable
    snapshot = await _snapshot(delivery.id)
    if status == ProductBrief.Status.READY:
        assert "## What happened" in snapshot[PULSE_BRIEF_REPORT_SNAPSHOT_KEY]
    elif status == ProductBrief.Status.QUIET:
        assert snapshot[PULSE_BRIEF_REPORT_SNAPSHOT_KEY] == QUIET_BRIEF_NOTE
    else:
        assert PULSE_BRIEF_REPORT_SNAPSHOT_KEY not in snapshot, "a failed brief must never be rendered for delivery"


async def test_mark_generation_skipped_only_touches_generating_briefs(team, user) -> None:
    generating = await _create_brief(team, user, status=ProductBrief.Status.GENERATING)
    ready = await _create_brief(team, user, status=ProductBrief.Status.READY)

    for brief in (generating, ready):
        await ActivityEnvironment().run(
            mark_pulse_brief_generation_skipped,
            MarkPulseBriefSkippedInputs(team_id=team.id, brief_id=str(brief.id)),
        )

    assert (await _get_brief(team, generating.id)).status == ProductBrief.Status.FAILED
    assert (await _get_brief(team, ready.id)).status == ProductBrief.Status.READY, (
        "a brief the concurrent run completed must not be clobbered"
    )
