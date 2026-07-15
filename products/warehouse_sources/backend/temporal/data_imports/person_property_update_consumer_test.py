import json
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.person_property_update_consumer import (
    _DEFAULT_RATE_PER_SEC,
    DLQ,
    RETRY,
    SENT,
    InvalidPersonPropertyMessage,
    PersonPropertyUpdateConsumer,
    _current_rate,
    build_capture_kwargs,
)

_SETTING = (
    "products.warehouse_sources.backend.temporal.data_imports.person_property_update_consumer.get_instance_setting"
)


class TestBuildCaptureKwargs:
    def test_maps_to_set_event_with_person_processing(self):
        kwargs = build_capture_kwargs(
            {"token": "tok", "distinct_id": 42, "properties": {"plan_tier": "pro"}, "event_source": "x"}
        )
        assert kwargs == {
            "token": "tok",
            "event_name": "$set",
            "event_source": "x",
            "distinct_id": "42",
            "properties": {"$set": {"plan_tier": "pro"}},
            "process_person_profile": True,
        }

    @parameterized.expand(
        [
            ("missing_token", {"distinct_id": "a", "properties": {"p": 1}}),
            ("missing_distinct_id", {"token": "t", "properties": {"p": 1}}),
            ("empty_properties", {"token": "t", "distinct_id": "a", "properties": {}}),
            ("non_dict_properties", {"token": "t", "distinct_id": "a", "properties": "nope"}),
            ("nan_value", {"token": "t", "distinct_id": "a", "properties": {"p": float("nan")}}),
            ("inf_value", {"token": "t", "distinct_id": "a", "properties": {"p": float("inf")}}),
            ("nested_inf_value", {"token": "t", "distinct_id": "a", "properties": {"p": {"q": float("-inf")}}}),
        ]
    )
    def test_rejects_unusable_messages(self, _name, payload):
        with pytest.raises(InvalidPersonPropertyMessage):
            build_capture_kwargs(payload)


def _capture_result(
    *, succeeded: bool, dropped: list[str] | None = None, error: dict | None = None, status_code: int | None = None
) -> MagicMock:
    return MagicMock(
        succeeded=MagicMock(return_value=succeeded), dropped=dropped or [], error=error, status_code=status_code
    )


