from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vultr import VultrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.source import VultrSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vultr.vultr import (
    VULTR_PER_PAGE,
    _redact_secrets,
    validate_credentials,
)


class TestGetResource:
    def test_per_page_is_within_vultr_max(self) -> None:
        # Vultr rejects per_page above 500.
        assert 0 < VULTR_PER_PAGE <= 500


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,schema_name,expected_valid",
        [
            pytest.param(200, None, True, id="200_create"),
            pytest.param(200, "instances", True, id="200_schema"),
            pytest.param(401, None, False, id="401_invalid_token"),
            pytest.param(401, "instances", False, id="401_invalid_token_schema"),
            # A token that 403s on both the account and the data endpoint can never sync, so it is
            # rejected even at create rather than saved as a source that fails every run.
            pytest.param(403, None, False, id="403_create_fully_blocked"),
            pytest.param(403, "instances", False, id="403_rejected_per_schema"),
            pytest.param(500, None, False, id="5xx_unexpected"),
        ],
    )
    def test_status_code_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            valid, error = validate_credentials("key", schema_name)

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    def test_create_403_accepts_subuser_token_when_data_endpoint_readable(self) -> None:
        # A sub-user token whose ACL blocks /v2/account but permits /v2/instances is usable, so a
        # create-time 403 on the account endpoint is confirmed against a real data endpoint.
        with scripted_network(
            [ScriptedResponse(status=403, json={}), ScriptedResponse(status=200, json={})]
        ) as network:
            valid, error = validate_credentials("key", None)

        assert valid is True
        assert error is None
        assert network.requests_log[-1].path == "/v2/instances"
        assert len(network.requests_log) == 2


class TestRedactSecrets:
    @pytest.mark.parametrize(
        "row,expected",
        [
            pytest.param(
                {"id": "i-1", "default_password": "hunter2", "label": "web"},
                {"id": "i-1", "label": "web"},
                id="instance_default_password",
            ),
            pytest.param(
                {"id": "db-1", "password": "s3cret", "access_key": "ak", "access_cert": "ac", "host": "h"},
                {"id": "db-1", "host": "h"},
                id="managed_database_credentials",
            ),
            pytest.param(
                # Managed databases nest read-replica objects that carry their own credentials.
                {
                    "id": "db-1",
                    "read_replicas": [{"id": "r-1", "password": "p"}],
                    "ferretdb_credentials": {"password": "p2", "user": "u"},
                },
                {"id": "db-1", "read_replicas": [{"id": "r-1"}], "ferretdb_credentials": {"user": "u"}},
                id="nested_credentials",
            ),
            pytest.param(
                {"id": "b-1", "amount": 10, "description": "invoice"},
                {"id": "b-1", "amount": 10, "description": "invoice"},
                id="no_secrets_untouched",
            ),
        ],
    )
    def test_strips_secret_fields_at_any_depth(self, row: dict[str, Any], expected: dict[str, Any]) -> None:
        assert _redact_secrets(row) == expected


class TestVultrSourceWiring:
    def test_source_redacts_rows_and_disables_sample_capture(self) -> None:
        page = {
            "instances": [{"id": "i-1", "default_password": "hunter2", "label": "web"}],
            "meta": {"links": {"next": ""}},
        }

        result = SourceDriver(VultrSource(), VultrSourceConfig(api_key="k")).run(
            "instances", [ScriptedResponse(json=page)]
        )

        # Credentials are stripped before rows reach the warehouse table.
        assert result.rows == [{"id": "i-1", "label": "web"}]
        # Raw responses carry secrets, so the source must opt out of HTTP sample capture.
        assert result.session_options[0]["capture"] is False
