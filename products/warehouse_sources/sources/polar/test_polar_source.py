from collections.abc import Iterable
from typing import Any, Optional, cast

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.polar import polar as polar_module
from products.warehouse_sources.sources.polar._config import PolarSourceConfig
from products.warehouse_sources.sources.polar.polar import NO_READABLE_SCOPE_MESSAGE
from products.warehouse_sources.sources.polar.settings import ENDPOINTS
from products.warehouse_sources.sources.polar.source import INVALID_TOKEN_MESSAGE, PolarSource
from products.warehouse_sources.sources.sdk import DEFAULT_RETRY
from products.warehouse_sources.sources.sdk.testing import error_message_matches

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
    @parameterized.expand(
        [
            ("connect_invalid_token", None, [401] * len(ENDPOINTS), False, INVALID_TOKEN_MESSAGE),
            ("connect_no_readable_scope", None, [403] * len(ENDPOINTS), False, NO_READABLE_SCOPE_MESSAGE),
            ("connect_one_readable_scope_is_enough", None, [403, 403, 200], True, None),
            (
                "connect_forbidden_then_invalid_token",
                None,
                [403] + [401] * (len(ENDPOINTS) - 1),
                False,
                INVALID_TOKEN_MESSAGE,
            ),
            (
                "table_missing_its_scope",
                "orders",
                [403],
                False,
                "Your Polar Organization Access Token can't read orders. "
                "Create a token with the orders:read scope, then reconnect.",
            ),
            ("table_invalid_token", "orders", [401], False, INVALID_TOKEN_MESSAGE),
        ]
    )
    def test_maps_probe_failures_to_actionable_messages(
        self,
        _name: str,
        schema_name: Optional[str],
        statuses: list[int],
        expected_ok: bool,
        expected_error: Optional[str],
    ) -> None:
        session = MagicMock()
        session.request.side_effect = [_FakeResponse(status) for status in statuses]
        with patch.object(polar_module, "_get_polar_session", return_value=session):
            ok, error = PolarSource().validate_credentials(
                PolarSourceConfig(polar_api_key="polar_oat_test"), team_id=1, schema_name=schema_name
            )
        assert ok is expected_ok
        assert error == expected_error


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