class TestProcessRecord:
    def _consumer(self, capture_fn, dlq=None):
        # Limiter always admits, so tests never wait on a real budget.
        return PersonPropertyUpdateConsumer(
            capture_fn=capture_fn, grant_fn=lambda: True, dlq_producer=dlq or MagicMock()
        )

    def test_successful_send_commits(self):
        capture = MagicMock(return_value=_capture_result(succeeded=True))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == SENT
        assert capture.call_args.kwargs["event_name"] == "$set"
        assert capture.call_args.kwargs["process_person_profile"] is True

    def test_transient_capture_failure_is_left_for_retry(self):
        # Not succeeded and nothing dropped -> transient (exhausted retries / unaccounted): redeliver.
        capture = MagicMock(return_value=_capture_result(succeeded=False))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    def test_capture_exception_is_left_for_retry(self):
        capture = MagicMock(side_effect=RuntimeError("capture down"))
        c = self._consumer(capture)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == RETRY

    @parameterized.expand(
        [
            ("client_error_400", 400, DLQ),
            ("client_error_404", 404, DLQ),
            ("retryable_408", 408, RETRY),
            ("retryable_429", 429, RETRY),
            ("server_error_503", 503, RETRY),
            ("transport_error_0", 0, RETRY),
        ]
    )
    def test_whole_request_error_routes_by_status_code(self, _name, status_code, expected):
        # A permanent 4xx (bad/stale token, validation) is poison -> DLQ; a retryable 4xx (408/429),
        # 5xx, or transport error (status 0) is transient -> retry. Without this split a 4xx retries
        # forever and wedges the partition, or a transient 408/429 gets dropped instead of retried.
        capture = MagicMock(
            return_value=_capture_result(succeeded=False, error={"error": "x"}, status_code=status_code)
        )
        dlq = MagicMock()
        c = self._consumer(capture, dlq=dlq)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == expected

    def test_raised_client_error_goes_to_dlq(self):
        # capture may *raise* a permanent 4xx (carrying .status_code) instead of returning it; that
        # must DLQ rather than retry forever. A raise without a 4xx status_code stays transient
        # (covered by test_capture_exception_is_left_for_retry).
        exc = Exception("bad token")
        exc.status_code = 400  # type: ignore[attr-defined]
        capture = MagicMock(side_effect=exc)
        dlq = MagicMock()
        c = self._consumer(capture, dlq=dlq)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == DLQ
        dlq.produce.assert_called_once()

    def test_terminal_drop_goes_to_dlq_not_retry(self):
        # A dropped event is a permanent rejection (bad token, validation): DLQ it so it can't be
        # redelivered forever and wedge the partition.
        capture = MagicMock(return_value=_capture_result(succeeded=False, dropped=["uid"]))
        dlq = MagicMock()
        c = self._consumer(capture, dlq=dlq)
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c.process_record(value) == DLQ
        dlq.produce.assert_called_once()

    @parameterized.expand(
        [
            ("invalid_json", b"not json"),
            ("non_object_array", b"[]"),
            ("non_object_string", b'"foo"'),
            ("non_object_null", b"null"),
            ("poison_shape", json.dumps({"distinct_id": "a", "properties": {"p": 1}}).encode()),
        ]
    )
    def test_poison_messages_go_to_dlq(self, _name, value):
        capture = MagicMock()
        dlq = MagicMock()
        c = PersonPropertyUpdateConsumer(capture_fn=capture, grant_fn=lambda: True, dlq_producer=dlq)

        assert c.process_record(value) == DLQ
        dlq.produce.assert_called_once()
        capture.assert_not_called()

    def test_failed_dlq_delivery_is_retried_not_dropped(self):
        # If the DLQ write itself fails to deliver, we must not commit the source offset: return
        # RETRY so the poison message is redelivered instead of vanishing from both topics.
        capture = MagicMock()
        dlq = MagicMock()
        dlq.produce.return_value.get.side_effect = RuntimeError("delivery failed")
        c = PersonPropertyUpdateConsumer(capture_fn=capture, grant_fn=lambda: True, dlq_producer=dlq)

        assert c.process_record(b"not json") == RETRY

    def test_dlq_producer_is_resolved_once_and_reused(self):
        # A poison-heavy partition must not resolve a new producer per message; the routed singleton
        # is fetched lazily on first use and cached.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.person_property_update_consumer.get_producer"
        ) as get_producer:
            c = PersonPropertyUpdateConsumer(capture_fn=MagicMock(), grant_fn=lambda: True)
            c.process_record(b"not json")
            c.process_record(b"still not json")

        get_producer.assert_called_once()
        assert get_producer.return_value.produce.call_count == 2


class TestProcessWithRetries:
    def test_transient_failure_reprocesses_same_message_until_terminal(self):
        # A RETRY must not advance past the message (committing a later offset would skip it):
        # the same message is re-sent in place until it succeeds.
        capture = MagicMock(
            side_effect=[
                _capture_result(succeeded=False),
                _capture_result(succeeded=False),
                _capture_result(succeeded=True),
            ]
        )
        sleeps: list[float] = []
        c = PersonPropertyUpdateConsumer(
            capture_fn=capture, grant_fn=lambda: True, dlq_producer=MagicMock(), sleep=lambda s: sleeps.append(s)
        )
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c._process_with_retries(value) == SENT
        assert capture.call_count == 3
        assert len(sleeps) == 2  # slept between each retry, not after the terminal outcome

    def test_shutdown_mid_retry_stops_reprocessing_and_stays_uncommitted(self):
        # On shutdown we stop retrying and return RETRY so the offset is left uncommitted and the
        # message is redelivered on the next start rather than blocking shutdown forever.
        capture = MagicMock(return_value=_capture_result(succeeded=False))
        c = PersonPropertyUpdateConsumer(capture_fn=capture, grant_fn=lambda: True, dlq_producer=MagicMock())

        def stop_after_first(_seconds: float) -> None:
            c._shutdown = True

        c._sleep = stop_after_first
        value = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

        assert c._process_with_retries(value) == RETRY


