from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.managed_warehouse.backend.facade.api import get_managed_warehouse_target
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTarget

_INGRESS_MODULE = "products.managed_warehouse.backend.managed_ingress"

_NLB_A = "10.1.0.1"
_NLB_B = "10.1.0.2"
_TENANT_HOST = "acme.dw.us.postwh.com"


def _target(host: str = _TENANT_HOST, ports: frozenset[int] = frozenset({5432})) -> ManagedWarehouseTarget:
    return ManagedWarehouseTarget(host=host, ports=ports)


class TestManagedWarehouseTargetRead(SimpleTestCase):
    """The control-plane read: what it accepts as a ready target, and what it refuses."""

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_ready_warehouse_yields_its_host(self) -> None:
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache"),
        ):
            hogtower.is_configured.return_value = True
            hogtower.request.return_value = _response(
                {"org_id": "org-1", "state": "ready", "connection": {"host": _TENANT_HOST}}
            )
            target = get_managed_warehouse_target("org-1", source_type="postgres")

        assert target is not None
        assert target.host == _TENANT_HOST
        assert target.ports == frozenset({5432})

    @parameterized.expand(
        [
            ("provisioning", {"state": "provisioning", "connection": {"host": _TENANT_HOST}}),
            ("deleting", {"state": "deleting", "connection": {"host": _TENANT_HOST}}),
            ("failed", {"state": "failed", "connection": {"host": _TENANT_HOST}}),
            ("ready_without_connection", {"state": "ready"}),
            ("ready_with_blank_host", {"state": "ready", "connection": {"host": "  "}}),
        ]
    )
    def test_a_warehouse_that_is_not_ready_yields_no_target(self, _name: str, body: dict) -> None:
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache"),
        ):
            hogtower.is_configured.return_value = True
            hogtower.request.return_value = _response({"org_id": "org-1", **body})
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None

    def test_a_response_naming_another_organization_is_refused(self) -> None:
        # A control-plane bug or a misrouted proxy must never let one tenant's host answer for
        # another, which would be a cross-tenant read path.
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache"),
            patch(f"{_INGRESS_MODULE}.logger"),
        ):
            hogtower.is_configured.return_value = True
            hogtower.request.return_value = _response(
                {"org_id": "org-2", "state": "ready", "connection": {"host": "other.dw.us.postwh.com"}}
            )
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None

    def test_a_source_type_the_warehouse_does_not_serve_is_not_read(self) -> None:
        # No control-plane call at all: the mapping decides before anything leaves the process.
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache"),
        ):
            assert get_managed_warehouse_target("org-1", source_type="mysql") is None
            hogtower.request.assert_not_called()

    def test_an_unconfigured_control_plane_yields_no_target(self) -> None:
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache"),
        ):
            hogtower.is_configured.return_value = False
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None

    def test_a_control_plane_timeout_is_denied_and_cached_briefly(self) -> None:
        # An outage must not turn every connect into a full-timeout call to an already-sick
        # service, so a denial is cached for a short window.
        import requests

        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache") as cache,
            patch(f"{_INGRESS_MODULE}.logger"),
        ):
            hogtower.is_configured.return_value = True
            hogtower.request.side_effect = requests.Timeout()
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None

        assert cache.set.called

    def test_a_cached_target_is_returned_without_a_control_plane_call(self) -> None:
        cached = _target()
        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache") as cache,
        ):
            cache.get.return_value = cached
            assert get_managed_warehouse_target("org-1", source_type="postgres") is cached
            hogtower.request.assert_not_called()


def _response(body: dict):
    # The control-plane read only checks status_code and body, so a small local object stands in
    # for the translator's response type without importing the presentation layer.
    return type("Response", (), {"status_code": 200, "body": body})()


class TestDenialCacheSurvivesSerialization(SimpleTestCase):
    """A denial must be recognised after a round trip through the cache backend.

    The cache pickles its values, so an `object()` sentinel comes back as a different object and
    an identity comparison never matches. A denial that never hits is worse than no cache: every
    denied dial, and every dial during a control-plane outage, pays the full control-plane
    timeout against an already-sick service.
    """

    def test_a_denial_is_recognised_after_a_pickle_round_trip(self) -> None:
        import pickle

        from products.managed_warehouse.backend.facade.testing import NO_MANAGED_WAREHOUSE_TARGET

        serialized = pickle.dumps(NO_MANAGED_WAREHOUSE_TARGET)  # nosemgrep
        restored = pickle.loads(serialized)  # nosemgrep
        assert restored == NO_MANAGED_WAREHOUSE_TARGET

    def test_a_cached_denial_is_returned_without_a_control_plane_call(self) -> None:
        from products.managed_warehouse.backend.facade.testing import NO_MANAGED_WAREHOUSE_TARGET

        with (
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.cache") as cache,
        ):
            cache.get.return_value = NO_MANAGED_WAREHOUSE_TARGET
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None
            hogtower.request.assert_not_called()

    def test_a_cache_read_fault_denies_instead_of_raising(self) -> None:
        # The guard runs inside a connect. An exception from the cache would replace a clear
        # refusal with an opaque connection error.
        with (
            patch(f"{_INGRESS_MODULE}.cache") as cache,
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.logger"),
        ):
            cache.get.side_effect = RuntimeError("redis down")
            hogtower.is_configured.return_value = False
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None

    def test_a_cache_write_fault_still_answers_the_dial(self) -> None:
        with (
            patch(f"{_INGRESS_MODULE}.cache") as cache,
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.logger"),
        ):
            cache.get.return_value = None
            cache.set.side_effect = RuntimeError("redis down")
            hogtower.is_configured.return_value = True
            hogtower.request.return_value = _response(
                {"org_id": "org-1", "state": "ready", "connection": {"host": _TENANT_HOST}}
            )
            target = get_managed_warehouse_target("org-1", source_type="postgres")

        assert target is not None
        assert target.host == _TENANT_HOST

    def test_a_control_plane_error_the_adapter_cannot_translate_denies(self) -> None:
        with (
            patch(f"{_INGRESS_MODULE}.cache"),
            patch(f"{_INGRESS_MODULE}.hogtower") as hogtower,
            patch(f"{_INGRESS_MODULE}.logger"),
        ):
            hogtower.is_configured.return_value = True
            hogtower.request.side_effect = KeyError("unmapped route")
            assert get_managed_warehouse_target("org-1", source_type="postgres") is None
