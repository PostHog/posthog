from typing import Any

import pytest
from unittest.mock import patch

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lambdalabs import (
    LambdaLabsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.source import LambdaLabsSource


class TestLambdaLabsSource:
    def test_get_source_config(self) -> None:
        config = LambdaLabsSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/lambda-labs"

        fields = config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        # The API key is a secret and must render as a password input.
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True

    @pytest.mark.parametrize(
        ("outcome", "expected_ok", "expected_error"),
        [
            (True, True, None),
            (False, False, "Invalid Lambda API key"),
            # A transient failure must not be reported as an invalid key — it should surface as a
            # retryable "could not reach" message so the user isn't sent to rotate a valid key.
            (
                requests.ConnectionError("boom"),
                False,
                "Could not reach Lambda to validate the API key. This may be a temporary network or service issue — please try again.",
            ),
        ],
    )
    def test_validate_credentials(self, outcome: Any, expected_ok: bool, expected_error: str | None) -> None:
        patch_kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.source.validate_lambda_labs_credentials",
            **patch_kwargs,
        ):
            ok, error = LambdaLabsSource().validate_credentials(LambdaLabsSourceConfig(api_key="k"), team_id=1)
        assert ok is expected_ok
        assert error == expected_error

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials` powers the public docs "Supported tables" section; it must
        # enumerate every endpoint with no I/O.
        tables = LambdaLabsSource().get_documented_tables()
        assert {t["name"] for t in tables} == {
            "instances",
            "instance_types",
            "filesystems",
            "images",
            "ssh_keys",
            "firewall_rulesets",
            "regions",
            "audit_events",
            "tickets",
        }
