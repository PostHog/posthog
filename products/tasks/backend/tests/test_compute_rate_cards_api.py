from datetime import UTC, datetime
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCard


class TestComputeRateCardsAPI(APIBaseTest):
    def test_returns_rates_overlapping_the_synchronized_billing_period(self) -> None:
        self.organization.usage = {"period": ["2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"]}
        self.organization.save()
        rate = ComputeRateCard(
            version="2026-07-15",
            effective_at=datetime(2026, 7, 15, tzinfo=UTC),
            expires_at=None,
            cpu_core_second_usd=Decimal("0.00001234"),
            memory_gib_second_usd=Decimal("0.00000567"),
        )

        with patch(
            "products.tasks.backend.facade.compute_rates.COMPUTE_RATE_CARDS",
            (rate,),
        ):
            response = self.client.get(f"/api/projects/{self.team.pk}/sandbox_compute_rate_cards/")

        assert response.status_code == 200
        assert response.json() == {
            "rate_cards": [
                {
                    "version": "2026-07-15",
                    "effective_at": "2026-07-15T00:00:00Z",
                    "expires_at": None,
                    "cpu_usd_per_core_second": "0.00001234",
                    "memory_usd_per_gib_second": "0.00000567",
                }
            ],
            "error": None,
        }

    def test_invalid_configuration_returns_no_rates(self) -> None:
        invalid = ComputeRateCard(
            version="invalid",
            effective_at=datetime(2026, 7, 15, tzinfo=UTC),
            expires_at=None,
            cpu_core_second_usd=Decimal("0"),
            memory_gib_second_usd=Decimal("1"),
        )

        with patch(
            "products.tasks.backend.facade.compute_rates.COMPUTE_RATE_CARDS",
            (invalid,),
        ):
            response = self.client.get(f"/api/projects/{self.team.pk}/sandbox_compute_rate_cards/")

        assert response.status_code == 200
        assert response.json() == {"rate_cards": None, "error": "invalid_configuration"}
