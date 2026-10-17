from typing import Literal

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.netsuite import (
    NetSuiteAuthMethodConfig,
    NetSuiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import NetSuiteProbeResult
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.source import NetSuiteSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.source"
DENIED = NetSuiteProbeResult(error="Your NetSuite role can't read the currency table.", record_denied=True)
UNAUTHORIZED = NetSuiteProbeResult(error="NetSuite rejected the credentials.")


def _config(selection: Literal["oauth2", "tba"] = "tba", **fields: str) -> NetSuiteSourceConfig:
    fields = fields or {"consumer_key": "ck", "consumer_secret": "cs", "token_id": "t", "token_secret": "s"}
    return NetSuiteSourceConfig(
        account_id="1234567", auth_method=NetSuiteAuthMethodConfig(selection=selection, **fields)
    )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("create_accepts_record_denied", None, DENIED, (True, None)),
            ("create_rejects_bad_credentials", None, UNAUTHORIZED, (False, UNAUTHORIZED.error)),
            ("schema_rejects_record_denied", "customer", DENIED, (False, DENIED.error)),
            ("schema_ok", "customer", NetSuiteProbeResult(), (True, None)),
        ]
    )
    def test_probe_result_mapping(
        self, _name: str, schema_name: str | None, result: NetSuiteProbeResult, expected: tuple[bool, str | None]
    ) -> None:
        with mock.patch(f"{MODULE}.NetSuiteClient"), mock.patch(f"{MODULE}.probe", return_value=result) as probe:
            assert NetSuiteSource().validate_credentials(_config(), team_id=1, schema_name=schema_name) == expected
        assert probe.call_args.args[1] == (schema_name or "currency")

    def test_unknown_schema_is_rejected_without_a_request(self) -> None:
        with mock.patch(f"{MODULE}.NetSuiteClient") as client:
            valid, error = NetSuiteSource().validate_credentials(_config(), team_id=1, schema_name="nope")
        assert not valid and error == "NetSuite has no table named nope"
        client.assert_not_called()

    @parameterized.expand(
        [
            ("oauth2_missing_key", "oauth2", {"client_id": "c", "certificate_id": "k"}, "private key"),
            ("tba_missing_secret", "tba", {"consumer_key": "ck", "token_id": "t"}, "token secret"),
        ]
    )
    def test_missing_credentials_name_the_fields(
        self, _name: str, selection: Literal["oauth2", "tba"], fields: dict[str, str], expected: str
    ) -> None:
        valid, error = NetSuiteSource().validate_credentials(_config(selection, **fields), team_id=1)
        assert not valid and error is not None and expected in error

    def test_invalid_account_id_is_rejected(self) -> None:
        config = NetSuiteSourceConfig(account_id="evil.example.com", auth_method=_config().auth_method)
        valid, error = NetSuiteSource().validate_credentials(config, team_id=1)
        assert not valid and error is not None and error.startswith("Invalid NetSuite account ID")


class TestEndpointPermissions:
    def test_only_record_denials_are_reported(self) -> None:
        results = {"customer": DENIED, "vendor": UNAUTHORIZED, "item": NetSuiteProbeResult()}
        with (
            mock.patch(f"{MODULE}.NetSuiteClient"),
            mock.patch(f"{MODULE}.probe", side_effect=lambda _client, table: results[table]),
        ):
            permissions = NetSuiteSource().get_endpoint_permissions(_config(), 1, ["customer", "vendor", "item"])

        assert permissions == {"customer": DENIED.error, "vendor": None, "item": None}
