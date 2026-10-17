from uuid import uuid4

import time_machine
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.constants import FlagRequestType
from posthog.redis import get_client

from products.feature_flags.backend.flag_analytics import get_team_request_key, get_team_request_library_key
from products.feature_flags.backend.usage_export import FlagUsageExporter


@override_settings(DECIDE_BILLING_ANALYTICS_TOKEN="test-billing-token")
class TestFlagUsageExporter(SimpleTestCase):
    def setUp(self) -> None:
        self.redis_client = get_client()
        self.team_id = uuid4().int % 1_000_000_000 + 1_000_000_000
        self.ph_client = Mock(
            disabled=False,
            send=True,
            before_send=None,
            disable_geoip=True,
            super_properties={},
            api_key="test-key",
            host="https://example.com",
        )
        self.clock = time_machine.travel("2026-06-02T00:00:00Z", tick=False)
        self.clock_coordinates = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.post = self.enterContext(patch("products.feature_flags.backend.usage_export.batch_post"))
        self.capture_error = self.enterContext(
            patch(
                "products.feature_flags.backend.usage_export.capture_exception",
                side_effect=lambda error: self.fail(str(error)),
            )
        )
        self.exporter = FlagUsageExporter(self.ph_client, self.redis_client)

    def tearDown(self) -> None:
        for request_type in FlagRequestType:
            key = get_team_request_key(self.team_id, request_type)
            self.redis_client.delete(key, f"{key}:pending_export")
            for suffix in ("posthog-js", "posthog-python"):
                self.redis_client.delete(get_team_request_library_key(self.team_id, request_type, suffix))

    def seed(self, request_type: FlagRequestType = FlagRequestType.DECIDE) -> str:
        key = get_team_request_key(self.team_id, request_type)
        self.redis_client.hset(key, mapping={"14836318": 7, "14836319": 3, "14836320": 2})
        self.redis_client.hset(
            get_team_request_library_key(self.team_id, request_type, "posthog-js"),
            mapping={"14836318": 7, "14836319": 3, "14836320": 2},
        )
        return key

    @parameterized.expand(
        [(FlagRequestType.DECIDE,), (FlagRequestType.LOCAL_EVALUATION,), (FlagRequestType.REMOTE_CONFIG,)]
    )
    def test_retains_retry_identity_and_sdk_counts_until_acknowledgement(self, request_type: FlagRequestType) -> None:
        key = self.seed(request_type)
        self.post.side_effect = TimeoutError("response lost")
        self.capture_error.side_effect = None
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.flush()
        self.capture_error.assert_called_once_with(self.post.side_effect)
        first = self.post.call_args.kwargs["batch"]
        assert len(first) == 1
        assert first[0]["properties"]["count"] == 10
        assert first[0]["properties"]["sdk_breakdown"] == {"posthog-js": 10}
        assert first[0]["properties"]["$ignore_sent_at"] is True
        assert first[0]["properties"]["$geoip_disable"] is True
        assert self.redis_client.hgetall(key) == {b"14836320": b"2"}
        assert self.redis_client.hget(f"{key}:pending_export", "uuid") == first[0]["uuid"].encode()

        self.redis_client.hincrby(key, "14836318", 5)
        self.clock_coordinates.shift(24 * 60 * 60)
        self.post.side_effect = None
        restarted = FlagUsageExporter(self.ph_client, self.redis_client)
        restarted.capture_team(self.team_id, "test-team")
        restarted.flush()
        assert self.post.call_args.kwargs["batch"] == first
        assert not self.redis_client.exists(f"{key}:pending_export")
        assert self.redis_client.hget(key, "14836318") == b"5"

        restarted.capture_team(self.team_id, "test-team")
        restarted.flush()
        next_event = self.post.call_args.kwargs["batch"][0]
        assert next_event["properties"]["count"] == 7
        assert next_event["uuid"] != first[0]["uuid"]

    @parameterized.expand([("missing_token",), ("disabled",), ("send_false",)])
    def test_disabled_delivery_preserves_source_counts(self, case: str) -> None:
        key = self.seed()
        if case == "missing_token":
            self.enterContext(override_settings(DECIDE_BILLING_ANALYTICS_TOKEN=""))
        elif case == "disabled":
            self.ph_client.disabled = True
        else:
            self.ph_client.send = False
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.flush()
        assert self.redis_client.hgetall(key) == {b"14836318": b"7", b"14836319": b"3", b"14836320": b"2"}
        self.post.assert_not_called()

    @parameterized.expand([("geoip_disabled", True), ("geoip_enabled", False)])
    def test_exports_a_completed_bucket_without_waiting_for_another_request(
        self, _name: str, disable_geoip: bool
    ) -> None:
        self.ph_client.disable_geoip = disable_geoip
        key = get_team_request_key(self.team_id, FlagRequestType.DECIDE)
        self.redis_client.hset(key, "14836319", 4)
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.flush()
        assert self.post.call_args.kwargs["batch"][0]["properties"]["count"] == 4
        assert self.post.call_args.kwargs["batch"][0]["properties"].get("$geoip_disable", False) == disable_geoip
        assert not self.redis_client.exists(key)

    def test_overlapping_exporter_does_not_acknowledge_a_newer_pending_batch(self) -> None:
        key = self.seed()
        self.exporter.capture_team(self.team_id, "test-team")
        overlapping = FlagUsageExporter(self.ph_client, self.redis_client)
        overlapping.capture_team(self.team_id, "test-team")
        overlapping.flush()
        self.redis_client.hincrby(key, "14836318", 5)
        overlapping.capture_team(self.team_id, "test-team")
        new_pending = self.redis_client.hgetall(f"{key}:pending_export")
        self.exporter.flush()
        assert self.redis_client.hgetall(f"{key}:pending_export") == new_pending
        overlapping.flush()
        assert self.post.call_args.kwargs["batch"][0]["properties"]["count"] == 5

    def test_worker_failure_before_send_leaves_a_recoverable_batch(self) -> None:
        key = self.seed()
        self.exporter.capture_team(self.team_id, "test-team")
        pending_uuid = self.redis_client.hget(f"{key}:pending_export", "uuid")
        restarted = FlagUsageExporter(self.ph_client, self.redis_client)
        restarted.capture_team(self.team_id, "test-team")
        restarted.flush()
        assert self.post.call_args.kwargs["batch"][0]["uuid"].encode() == pending_uuid

    def test_capture_filter_keeps_the_pending_export_for_a_later_run(self) -> None:
        key = self.seed()
        self.ph_client.before_send = lambda event: None
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.flush()
        self.post.assert_not_called()
        assert self.redis_client.exists(f"{key}:pending_export")
        self.ph_client.before_send = None
        self.exporter.capture_team(self.team_id, "test-team")
        self.exporter.flush()
        assert self.post.call_args.kwargs["batch"][0]["properties"]["count"] == 10

    @parameterized.expand([("success", False), ("failed_first_batch", True)])
    def test_flushes_bounded_batches_and_continues_after_failure(self, _name: str, fail_first: bool) -> None:
        self.seed()
        self.capture_error.side_effect = None
        error = TimeoutError("response lost")
        self.post.side_effect = [error if fail_first else None, None]
        later_team = self.team_id + 1
        later_key = get_team_request_key(later_team, FlagRequestType.DECIDE)
        self.redis_client.hset(later_key, "14836319", 4)
        self.addCleanup(self.redis_client.delete, later_key, f"{later_key}:pending_export")
        exporter = FlagUsageExporter(self.ph_client, self.redis_client, batch_size=1)
        exporter.capture_team(self.team_id, "test-team")
        exporter.capture_team(later_team, "later-team")

        assert self.post.call_count == 2
        first, later = [call.kwargs["batch"] for call in self.post.call_args_list]
        assert len(first) == len(later) == 1
        assert later[0]["properties"]["team_id"] == later_team
        assert later[0]["properties"]["count"] == 4
        assert not self.redis_client.exists(f"{later_key}:pending_export")
        assert not exporter.pending
        key = get_team_request_key(self.team_id, FlagRequestType.DECIDE)
        if fail_first:
            self.capture_error.assert_called_once_with(error)
            assert self.redis_client.hget(f"{key}:pending_export", "uuid") == first[0]["uuid"].encode()
            self.post.side_effect = None
            restarted = FlagUsageExporter(self.ph_client, self.redis_client, batch_size=1)
            restarted.capture_team(self.team_id, "test-team")
            assert self.post.call_args.kwargs["batch"] == first
        else:
            self.capture_error.assert_not_called()
        assert not self.redis_client.exists(f"{key}:pending_export")
