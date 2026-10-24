"""Tests for the managed-warehouse host exemption.

The exemption replaces a `.postwh.com` suffix test that skipped the address check on any port,
for any organization, on any subdomain. Every test here pins one of the conditions that replaced
it, because a regression in any single one re-opens the same hole:

- the host must be the organization's own control-plane host, not a name of the right shape;
- the port must be one the managed warehouse serves that source type on;
- every resolved address must be a configured ingress address;
- the check must run on the addresses the connection will actually dial.

Each test states the attack it prevents, so a later reader can tell a real regression from a
value that simply changed.
"""

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.managed_warehouse.backend.facade.api import get_managed_warehouse_target
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTarget
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    HostNotAllowedError,
    _is_managed_warehouse_host,
    check_resolved_addresses,
    pinned_host_kwargs,
    resolve_safe_host,
)

_MIXINS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"
_INGRESS_MODULE = "products.managed_warehouse.backend.managed_ingress"

# Two addresses, because the incident observed the shared load balancer answering on both.
_NLB_A = "10.1.0.1"
_NLB_B = "10.1.0.2"
_TENANT_HOST = "acme.dw.us.postwh.com"
_INGRESS_SET = (_NLB_A, _NLB_B)


def _target(host: str = _TENANT_HOST, ports: frozenset[int] = frozenset({5432})) -> ManagedWarehouseTarget:
    return ManagedWarehouseTarget(host=host, ports=ports)


