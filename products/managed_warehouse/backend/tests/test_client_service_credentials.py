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


def _credential(secret: str, *, credential_id: str) -> ServiceCredential:
    return ServiceCredential(
        credential_id=credential_id,
        credential_secret=secret,
        expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
        connect=_CONNECT,
    )


class TestMakeDuckgresConninfoWithStoredLogin:
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    @mock.patch("products.managed_warehouse.backend.client.get_duckgres_config_for_org")
    def test_uses_the_current_stored_server_login(self, config, _dev) -> None:
        config.return_value = {
            "DUCKGRES_HOST": "managed.example.com",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "stored-login",
            "DUCKGRES_PASSWORD": "stored-password",
        }

        conninfo = make_duckgres_conninfo(7, organization_id="org-1")

        config.assert_called_once_with("org-1")
        assert "host=managed.example.com" in conninfo
        assert "dbname=ducklake" in conninfo
        assert "user=stored-login" in conninfo
        assert "password=stored-password" in conninfo


class TestMakeDuckgresConninfoWithServiceCredential:
    """client.make_duckgres_conninfo with a service_credential dials the
    server-issued credential pair (svc_<id> + plaintext) and the CP-issued
    `connect` target — never the DuckgresServer row stored in Django.
    """

    @mock.patch(
        "products.managed_warehouse.backend.client.get_duckgres_config_for_org",
        side_effect=AssertionError("DuckgresServer row must not be consulted on the service-credential path"),
    )
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_uses_service_credential_and_connect_block(self, _dev, _config):
        conninfo = make_duckgres_conninfo(
            7,
            organization_id="org-1",
            service_credential=_credential("minted-plaintext", credential_id="svc_0123456789abcdef01234567"),
        )

        assert "user=svc_0123456789abcdef01234567" in conninfo
        assert "password=minted-plaintext" in conninfo
        assert "host=019740a8-ac01-0000-cad1-4626cafbc273.dw.us.postwh.com" in conninfo
        assert "port=443" in conninfo
        assert "dbname=ducklake" in conninfo
        assert "sslmode=require" in conninfo
        # Untagged callers still get the default so duckgres can tell them apart
        # from customer clients (psql, their own application_name).
        assert "application_name=posthog" in conninfo

    @mock.patch(
        "products.managed_warehouse.backend.client.get_duckgres_config_for_org",
        side_effect=AssertionError("DuckgresServer row must not be consulted on the service-credential path"),
    )
    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_application_name_is_forwarded_on_service_credential_path(self, _dev, _config):
        conninfo = make_duckgres_conninfo(
            7,
            organization_id="org-1",
            service_credential=_credential("minted-plaintext", credential_id="svc_0123456789abcdef01234567"),
            application_name="ducklake-register",
        )

        assert "application_name=ducklake-register" in conninfo

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
            credential_id="svc_0123456789abcdef01234567",
            credential_secret="minted-plaintext",
            expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
            connect=connect,
        )

        conninfo = make_duckgres_conninfo(7, organization_id="org-1", service_credential=credential)

        assert "sslmode=verify-full" in conninfo

    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    def test_empty_secret_credential_is_rejected_loudly(self, _dev):
        with pytest.raises(RuntimeError, match="invalid response"):
            make_duckgres_conninfo(
                7,
                organization_id="org-1",
                service_credential=_credential("", credential_id="svc_0123456789abcdef01234567"),
            )

    def test_dev_mode_rejects_service_credential_loudly(self):
        with mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True):
            with pytest.raises(RuntimeError, match="dev mode"):
                make_duckgres_conninfo(
                    7,
                    service_credential=_credential("minted-plaintext", credential_id="svc_0123456789abcdef01234567"),
                )
