from typing import Any

import pytest
from unittest import mock

from django.test import SimpleTestCase, override_settings

import jwt
import requests

from posthog.integration_secrets.callers import IntegrationCaller
from posthog.integration_secrets.errors import IntegrationServiceUnreachableError, SecretInRecoveryError
from posthog.jwt import PosthogJwtAudience

from products.warehouse_sources.backend.temporal.data_imports.sources.common import integration_secrets

SERVICE_SETTINGS: dict[str, Any] = {
    "INTEGRATION_SERVICE_URL": "http://integration-service.posthog.svc.cluster.local",
    "INTEGRATION_SERVICE_JWT_SECRET": "signing-key",
}

KEY = "GOOGLE_ADS_DEVELOPER_TOKEN"
FLAG = "posthog.integration_secrets.client.posthoganalytics.feature_enabled"


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def _body(value: str) -> dict[str, Any]:
    return {
        "secrets": {KEY: {"state": "steady", "value": value, "version_id": "v1", "fetched_at": "now"}},
        "missing": [],
    }


class TestSessionProperties(SimpleTestCase):
    """Two properties of the session that are cheap to lose and expensive to have lost."""

    # The response body on this path is the credential in plaintext. Sample capture stores request
    # and response bodies in Redis for later inspection, and the name-based scrubbers can't
    # recognise a value they've never seen — so capture must be off at the adapter, not filtered
    # afterwards.
    def test_http_sample_capture_is_disabled(self) -> None:
        session = integration_secrets._build_session()
        adapters = [session.get_adapter("https://x"), session.get_adapter("http://x")]
        assert adapters, "expected tracked adapters to be mounted"
        for adapter in adapters:
            assert adapter._capture is False

    # The service is an internal in-cluster address. Warehouse traffic otherwise goes through the
    # Smokescreen egress proxy, which re-resolves each hop and blocks internal hosts — right for a
    # customer's API, and the exact wrong thing here: every credential read would be handed to a
    # proxy whose job is to refuse it.
    def test_the_egress_proxy_is_bypassed(self) -> None:
        assert integration_secrets._build_session().trust_env is False

    # No cache means no last known good, so a retry here only delays a failure Temporal already
    # retries with backoff. Matches the shared internal session, whose adapter also doesn't retry.
    def test_the_transport_does_not_retry(self) -> None:
        session = integration_secrets._build_session()
        assert session.get_adapter("https://x").max_retries.total == 0