class TestManagedWarehouseAccepts(SimpleTestCase):
    """`ManagedWarehouseTarget.accepts` is the whole policy, so test it without the guard."""

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_the_organizations_own_host_on_its_own_port_at_an_ingress_address_is_accepted(self) -> None:
        assert _target().accepts(_TENANT_HOST, 5432, [_NLB_A], _INGRESS_SET) is True

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_every_resolved_address_is_allowed(self) -> None:
        assert _target().accepts(_TENANT_HOST, 5432, [_NLB_A, _NLB_B], _INGRESS_SET) is True

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_neighbouring_tenant_host_is_refused(self) -> None:
        # The signal the actor used to enumerate tenants: a guessed label that still resolves
        # to the shared load balancer must not be exempted.
        assert _target().accepts("zzq7x9neg.dw.us.postwh.com", 5432, [_NLB_A], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_different_tenant_at_the_same_address_is_refused(self) -> None:
        # Both tenant names answer with the same ingress address, so the address check alone
        # cannot separate them. The host comparison is what stops one tenant reaching another.
        assert _target().accepts("globex.dw.us.postwh.com", 5432, [_NLB_A], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_port_the_source_type_is_not_served_on_is_refused(self) -> None:
        # A Postgres source must not be able to reach the gateway listener on the same address.
        assert _target().accepts(_TENANT_HOST, 443, [_NLB_A], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_missing_port_is_refused(self) -> None:
        # `None` must deny. A branch that treats it as "no port to check" restores the
        # any-port hole the exemption had.
        assert _target().accepts(_TENANT_HOST, None, [_NLB_A], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_an_address_outside_the_ingress_set_is_refused(self) -> None:
        # A dangling or taken-over `postwh.com` record answers with an address that is not ours.
        assert _target().accepts(_TENANT_HOST, 5432, ["10.0.0.7"], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_one_foreign_address_in_the_set_is_refused(self) -> None:
        # A mixed answer is the DNS-rebinding shape: one approved address to pass a check, one
        # the connection could actually reach. Every address must agree.
        assert _target().accepts(_TENANT_HOST, 5432, [_NLB_A, "10.0.0.7"], _INGRESS_SET) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_an_empty_address_set_is_refused(self) -> None:
        # An empty set is a failed lookup, not an approval.
        assert _target().accepts(_TENANT_HOST, 5432, [], _INGRESS_SET) is False

    def test_an_unconfigured_ingress_set_refuses_everything(self) -> None:
        # The fail-closed default. A deployment that has not been given the address set refuses
        # managed warehouse hosts rather than trusting the name. The caller passes the set, so an
        # empty one is the refusal, not a setting the contract reads.
        assert _target().accepts(_TENANT_HOST, 5432, [_NLB_A], ()) is False

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=_NLB_A)
    def test_an_ipv4_mapped_form_matches_its_ipv4_spelling(self) -> None:
        # The resolver can answer in either form, so a string comparison would refuse a real
        # address or, worse, accept the wrong one.
        assert _target().accepts(_TENANT_HOST, 5432, [f"::ffff:{_NLB_A}"], _INGRESS_SET) is True


class TestManagedWarehouseHostShape(SimpleTestCase):
    """The shape check is a prefilter in front of the control-plane read, not an authorization."""

    @parameterized.expand(
        [
            ("us", "US", "acme.dw.us.postwh.com", "acme.dw.eu.postwh.com"),
            ("eu", "EU", "acme.dw.eu.postwh.com", "acme.dw.us.postwh.com"),
            ("dev", "DEV", "acme.dw.dev.postwh.com", "acme.dw.us.postwh.com"),
        ]
    )
    def test_one_label_under_this_deployments_zone_has_the_shape_and_another_does_not(
        self, _name: str, deployment: str, own_zone_host: str, other_zone_host: str
    ) -> None:
        # The zone is derived from the deployment, so a host under a different environment's zone
        # must not qualify: a dev deployment must not exempt a production tenant name.
        with override_settings(CLOUD_DEPLOYMENT=deployment):
            assert _is_managed_warehouse_host(own_zone_host) is True
            assert _is_managed_warehouse_host(other_zone_host) is False

    @parameterized.expand(
        [
            ("apex", "dw.us.postwh.com"),
            ("nested", "a.b.dw.us.postwh.com"),
            ("legacy_no_dw", "acme.us.postwh.com"),
            ("suffix_only", "something.postwh.com"),
            ("trailing_dot", "acme.dw.us.postwh.com."),
            ("uppercase", "ACME.DW.US.POSTWH.COM"),
            ("host_list", "10.0.0.5,acme.dw.us.postwh.com"),
            ("host_port", "acme.dw.us.postwh.com:5432"),
            ("socket_path", "/var/run/acme.dw.us.postwh.com"),
            ("lookalike_tld", "acme.dw.us.postwh.com.evil.example"),
            ("leading_hyphen", "-acme.dw.us.postwh.com"),
            ("trailing_hyphen", "acme-.dw.us.postwh.com"),
            ("underscore", "acme_.dw.us.postwh.com"),
            ("non_ascii", "\u212a.dw.us.postwh.com"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_everything_else_fails_the_shape(self, _name: str, host: str) -> None:
        assert _is_managed_warehouse_host(host) is False


class TestManagedWarehouseExemptionInTheGuard(SimpleTestCase):
    """The guard is what an attacker reaches. These are the regression tests for the incident."""

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_guessed_tenant_label_resolving_to_the_load_balancer_is_refused(self) -> None:
        # The incident: a customer-controlled host that resolves to the managed ingress. Before
        # the fix the suffix alone exempted it, so the connector dialled the load balancer.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(
                f"{_INGRESS_MODULE}.get_managed_warehouse_target",
                return_value=_target(),
            ),
        ):
            resolution = resolve_safe_host("zzq7x9neg.dw.us.postwh.com", 999, port=5432, source_type="postgres")

        assert resolution.connect_host is None
        assert resolution.error is not None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_imds_behind_a_postwh_name_is_refused(self) -> None:
        # The prize the campaign was after: a name that answers with the instance metadata
        # address must not be exempt, however well formed it looks.
        with (
            patch(
                f"{_MIXINS_MODULE}.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("169.254.169.254", 0))],
            ),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
        ):
            resolution = resolve_safe_host("acme.dw.us.postwh.com", 999, port=5432, source_type="postgres")

        assert resolution.connect_host is None
        assert resolution.error is not None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_source_type_the_warehouse_does_not_serve_is_refused(self) -> None:
        # No managed warehouse serves MySQL, so the exemption must not be reachable from that
        # source even with a matching host, port and address.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
        ):
            resolution = resolve_safe_host("acme.dw.us.postwh.com", 999, port=3306, source_type="mysql")

        assert resolution.connect_host is None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_missing_source_type_is_refused(self) -> None:
        # A caller that forgets to name its source type loses the exemption, which is the safe
        # direction, and this is the test that stops it becoming an accidental bypass.
        with patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]):
            resolution = resolve_safe_host("acme.dw.us.postwh.com", 999, port=5432)

        assert resolution.connect_host is None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_real_managed_warehouse_host_is_pinned_to_the_ingress_address(self) -> None:
        # The exemption must still work for the customer it exists for. Pinning matters: the
        # approved address is the address dialled, so a second lookup cannot answer differently.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(
                f"{_INGRESS_MODULE}.get_managed_warehouse_target",
                return_value=_target(),
            ),
        ):
            resolution = resolve_safe_host(_TENANT_HOST, 999, port=5432, source_type="postgres")

        assert resolution.error is None
        assert resolution.addresses == (_NLB_A,)
        assert resolution.connect_host == _NLB_A

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_the_checked_addresses_are_the_addresses_returned_for_a_managed_host(self) -> None:
        # `check_resolved_addresses` is the path a client that resolves the name itself takes.
        # The addresses it approves must be the ones it hands back.
        with (
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(
                f"{_INGRESS_MODULE}.get_managed_warehouse_target",
                return_value=_target(),
            ),
        ):
            resolution = check_resolved_addresses(
                _TENANT_HOST, [_NLB_A, _NLB_B], 999, port=5432, source_type="postgres"
            )

        assert resolution.connect_host == _TENANT_HOST
        assert resolution.addresses == (_NLB_A, _NLB_B)

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_mixed_address_set_is_refused_for_a_managed_host(self) -> None:
        with (
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(
                f"{_INGRESS_MODULE}.get_managed_warehouse_target",
                return_value=_target(),
            ),
        ):
            resolution = check_resolved_addresses(
                _TENANT_HOST, [_NLB_A, "10.0.0.7"], 999, port=5432, source_type="postgres"
            )

        assert resolution.connect_host is None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_an_organization_without_a_warehouse_is_refused(self) -> None:
        # An organization that has no ready warehouse must not reach the shared ingress at all,
        # which is what stops the ingress doubling as a probing oracle.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(f"{_INGRESS_MODULE}.get_managed_warehouse_target", return_value=None),
        ):
            resolution = resolve_safe_host(_TENANT_HOST, 999, port=5432, source_type="postgres")

        assert resolution.connect_host is None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_team_that_cannot_be_resolved_to_an_organization_is_refused(self) -> None:
        # `team_id` is optional on several paths. A missing or unresolvable team must deny the
        # exemption rather than skip the ownership question.
        with patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]):
            resolution = resolve_safe_host(_TENANT_HOST, None, port=5432, source_type="postgres")

        assert resolution.connect_host is None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_control_plane_failure_denies_instead_of_raising(self) -> None:
        # A control-plane outage must not fail the connect with an unexpected exception, and must
        # not grant the exemption either.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(f"{_INGRESS_MODULE}.get_managed_warehouse_target", return_value=None),
        ):
            resolution = resolve_safe_host(_TENANT_HOST, 999, port=5432, source_type="postgres")

        assert resolution.connect_host is None
        assert resolution.error is not None

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_the_team_allowlist_still_bypasses_the_address_check(self) -> None:
        # The internal-team exemption is unchanged, and must keep working for team 2 in US.
        with patch(f"{_MIXINS_MODULE}.logger"):
            resolution = check_resolved_addresses("db.internal.example.com", [_NLB_A], team_id=2)

        assert resolution.connect_host == "db.internal.example.com"

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_managed_host_is_refused_when_the_ingress_set_is_empty(self) -> None:
        # Fail closed: shipping the code before the address set must refuse rather than trust.
        with (
            patch(f"{_MIXINS_MODULE}.socket.getaddrinfo", return_value=[(None, None, None, None, (_NLB_A, 0))]),
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(f"{_INGRESS_MODULE}.get_managed_warehouse_target", return_value=_target()),
            override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=""),
        ):
            resolution = resolve_safe_host(_TENANT_HOST, 999, port=5432, source_type="postgres")

        assert resolution.connect_host is None


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


