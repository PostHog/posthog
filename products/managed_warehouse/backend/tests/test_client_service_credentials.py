from datetime import UTC, datetime

import pytest
from unittest import mock

from products.managed_warehouse.backend.client import make_duckgres_conninfo
from products.managed_warehouse.backend.service_credentials import ServiceCredential


def _credential(password: str = "minted-plaintext") -> ServiceCredential:
    return ServiceCredential(
        username="posthog_team_7_rw",
        password=password,
        expires_at=datetime(2026, 8, 11, 13, 0, tzinfo=UTC),
        rotated=bool(password),
    )


class TestMakeDuckgresConninfoWithServiceCredential:
    """client.make_duckgres_conninfo with a service_credential presents the
    team's canonical project_user login (CP-issued, team-scoped), NOT the
    org-root credential stored in the DuckgresServer row.
    """

    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    @mock.patch("products.managed_warehouse.backend.client.get_duckgres_config_for_org")
    def test_uses_service_credential_username_and_password(self, mock_config, _dev):
        mock_config.return_value = {
            "DUCKGRES_HOST": "wh.duckgres.local",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "root",
            "DUCKGRES_PASSWORD": "root-secret",
        }

        conninfo = make_duckgres_conninfo(7, organization_id="org-1", service_credential=_credential())

        assert "user=posthog_team_7_rw" in conninfo
        assert "password=minted-plaintext" in conninfo
        assert "root-secret" not in conninfo
        assert "sslmode=require" in conninfo

    @mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=False)
    @mock.patch("products.managed_warehouse.backend.client.get_duckgres_config_for_org")
    def test_empty_password_credential_is_rejected_loudly(self, mock_config, _dev):
        # A reuse-path credential (CP returned no plaintext) must fail HERE —
        # a fresh fetcher with nothing cached needs to mint with force_rotate,
        # not connect with a blank password and get a cryptic 28P01.
        mock_config.return_value = {
            "DUCKGRES_HOST": "h",
            "DUCKGRES_PORT": "5432",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "root",
            "DUCKGRES_PASSWORD": "root-secret",
        }

        with pytest.raises(RuntimeError, match="force_rotate"):
            make_duckgres_conninfo(7, organization_id="org-1", service_credential=_credential(password=""))

    def test_dev_mode_rejects_service_credential_loudly(self):
        with mock.patch("products.managed_warehouse.backend.client.is_dev_mode", return_value=True):
            with pytest.raises(RuntimeError, match="dev mode"):
                make_duckgres_conninfo(7, service_credential=_credential())