@override_settings(**SERVICE_SETTINGS)
class TestHelper(SimpleTestCase):
    def setUp(self) -> None:
        flag = mock.patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    @staticmethod
    def _patched_post(payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return mock.patch.object(
            integration_secrets._session,
            "post",
            return_value=_FakeResponse(payload or _body("token")),
            **kwargs,
        )

    # Attribution is what the service writes to its audit log, so "who read this credential" is
    # only answerable if every warehouse read carries the same caller. Pinning it here means a new
    # source can't label its reads as something else by copying the wrong line.
    def test_every_read_is_attributed_to_warehouse_sources(self) -> None:
        with self._patched_post() as post:
            assert integration_secrets.get_secret(KEY) == "token"

        token = post.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(
            token,
            "signing-key",
            algorithms=["HS256"],
            audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
        )
        assert claims["caller"] == str(IntegrationCaller.WAREHOUSE_SOURCES)
        assert claims["keys"] == [KEY]

    def test_several_keys_resolve_in_one_request(self) -> None:
        keys = [KEY, "GOOGLE_ADS_APP_CLIENT_ID"]
        payload = {
            "secrets": {
                k: {"state": "steady", "value": f"v-{k}", "version_id": "v1", "fetched_at": "now"} for k in keys
            },
            "missing": [],
        }
        with self._patched_post(payload) as post:
            assert integration_secrets.get_secrets(keys) == {k: f"v-{k}" for k in keys}
        assert post.call_count == 1

    def test_a_rotation_exposes_both_values(self) -> None:
        payload = {
            "secrets": {
                KEY: {
                    "state": "rotating",
                    "value": "live",
                    "previous": "staged",
                    "version_id": "v2",
                    "fetched_at": "now",
                }
            },
            "missing": [],
        }
        with self._patched_post(payload):
            secret = integration_secrets.get_secret_with_incoming(KEY)
        assert (secret.current, secret.incoming) == ("live", "staged")

    # A key the service holds is read from the service, not from the environment it also still
    # sits in. Otherwise the migration would look complete while changing nothing.
    def test_the_service_wins_over_a_value_still_in_the_environment(self) -> None:
        with mock.patch.dict("os.environ", {KEY: "stale-copy-in-settings"}):
            with self._patched_post():
                assert integration_secrets.get_secret(KEY) == "token"


class TestServiceOff(SimpleTestCase):
    # With the service unconfigured — self-hosted, local development — the client reads the same
    # environment value the source reads today. This is what makes a migrated call site a no-op
    # until the key actually moves.
    @override_settings(INTEGRATION_SERVICE_URL=None, INTEGRATION_SERVICE_JWT_SECRET=None)
    def test_falls_back_to_the_environment_without_calling_out(self) -> None:
        with mock.patch.object(integration_secrets._session, "post", side_effect=AssertionError("called out")):
            with mock.patch.dict("os.environ", {KEY: "from-env"}):
                assert integration_secrets.get_secret(KEY) == "from-env"


class TestNoRequestsExceptionEscapes(SimpleTestCase):
    @override_settings(**SERVICE_SETTINGS)
    def test_transport_failure_is_typed(self) -> None:
        from posthog.integration_secrets.errors import IntegrationServiceUnreachableError

        with mock.patch(FLAG, return_value=True):
            with mock.patch.object(
                integration_secrets._session, "post", side_effect=requests.ConnectionError("refused")
            ):
                with pytest.raises(IntegrationServiceUnreachableError):
                    integration_secrets.get_secret(KEY)


@override_settings(**SERVICE_SETTINGS)
class TestSettingsFallbackBridge(SimpleTestCase):
    """The temporary bridge that lets call sites move before their keys do.

    Every test here is about a boundary of it. The bridge is the risky part of this migration:
    too wide and it hides a broken rollout, too narrow and it breaks eight sources on deploy.
    """

    def setUp(self) -> None:
        flag = mock.patch(FLAG, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)
        integration_secrets.SETTINGS_FALLBACK_COUNTER.clear()

    def _missing(self) -> Any:
        return mock.patch.object(
            integration_secrets._session,
            "post",
            return_value=_FakeResponse({"secrets": {}, "missing": [KEY]}),
        )

    # The whole point: the service is already live on the worker, so a call site whose key hasn't
    # moved must keep working rather than failing every sync for that source.
    def test_a_key_not_in_the_service_falls_back_to_settings(self) -> None:
        with self._missing():
            with mock.patch.dict("os.environ", {KEY: "still-in-settings"}):
                assert integration_secrets.get_secret(KEY) == "still-in-settings"

    # The fallback is what you watch to know the rollout is done, so it has to be countable and
    # name the key. A silent one would be the failure mode the client refuses to have.
    def test_the_fallback_is_counted_and_named(self) -> None:
        with self._missing():
            with mock.patch.dict("os.environ", {KEY: "still-in-settings"}):
                with mock.patch.object(integration_secrets, "logger") as log:
                    integration_secrets.get_secret(KEY)

        assert integration_secrets.SETTINGS_FALLBACK_COUNTER.labels(key=KEY, outcome="settings")._value.get() == 1
        assert log.warning.call_args.kwargs["key"] == KEY

    # Recovery means the credential is known-burned. The settings copy is the burned value, so
    # falling back would turn the kill switch into a no-op — worse than the sync stopping.
    def test_recovery_does_not_fall_back(self) -> None:
        payload = {"secrets": {KEY: {"state": "recovery", "version_id": "v1", "fetched_at": "now"}}, "missing": []}
        with mock.patch.object(integration_secrets._session, "post", return_value=_FakeResponse(payload)):
            with mock.patch.dict("os.environ", {KEY: "the-burned-value"}):
                with pytest.raises(SecretInRecoveryError):
                    integration_secrets.get_secret(KEY)

        assert integration_secrets.SETTINGS_FALLBACK_COUNTER.labels(key=KEY, outcome="settings")._value.get() == 0

    # An outage is not a rollout gap. There is no last known good here, and treating "no answer"
    # as "the key isn't there" would quietly serve stale credentials through an incident.
    def test_an_unreachable_service_does_not_fall_back(self) -> None:
        with mock.patch.object(integration_secrets._session, "post", side_effect=requests.ConnectionError("refused")):
            with mock.patch.dict("os.environ", {KEY: "still-in-settings"}):
                with pytest.raises(IntegrationServiceUnreachableError):
                    integration_secrets.get_secret(KEY)

    # Configured nowhere is the normal state of an integration a deployment doesn't use, and it
    # is what `settings.X` already returned. This migration moves where a credential comes from;
    # changing what happens when there isn't one would reach far past it — every self-hosted
    # install without this integration, and every test that never set it.
    def test_configured_nowhere_returns_what_settings_returned(self) -> None:
        with self._missing():
            with mock.patch.dict("os.environ", {}, clear=True):
                assert integration_secrets.get_secret(KEY) == ""

        counter = integration_secrets.SETTINGS_FALLBACK_COUNTER
        assert counter.labels(key=KEY, outcome="unset")._value.get() == 1
        # Not a rollout gap, so it must not be counted as one.
        assert counter.labels(key=KEY, outcome="settings")._value.get() == 0

    # A part-migrated batch is the normal state during the rollout: the batch can't say which key
    # was missing, so it re-resolves per key and each one takes the path it needs.
    def test_a_batch_with_one_missing_key_resolves_the_rest_per_key(self) -> None:
        other = "GOOGLE_ADS_APP_CLIENT_ID"
        in_service = {"state": "steady", "value": "from-service", "version_id": "v1", "fetched_at": "now"}

        def post(*args: Any, **kwargs: Any) -> Any:
            asked = _keys_asked_for(kwargs["headers"]["Authorization"])
            if KEY in asked and other in asked:
                return _FakeResponse({"secrets": {other: in_service}, "missing": [KEY]})
            if asked == [other]:
                return _FakeResponse({"secrets": {other: in_service}, "missing": []})
            return _FakeResponse({"secrets": {}, "missing": [KEY]})

        with mock.patch.object(integration_secrets._session, "post", side_effect=post):
            with mock.patch.dict("os.environ", {KEY: "still-in-settings"}):
                assert integration_secrets.get_secrets([KEY, other]) == {
                    KEY: "still-in-settings",
                    other: "from-service",
                }


def _keys_asked_for(authorization: str) -> list[str]:
    claims = jwt.decode(
        authorization.removeprefix("Bearer "),
        "signing-key",
        algorithms=["HS256"],
        audience=PosthogJwtAudience.INTEGRATION_SERVICE.value,
    )
    return list(claims["keys"])