class TestNoImportOfTheManagedWarehouseProductAtModuleLoad(SimpleTestCase):
    """The guard must not pull the control-plane read into every worker that loads it.

    `mixins` is imported when the Temporal worker starts. The product's Django app registry
    (models, apps) loads with `django.setup()` whatever this file does, so the assertion names
    the modules the guard itself could add: the presentation layer and the control-plane read.
    A module-level import of those would cost every worker and would fail at startup rather
    than at the one call site that needs them.
    """

    def test_importing_the_guard_does_not_load_the_control_plane_path(self) -> None:
        import sys
        import subprocess

        code = (
            "import os, sys, django\n"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'posthog.settings')\n"
            "django.setup()\n"
            "before = set(sys.modules)\n"
            "from products.warehouse_sources.backend.temporal.data_imports.sources.common import mixins\n"
            "added = set(sys.modules) - before\n"
            "forbidden = sorted(m for m in added if m in {\n"
            "    'products.managed_warehouse.backend.presentation.views',\n"
            "    'products.managed_warehouse.backend.presentation.hogtower',\n"
            "    'products.managed_warehouse.backend.managed_ingress',\n"
            "})\n"
            "assert not forbidden, forbidden\n"
            "print('clean')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_repo_root()), timeout=180
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "clean" in result.stdout


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[7]


