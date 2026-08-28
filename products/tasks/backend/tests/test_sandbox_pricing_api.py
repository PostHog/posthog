from datetime import UTC, datetime
from decimal import Decimal

from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework.test import APIClient

from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCard


class TestSandboxComputePricingAPI(SimpleTestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    def test_anonymous_request_returns_current_and_expired_rates_without_scheduled_rates(self) -> None:
        cards = (
            self._rate_card("v1", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
            self._rate_card("v2", datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)),
            self._rate_card("v3", datetime(2026, 3, 1, tzinfo=UTC), None),
        )

        with (
            patch("products.tasks.backend.logic.services.sandbox_pricing.COMPUTE_RATE_CARDS", cards),
            patch(
                "products.tasks.backend.logic.services.sandbox_pricing.timezone.now",
                return_value=datetime(2026, 2, 15, tzinfo=UTC),
            ),
        ):
            response = self.client.get("/api/code/sandbox-pricing/")

        assert response.status_code == 200
        assert response.json() == {
            "current": {
                "version": "v2",
                "effective_at": "2026-02-01T00:00:00Z",
                "expires_at": "2026-03-01T00:00:00Z",
                "cpu_core_second_usd": "0.000011",
                "memory_gib_second_usd": "0.0000021",
            },
            "history": [
                {
                    "version": "v1",
                    "effective_at": "2026-01-01T00:00:00Z",
                    "expires_at": "2026-02-01T00:00:00Z",
                    "cpu_core_second_usd": "0.000011",
                    "memory_gib_second_usd": "0.0000021",
                }
            ],
        }

    @staticmethod
    def _rate_card(version: str, effective_at: datetime, expires_at: datetime | None) -> ComputeRateCard:
        return ComputeRateCard(
            version=version,
            effective_at=effective_at,
            expires_at=expires_at,
            cpu_core_second_usd=Decimal("0.000011"),
            memory_gib_second_usd=Decimal("0.0000021"),
        )