class TestRateGate:
    _VALUE = json.dumps({"token": "t", "distinct_id": "a", "properties": {"p": 1}}).encode()

    def test_send_waits_for_the_budget_then_fires(self):
        # Denied twice, then admitted: the send waits (polling the shared budget) and only calls
        # capture once a slot frees. No message is dropped while throttled.
        grants = iter([False, False, True])
        capture = MagicMock(return_value=_capture_result(succeeded=True))
        sleeps: list[float] = []
        c = PersonPropertyUpdateConsumer(
            capture_fn=capture,
            grant_fn=lambda: next(grants),
            dlq_producer=MagicMock(),
            sleep=lambda s: sleeps.append(s),
        )

        assert c.process_record(self._VALUE) == SENT
        assert capture.call_count == 1
        assert len(sleeps) == 2  # waited once per denial before the grant

    def test_shutdown_while_throttled_leaves_message_uncommitted(self):
        # If the budget never frees and shutdown arrives, we neither send nor drop: return RETRY so
        # the offset stays uncommitted and the message is redelivered on the next start.
        capture = MagicMock()
        c = PersonPropertyUpdateConsumer(capture_fn=capture, grant_fn=lambda: False, dlq_producer=MagicMock())

        def stop_after_first(_seconds: float) -> None:
            c._shutdown = True

        c._sleep = stop_after_first

        assert c.process_record(self._VALUE) == RETRY
        capture.assert_not_called()

    def test_admitted_immediately_does_not_wait(self):
        # The happy path: budget available on the first check, so the send fires with no sleep.
        capture = MagicMock(return_value=_capture_result(succeeded=True))
        sleeps: list[float] = []
        c = PersonPropertyUpdateConsumer(
            capture_fn=capture, grant_fn=lambda: True, dlq_producer=MagicMock(), sleep=lambda s: sleeps.append(s)
        )

        assert c.process_record(self._VALUE) == SENT
        assert sleeps == []

    def test_grant_error_is_treated_as_transient_and_retried(self):
        # A grant that raises (an unexpected limiter/Redis error the limiter's own fallback didn't
        # absorb) must not crash the loop: back off and retry the acquire until it succeeds, leaving
        # the message uncommitted meanwhile. Without this it escapes and crash-loops the pod.
        raises = iter([True, True, False])  # raise on the first two acquires, then admit

        def grant() -> bool:
            if next(raises):
                raise RuntimeError("redis down")
            return True

        capture = MagicMock(return_value=_capture_result(succeeded=True))
        sleeps: list[float] = []
        c = PersonPropertyUpdateConsumer(
            capture_fn=capture, grant_fn=grant, dlq_producer=MagicMock(), sleep=lambda s: sleeps.append(s)
        )

        assert c.process_record(self._VALUE) == SENT
        assert capture.call_count == 1
        assert len(sleeps) == 2  # backed off once per grant error before the grant

    def test_reports_liveness_while_throttled(self):
        # A pod that's merely rate-limited must keep heartbeating, or its liveness probe kills it
        # mid-wait. The reporter fires on each throttled poll.
        grants = iter([False, False, True])
        capture = MagicMock(return_value=_capture_result(succeeded=True))
        heartbeats: list[int] = []
        c = PersonPropertyUpdateConsumer(
            capture_fn=capture, grant_fn=lambda: next(grants), dlq_producer=MagicMock(), sleep=lambda _s: None
        )
        c._health_reporter = lambda: heartbeats.append(1)

        assert c.process_record(self._VALUE) == SENT
        assert len(heartbeats) == 2  # one per throttled poll before the grant


