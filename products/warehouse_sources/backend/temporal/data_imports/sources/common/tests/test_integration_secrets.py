from typing import Any

import pytest
from unittest import mock

from django.test import SimpleTestCase, override_settings

import jwt
import requests

from posthog.integration_secrets.callers import IntegrationCaller
from posthog.integration_secrets.errors import SecretMissingError
from posthog.jwt import PosthogJwtAudience

from products.warehouse_sources.backend.temporal.data_imports.sources.common import integration_secrets
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import TrackedHTTPAdapter

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
            assert isinstance(adapter, TrackedHTTPAdapter)
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
        adapter = session.get_adapter("https://x")
        assert isinstance(adapter, TrackedHTTPAdapter)
        assert adapter.max_retries.total == 0


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

    # The sequencing constraint, pinned as behaviour rather than left in a docstring: with the
    # service on, a key that isn't in it raises instead of quietly reading settings. A silent
    # fallback is how a half-finished rollout looks exactly like a finished one — so a call site
    # may only move after its key exists in the service for every environment that runs it.
    def test_a_key_not_yet_in_the_service_raises_rather_than_reading_settings(self) -> None:
        with mock.patch.dict("os.environ", {KEY: "value-still-in-the-environment"}):
            with self._patched_post({"secrets": {}, "missing": [KEY]}):
                with pytest.raises(SecretMissingError):
                    integration_secrets.get_secret(KEY)


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
