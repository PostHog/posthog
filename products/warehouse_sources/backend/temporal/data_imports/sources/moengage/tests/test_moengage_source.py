from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moengage import (
    MoEngageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.source import MoEngageSource

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.moengage.source.validate_moengage_credentials"
)


def _config(data_center: str = "01", start_date: str | None = None) -> MoEngageSourceConfig:
    # data_center is typed as a Literal of the known data centers; the invalid-value tests
    # deliberately construct configs outside it, the way a crafted PATCH payload could.
    return MoEngageSourceConfig(
        data_center=cast(Any, data_center), workspace_id="ws-1", api_key="key", start_date=start_date
    )


class TestMoEngageValidateCredentials:
    @pytest.mark.parametrize("data_center", ["01.evil.com", "evil.com/", "07", ""])
    def test_rejects_unknown_data_center_without_calling_the_api(self, data_center: str) -> None:
        # The data center is interpolated into the API hostname, so a value outside the fixed set
        # must be refused before any request carries the credential.
        with mock.patch(_VALIDATE) as mock_validate:
            is_valid, message = MoEngageSource().validate_credentials(_config(data_center=data_center), team_id=1)

        assert is_valid is False
        assert message is not None and "data center" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize("start_date", ["last week", "01/05/2025", "2025-13-40"])
    def test_rejects_malformed_start_date_without_calling_the_api(self, start_date: str) -> None:
        # An unparseable start date would otherwise pass source creation and crash every daily
        # report sync.
        with mock.patch(_VALIDATE) as mock_validate:
            is_valid, message = MoEngageSource().validate_credentials(_config(start_date=start_date), team_id=1)

        assert is_valid is False
        assert message is not None and "YYYY-MM-DD" in message
        mock_validate.assert_not_called()

    @pytest.mark.parametrize("start_date", [None, "", "2025-01-01"])
    def test_valid_config_reaches_the_credential_probe(self, start_date: str | None) -> None:
        with mock.patch(_VALIDATE, return_value=(True, None)) as mock_validate:
            is_valid, message = MoEngageSource().validate_credentials(_config(start_date=start_date), team_id=1)

        assert (is_valid, message) == (True, None)
        mock_validate.assert_called_once_with("01", "ws-1", "key")