class TestCurrentRate:
    @parameterized.expand([("empty", ""), ("non_numeric", "fast"), ("none", None)])
    def test_unreadable_setting_falls_back_to_default(self, _name, raw):
        # A fat-fingered constance value must not propagate a ValueError through the rate policy into
        # the consume loop and crash-loop every replica; fall back to the configured default.
        with patch(_SETTING, return_value=raw):
            assert _current_rate() == _DEFAULT_RATE_PER_SEC

    @parameterized.expand([("string_int", "250", 250.0), ("below_floor", "0.5", 1.0)])
    def test_valid_setting_is_parsed_and_floored(self, _name, raw, expected):
        with patch(_SETTING, return_value=raw):
            assert _current_rate() == expected


_MODULE = "products.warehouse_sources.backend.temporal.data_imports.person_property_update_consumer"


def _profile(security_protocol):
    return SimpleNamespace(
        hosts=["broker-1:9092", "broker-2:9092"],
        security_protocol=security_protocol,
        sasl_mechanism="PLAIN",
        sasl_user="user",
        sasl_password="pass",
    )


class TestBuildConsumerConfig:
    def test_base64_keys_force_ssl_and_install_certs(self):
        # Self-hosted cert-auth mode: the consumer must force security.protocol=SSL and merge the
        # decoded cert/key/CA paths, exactly like the shared producer — otherwise it can fall back
        # to plaintext or fail to join a TLS-secured cluster, leaking person data.
        ssl_material = {
            "security.protocol": "SSL",
            "ssl.certificate.location": "/tmp/client.crt",
            "ssl.key.location": "/tmp/client.key",
            "ssl.ca.location": "/tmp/ca.crt",
        }
        with (
            override_settings(KAFKA_BASE64_KEYS=True),
            patch(f"{_MODULE}.get_profile_settings", return_value=_profile("SASL_SSL")),
            patch(f"{_MODULE}.helper.ssl_cert_config", return_value=ssl_material) as ssl_cert_config,
        ):
            config = PersonPropertyUpdateConsumer._build_consumer_config()

        ssl_cert_config.assert_called_once()
        assert config["security.protocol"] == "SSL"
        assert config["ssl.certificate.location"] == "/tmp/client.crt"
        assert config["ssl.key.location"] == "/tmp/client.key"
        assert config["ssl.ca.location"] == "/tmp/ca.crt"
        # SSL is not a SASL protocol, so credentials must not be attached alongside the cert material.
        assert "sasl.username" not in config

    def test_sasl_ssl_profile_attaches_credentials(self):
        with (
            override_settings(KAFKA_BASE64_KEYS=False),
            patch(f"{_MODULE}.get_profile_settings", return_value=_profile("SASL_SSL")),
            patch(f"{_MODULE}.helper.ssl_cert_config") as ssl_cert_config,
        ):
            config = PersonPropertyUpdateConsumer._build_consumer_config()

        ssl_cert_config.assert_not_called()
        assert config["security.protocol"] == "SASL_SSL"
        assert config["sasl.mechanism"] == "PLAIN"
        assert config["sasl.username"] == "user"
        assert config["sasl.password"] == "pass"
        assert "ssl.certificate.location" not in config

    def test_plaintext_profile_has_no_credentials_or_certs(self):
        with (
            override_settings(KAFKA_BASE64_KEYS=False),
            patch(f"{_MODULE}.get_profile_settings", return_value=_profile(None)),
            patch(f"{_MODULE}.helper.ssl_cert_config") as ssl_cert_config,
        ):
            config = PersonPropertyUpdateConsumer._build_consumer_config()

        ssl_cert_config.assert_not_called()
        assert config["security.protocol"] == "PLAINTEXT"
        assert config["bootstrap.servers"] == "broker-1:9092,broker-2:9092"
        assert "sasl.username" not in config
        assert "ssl.certificate.location" not in config