class TestPinnedHostKwargsForAManagedWarehouse(SimpleTestCase):
    """libpq pairs `host` and `hostaddr` positionally, so the pin is what the driver dials.

    The exemption is only worth anything if the approved address is the address connected to.
    Handing libpq the hostname alone would let it resolve a second time, and a record that
    answers with the ingress address for the check and something else for the connect would
    slip through.
    """

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_the_hostname_keeps_sni_and_the_address_is_pinned(self) -> None:
        with (
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(f"{_INGRESS_MODULE}.get_managed_warehouse_target", return_value=_target()),
            patch(f"{_MIXINS_MODULE}.host_lookup_is_skipped", return_value=False),
            patch(
                f"{_MIXINS_MODULE}._resolve_hostaddr_with_timeout",
                return_value=[_NLB_A, _NLB_B],
            ),
        ):
            kwargs = pinned_host_kwargs(_TENANT_HOST, port=5432, connect_timeout=5, team_id=999, source_type="postgres")

        # The name is repeated once per address so libpq can pair them, and it still carries the
        # SNI and certificate name a pin to a bare address would lose.
        assert kwargs["host"] == f"{_TENANT_HOST},{_TENANT_HOST}"
        assert kwargs["hostaddr"] == f"{_NLB_A},{_NLB_B}"

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=f"{_NLB_A},{_NLB_B}")
    def test_a_managed_host_whose_lookup_fails_is_refused_rather_than_resolved_again(self) -> None:
        # An empty answer is a failed lookup. Falling back to the bare hostname would hand the
        # resolution, and the decision, back to libpq.
        with (
            patch(f"{_MIXINS_MODULE}._managed_warehouse_organization_id", return_value="org-1"),
            patch(f"{_MIXINS_MODULE}.logger"),
            patch(f"{_INGRESS_MODULE}.get_managed_warehouse_target", return_value=_target()),
            patch(f"{_MIXINS_MODULE}.host_lookup_is_skipped", return_value=False),
            patch(f"{_MIXINS_MODULE}._resolve_hostaddr_with_timeout", return_value=[]),
        ):
            with pytest.raises(HostNotAllowedError):
                pinned_host_kwargs(_TENANT_HOST, port=5432, connect_timeout=5, team_id=999, source_type="postgres")


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


