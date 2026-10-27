from collections.abc import Iterable
from typing import Any, Optional, cast

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import DEFAULT_RETRY
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.polar import PolarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.polar import polar as polar_module
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.source import PolarSource

_VERSION_CASES = [
    ("legacy_v1_sends_no_header", "v1", None),
    ("2026_10_sends_header", "2026-10", "2026-10"),
    ("unpinned_resolves_to_default", None, "2026-10"),
]


class _FakeResponse:
    def __init__(self, status_code: int, body: Optional[dict] = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body

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


class TestGetPolarSession:
    def test_retries_transient_errors_instead_of_failing_the_sync_outright(self) -> None:
        # A no-retry adapter previously made a single dropped connection or 5xx during
        # pagination fail the whole sync activity instead of being absorbed here.
        session = polar_module._get_polar_session()
        assert session.adapters["https://"].max_retries is DEFAULT_RETRY


class TestPolarRetryableErrors:
    @parameterized.expand(
        [
            (
                "service_unavailable",
                "503 Server Error: Service Unavailable for url: https://api.polar.sh/v1/orders/?limit=100&page=1&sorting=created_at",
                True,
            ),
            (
                "bad_gateway",
                "502 Server Error: Bad Gateway for url: https://api.polar.sh/v1/customers/?limit=100&page=1",
                True,
            ),
            (
                "internal_server_error",
                "500 Server Error: Internal Server Error for url: https://api.polar.sh/v1/products/?limit=100&page=1",
                True,
            ),
            (
                "gateway_timeout",
                "504 Server Error: Gateway Timeout for url: https://api.polar.sh/v1/subscriptions/?limit=100&page=1",
                True,
            ),
            (
                "different_host",
                "503 Server Error: Service Unavailable for url: https://example.com/v1/orders/?limit=100&page=1",
                False,
            ),
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.polar.sh/v1/orders/?limit=100&page=1",
                False,
            ),
        ]
    )
    def test_get_retryable_errors_match_only_polar_server_errors(
        self, _name: str, error_msg: str, retryable: bool
    ) -> None:
        assert error_message_matches(error_msg, PolarSource().get_retryable_errors()) is retryable


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


class TestPolarApiVersion:
    @parameterized.expand(_VERSION_CASES)
    def test_sync_requests_send_the_pinned_version(
        self, _name: str, pin: Optional[str], expected_header: Optional[str]
    ) -> None:
        session = MagicMock()
        session.request.return_value = _FakeResponse(
            200, {"items": [{"id": "cus_1"}], "pagination": {"total_count": 1, "max_page": 1}}
        )
        inputs = MagicMock(schema_name="customers", api_version=pin)
        manager = MagicMock()
        manager.can_resume.return_value = False
        with patch.object(polar_module, "_get_polar_session", return_value=session):
            response = PolarSource().source_for_pipeline(
                PolarSourceConfig(polar_api_key="polar_oat_test"), manager, inputs
            )
            rows = list(cast(Iterable[Any], response.items()))

        assert rows == [[{"id": "cus_1"}]]
        url = session.request.call_args.args[1]
        assert url.startswith("https://api.polar.sh/v1/customers/?")
        headers = session.request.call_args.kwargs["headers"]
        assert headers.get("Polar-Version") == expected_header

    @parameterized.expand(_VERSION_CASES)
    def test_credential_probe_sends_the_pinned_version(
        self, _name: str, pin: Optional[str], expected_header: Optional[str]
    ) -> None:
        session = MagicMock()
        session.request.return_value = _FakeResponse(200)
        with patch.object(polar_module, "_get_polar_session", return_value=session):
            ok, _ = PolarSource().validate_credentials(
                PolarSourceConfig(polar_api_key="polar_oat_test"), team_id=1, api_version=pin
            )

        assert ok is True
        headers = session.request.call_args.kwargs["headers"]
        assert headers.get("Polar-Version") == expected_header
