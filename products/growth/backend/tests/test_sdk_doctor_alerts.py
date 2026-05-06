from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from django.test import SimpleTestCase

from products.growth.backend.sdk_doctor_alerts import (
    SDK_DOCTOR_ALERT_EVENT,
    alert_cooldown_key,
    emit_sdk_doctor_alert_event,
    report_to_event_payload,
)
from products.growth.backend.sdk_health import compute_sdk_health

NOW = datetime(2026, 4, 21, tzinfo=UTC)


def _days_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def _healthy_data() -> dict:
    return {
        "web": {
            "latest_version": "1.5.0",
            "usage": [
                {
                    "lib_version": "1.5.0",
                    "count": 100,
                    "max_timestamp": NOW.isoformat(),
                    "is_latest": True,
                    "release_date": _days_ago(3),
                }
            ],
        }
    }


def _single_outdated_data() -> dict:
    return {
        "web": {
            "latest_version": "1.5.0",
            "usage": [
                {
                    "lib_version": "1.5.0",
                    "count": 100,
                    "max_timestamp": NOW.isoformat(),
                    "is_latest": True,
                    "release_date": _days_ago(3),
                }
            ],
        },
        "posthog-python": {
            "latest_version": "5.0.0",
            "usage": [
                {
                    "lib_version": "1.0.0",
                    "count": 100,
                    "max_timestamp": NOW.isoformat(),
                    "is_latest": False,
                    "release_date": _days_ago(200),
                }
            ],
        },
    }


def _critically_outdated_data() -> dict:
    return {
        "posthog-node": {
            "latest_version": "5.0.0",
            "usage": [
                {
                    "lib_version": "1.0.0",
                    "count": 100,
                    "max_timestamp": NOW.isoformat(),
                    "is_latest": False,
                    "release_date": _days_ago(200),
                }
            ],
        },
        "posthog-python": {
            "latest_version": "5.0.0",
            "usage": [
                {
                    "lib_version": "1.0.0",
                    "count": 100,
                    "max_timestamp": NOW.isoformat(),
                    "is_latest": False,
                    "release_date": _days_ago(200),
                }
            ],
        },
    }


class FakeRedis:
    def __init__(self):
        self.store: dict[bytes | str, bytes] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


class TestEmitSdkDoctorAlertEvent(SimpleTestCase):
    def setUp(self):
        self.fake_redis = FakeRedis()
        self.redis_patch = patch(
            "products.growth.backend.sdk_doctor_alerts.get_client",
            return_value=self.fake_redis,
        )
        self.redis_patch.start()
        self.addCleanup(self.redis_patch.stop)

    def test_skips_when_report_is_healthy(self):
        report = compute_sdk_health(_healthy_data(), now=NOW)
        assert report.overall_health == "healthy"

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            fired = emit_sdk_doctor_alert_event(team_id=42, report=report)

        assert fired is False
        produce.assert_not_called()

    def test_emits_when_single_sdk_outdated(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)
        assert report.overall_health == "needs_attention"
        assert report.needs_updating_count == 1

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            fired = emit_sdk_doctor_alert_event(team_id=42, report=report)

        assert fired is True
        produce.assert_called_once()
        _, kwargs = produce.call_args
        assert kwargs["team_id"] == 42
        event_arg = kwargs["event"]
        assert event_arg.event == SDK_DOCTOR_ALERT_EVENT
        assert event_arg.distinct_id == "team_42"
        props = event_arg.properties
        assert props["needs_updating_count"] == 1
        assert props["overall_health"] == "needs_attention"
        assert len(props["outdated_sdks"]) == 1
        assert props["outdated_sdks"][0]["sdk_type"] == "posthog-python"

    def test_emits_when_team_critically_outdated(self):
        report = compute_sdk_health(_critically_outdated_data(), now=NOW)
        assert report.health == "danger"
        assert report.overall_health == "needs_attention"

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            fired = emit_sdk_doctor_alert_event(team_id=42, report=report)

        assert fired is True
        props = produce.call_args.kwargs["event"].properties
        assert props["health"] == "danger"
        assert len(props["outdated_sdks"]) == 2

    def test_respects_cooldown(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            first = emit_sdk_doctor_alert_event(team_id=42, report=report)
            second = emit_sdk_doctor_alert_event(team_id=42, report=report)

        assert first is True
        assert second is False
        assert produce.call_count == 1
        assert alert_cooldown_key(42) in self.fake_redis.store

    def test_force_bypasses_cooldown(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)
        self.fake_redis.store[alert_cooldown_key(42)] = b"1"

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            fired = emit_sdk_doctor_alert_event(team_id=42, report=report, force=True)

        assert fired is True
        produce.assert_called_once()

    def test_cooldown_is_per_team(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)

        with patch("products.growth.backend.sdk_doctor_alerts.produce_internal_event") as produce:
            fired_a = emit_sdk_doctor_alert_event(team_id=1, report=report)
            fired_b = emit_sdk_doctor_alert_event(team_id=2, report=report)

        assert fired_a is True
        assert fired_b is True
        assert produce.call_count == 2

    def test_produce_failure_does_not_set_cooldown(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)

        with (
            patch(
                "products.growth.backend.sdk_doctor_alerts.produce_internal_event",
                side_effect=RuntimeError("kafka down"),
            ),
            patch("products.growth.backend.sdk_doctor_alerts.capture_exception"),
        ):
            fired = emit_sdk_doctor_alert_event(team_id=42, report=report)

        assert fired is False
        assert alert_cooldown_key(42) not in self.fake_redis.store


class TestReportToEventPayload(SimpleTestCase):
    def test_payload_includes_expected_keys(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)
        payload = report_to_event_payload(report)

        assert set(payload.keys()) == {
            "outdated_sdks",
            "needs_updating_count",
            "team_sdk_count",
            "overall_health",
            "health",
        }
        assert payload["team_sdk_count"] == 2
        assert payload["needs_updating_count"] == 1
        assert payload["outdated_sdks"][0]["sdk_type"] == "posthog-python"
        assert payload["outdated_sdks"][0]["current_version"] == "1.0.0"
        assert payload["outdated_sdks"][0]["latest_version"] == "5.0.0"

    def test_payload_omits_healthy_sdks_from_outdated_list(self):
        report = compute_sdk_health(_single_outdated_data(), now=NOW)
        payload = report_to_event_payload(report)

        sdk_types = {sdk["sdk_type"] for sdk in payload["outdated_sdks"]}
        assert sdk_types == {"posthog-python"}
