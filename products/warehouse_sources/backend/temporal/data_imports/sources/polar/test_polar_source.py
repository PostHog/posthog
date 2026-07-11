from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PolarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.polar import polar as polar_module
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.source import PolarSource


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def raise_for_status(self) -> None:
        if not self.ok:
            # Mirror the shape of requests' error whose str() would otherwise leak the request URL.
            raise requests.HTTPError(
                f"{self.status_code} Client Error: Unauthorized for url: https://api.polar.sh/v1/organizations/?limit=1",
                response=self,  # type: ignore[arg-type]
            )


class TestPolarValidateCredentials:
    def test_invalid_token_maps_401_without_leaking_url(self) -> None:
        session = MagicMock()
        session.request.return_value = _FakeResponse(401)
        with patch.object(polar_module, "_get_polar_session", return_value=session):
            ok, error = PolarSource().validate_credentials(PolarSourceConfig(polar_api_key="polar_oat_test"), team_id=1)
        assert ok is False
        assert error is not None
        assert "api.polar.sh" not in error
        assert "invalid or expired" in error