class TestHostComparisonIsNormalized(SimpleTestCase):
    """A control-plane host with a capital or a trailing dot must still match.

    The guard refuses any host that is not already normalized, so it compares the normalized
    name. Comparing against the control plane's string as stored would refuse that host for as
    long as the control plane kept answering with it.
    """

    @parameterized.expand(
        [
            ("uppercase", "ACME.DW.US.POSTWH.COM"),
            ("trailing_dot", "acme.dw.us.postwh.com."),
            ("mixed", "Acme.Dw.Us.Postwh.Com."),
        ]
    )
    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=_NLB_A)
    def test_a_differently_cased_or_dotted_control_plane_host_still_matches(self, _name: str, stored: str) -> None:
        target = ManagedWarehouseTarget(host=stored, ports=frozenset({5432}))
        assert target.accepts(_TENANT_HOST, 5432, [_NLB_A], _INGRESS_SET) is True

    @override_settings(MANAGED_WAREHOUSE_INGRESS_IPS=_NLB_A)
    def test_a_genuinely_different_host_is_still_refused(self) -> None:
        # Normalization must not become a fuzzy match.
        target = ManagedWarehouseTarget(host="globex.dw.us.postwh.com", ports=frozenset({5432}))
        assert target.accepts(_TENANT_HOST, 5432, [_NLB_A], _INGRESS_SET) is False


class TestTrinoConnectPathAgreesWithValidation(SimpleTestCase):
    """A managed Trino source must not validate and then refuse every sync.

    The taken branch checked the host without a port or source type, so the exemption was
    unavailable on the connect path even when validation had just approved it.
    """

    @override_settings(CLOUD_DEPLOYMENT="US", MANAGED_WAREHOUSE_INGRESS_IPS=_NLB_A)
    def test_the_trino_connect_passes_port_and_source_type(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import TrinoImplementation

        config = _stub_trino_config(port=443)
        with patch.object(TrinoImplementation, "is_database_host_valid", return_value=(True, None)) as check:
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino.connect_trino",
                side_effect=_no_connection,
            ):
                try:
                    with TrinoImplementation().connect(config, team_id=999):
                        pass
                except _Stop:
                    pass

        check.assert_called_once()
        kwargs = check.call_args.kwargs
        assert kwargs.get("port") == 443
        assert kwargs.get("source_type") == "trino"


class _Stop(Exception):
    pass


def _no_connection(*args, **kwargs):
    raise _Stop()


def _stub_trino_config(port: int):
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import (
        TrinoAuthTypeConfig,
        TrinoSourceConfig,
    )

    return TrinoSourceConfig(
        host=_TENANT_HOST,
        port=port,
        catalog="ducklake",
        auth_type=TrinoAuthTypeConfig(user="root", selection="password", password="secret"),
        schema="main",
        use_ssl=True,
        verify_ssl=True,
    )


class TestTheRealDependenciesResolve(SimpleTestCase):
    """The guard's imports must resolve without a patch, on the real module path.

    Every other test in this file patches `_managed_warehouse_organization_id`, so a wrong
    import path inside it would pass them all and then raise an `ImportError` at the call site in
    production. These tests call the real functions.
    """

    def test_the_organization_lookup_resolves(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
            _managed_warehouse_organization_id,
        )

        # A nonexistent team must deny, not raise. The point is that the import resolves.
        assert _managed_warehouse_organization_id(2**31 - 1) is None

    def test_a_missing_team_denies(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
            _managed_warehouse_organization_id,
        )

        with patch(f"{_MIXINS_MODULE}.logger"):
            assert _managed_warehouse_organization_id(None) is None

    def test_the_domain_helper_resolves_without_the_presentation_layer(self) -> None:
        # The guard reads the zone from a dependency-free module, so a Temporal worker does not
        # import the DRF views module to learn a DNS suffix.
        from products.managed_warehouse.backend.facade.api import managed_warehouse_domain

        with override_settings(CLOUD_DEPLOYMENT="US"):
            assert managed_warehouse_domain() == "us.postwh.com"
        with override_settings(CLOUD_DEPLOYMENT="EU"):
            assert managed_warehouse_domain() == "eu.postwh.com"

    def test_the_views_helper_agrees_with_the_dependency_free_one(self) -> None:
        from products.managed_warehouse.backend.facade.api import managed_warehouse_domain as dependency_free
        from products.managed_warehouse.backend.presentation.views import managed_warehouse_domain

        with override_settings(CLOUD_DEPLOYMENT="US"):
            assert managed_warehouse_domain() == dependency_free() == "us.postwh.com"
