import asyncio
from dataclasses import asdict

from temporalio.converter import default

from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    ProcessSubscriptionWorkflowInputs,
    TrackedSubscriptionInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import (
    delivery_subscription_activity_input,
    tracked_subscription_child_input,
)
from products.subscriptions.backend.pulse.temporal.inputs import ProactiveDispatchSnapshot


async def _payload(value: object) -> bytes:
    return (await default().encode([value]))[0].data


async def _decode_as_legacy_child(value: object) -> ProcessSubscriptionWorkflowInputs:
    payloads = await default().encode([value])
    return (await default().decode(payloads, [ProcessSubscriptionWorkflowInputs]))[0]


def test_legacy_child_payload_omits_absent_proactive_snapshot() -> None:
    tracked = TrackedSubscriptionInputs(subscription_id=1, team_id=2, distinct_id="distinct")
    legacy_input = asdict(tracked)
    legacy_input.pop("proactive_snapshot", None)
    legacy_input.pop("proactive_snapshot_manifest_ref", None)

    legacy_payload = asyncio.run(_payload(legacy_input))
    child_payload = asyncio.run(_payload(tracked_subscription_child_input(tracked)))

    assert child_payload == legacy_payload
    assert b"proactive_snapshot" not in child_payload


def test_enabled_child_payload_carries_immutable_proactive_snapshot() -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    tracked = TrackedSubscriptionInputs(
        subscription_id=1,
        team_id=2,
        distinct_id="distinct",
        proactive_snapshot=snapshot,
    )

    child_payload = asyncio.run(_payload(tracked_subscription_child_input(tracked)))

    assert b"proactive_snapshot" in child_payload
    assert b"pulse-config:1" in child_payload


def test_batched_manifest_child_payload_carries_only_the_manifest_reference() -> None:
    tracked = TrackedSubscriptionInputs(
        subscription_id=1,
        team_id=2,
        distinct_id="distinct",
        proactive_snapshot_manifest_ref="subscriptions/pulse/dispatch-manifests/v1/test.json",
    )

    child_payload = asyncio.run(_payload(tracked_subscription_child_input(tracked)))

    assert b"proactive_snapshot_manifest_ref" in child_payload
    assert b"dispatch-manifests/v1/test.json" in child_payload


def test_temporal_converter_ignores_the_new_manifest_field_for_an_older_child_contract() -> None:
    tracked = TrackedSubscriptionInputs(
        subscription_id=1,
        team_id=2,
        distinct_id="distinct",
        proactive_snapshot_manifest_ref="subscriptions/pulse/dispatch-manifests/v1/test.json",
    )

    decoded = asyncio.run(_decode_as_legacy_child(asdict(tracked)))

    assert decoded.subscription_id == 1
    assert decoded.team_id == 2


def test_legacy_delivery_payload_omits_absent_pulse_ledger() -> None:
    delivery = DeliverSubscriptionInputs(subscription_id=1, exported_asset_ids=[], total_insight_count=0)
    legacy_input = asdict(delivery)
    legacy_input.pop("pulse_delivery_ledger_id", None)

    legacy_payload = asyncio.run(_payload(legacy_input))
    activity_payload = asyncio.run(_payload(delivery_subscription_activity_input(delivery)))

    assert activity_payload == legacy_payload
    assert b"pulse_delivery_ledger_id" not in activity_payload
