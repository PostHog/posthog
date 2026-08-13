from datetime import UTC, datetime

import pytest
from unittest import mock

from products.managed_warehouse.backend.client import make_duckgres_conninfo
from products.managed_warehouse.backend.facade.contracts import ServiceCredentialConnect
from products.managed_warehouse.backend.service_credentials import ServiceCredential

_CONNECT = ServiceCredentialConnect(
    host="019740a8-ac01-0000-cad1-4626cafbc273.dw.us.postwh.com",
    port=443,
    database="ducklake",
    sslmode="require",
)


def _credential(password: str) -> ServiceCredential:
    return ServiceCredential(
        username="posthog_team_7_rw",
        password=password,
        expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
        rotated=bool(password),
        connect=_CONNECT,
    )


class TestMakeDuckgresConninfoWithServiceCredential:
    """client.make_duckgres_conninfo with a service_credential presents the
    team's canonical project_user login (CP-issued, team-scoped), NOT the
    org-root credential stored in the DuckgresServer row — and dials the
    CP-issued `connect` target, never the row's host/port/database.
    """

    @mock.patch(
        "products.managed_warehouse.backend.client.get_duckgres_config_for_org",
        side_effect=AssertionError("DuckgresServer row must not be consulted on the service-credential path"),
    )
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_uses_service_credential_and_connect_block(self, _dev, _config):
        conninfo = make_duckgres_conninfo(
            7, organization_id="org-1", service_credential=_credential("minted-plaintext")
        )

        assert "user=posthog_team_7_rw" in conninfo
        assert "password=minted-plaintext" in conninfo
        assert "host=019740a8-ac01-0000-cad1-4626cafbc273.dw.us.postwh.com" in conninfo
        assert "port=443" in conninfo
        assert "dbname=ducklake" in conninfo
        assert "sslmode=require" in conninfo

    @mock.patch(
        "products.managed_warehouse.backend.client.get_duckgres_config_for_org",
        side_effect=AssertionError("DuckgresServer row must not be consulted on the service-credential path"),
    )
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_sslmode_comes_from_connect_block(self, _dev, _config):
        connect = ServiceCredentialConnect(
            host="h.dw.us.postwh.com", port=443, database="ducklake", sslmode="verify-full"
        )
        credential = ServiceCredential(
            username="posthog_team_7_rw",
            password="minted-plaintext",
            expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
            rotated=True,
            connect=connect,
        )

        conninfo = make_duckgres_conninfo(7, organization_id="org-1", service_credential=credential)

        assert "sslmode=verify-full" in conninfo

    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_empty_password_credential_is_rejected_loudly(self, _dev):
        # A reuse-path credential (CP returned no plaintext) must fail HERE —
        # a fresh fetcher with nothing cached needs to mint with force_rotate,
        # not connect with a blank password and get a cryptic 28P01.
        with pytest.raises(RuntimeError, match="force_rotate"):
            make_duckgres_conninfo(7, organization_id="org-1", service_credential=_credential(""))

    def test_dev_mode_rejects_service_credential_loudly(self):
        with mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True):
            with pytest.raises(RuntimeError, match="dev mode"):
                make_duckgres_conninfo(7, service_credential=_credential("minted-plaintext"))
