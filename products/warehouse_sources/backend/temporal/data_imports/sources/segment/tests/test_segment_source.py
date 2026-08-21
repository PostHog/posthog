from typing import Literal, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.segment import (
    SegmentSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.source import SegmentSource


def _config(region: str = "api", api_token: str = "tok") -> SegmentSourceConfig:
    return SegmentSourceConfig(api_token=api_token, region=cast(Literal["api", "eu1"], region))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("missing_header", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            response = MagicMock()
            response.status_code = status_code
            mock_session.return_value.get.return_value = response

            ok, error = SegmentSource().validate_credentials(_config(), team_id=1)
            assert ok is expected_ok
            assert (error is None) is expected_ok

    def test_validate_credentials_network_error_is_invalid(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            ok, error = SegmentSource().validate_credentials(_config(), team_id=1)
            assert ok is False
            assert error is not None

    @parameterized.expand([("us", "api"), ("eu", "eu1")])
    def test_validate_credentials_targets_region_host(self, _name: str, region: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            response = MagicMock()
            response.status_code = 200
            mock_session.return_value.get.return_value = response

            SegmentSource().validate_credentials(_config(region=region), team_id=1)
            called_url = mock_session.return_value.get.call_args.args[0]
            assert region in called_url
