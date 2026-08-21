from typing import Any

import pytest
from unittest.mock import patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lambdalabs import (
    LambdaLabsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lambda_labs.source import LambdaLabsSource


class TestLambdaLabsSource:
    def test_only_audit_events_is_incremental(self) -> None:
        schemas = {s.name: s for s in LambdaLabsSource().get_schemas(LambdaLabsSourceConfig(api_key="k"), team_id=1)}

        assert schemas["audit_events"].supports_incremental is True
        assert [f["field"] for f in schemas["audit_events"].incremental_fields] == ["event_time"]

        for name, schema in schemas.items():
            if name == "audit_events":
                continue
            assert schema.supports_incremental is False, name
            assert schema.incremental_fields == [], name

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
