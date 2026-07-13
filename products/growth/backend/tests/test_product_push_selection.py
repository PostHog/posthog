from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.product_intent.product_intent import ProductIntent
from posthog.models.project import Project
from posthog.products import Products
from posthog.schema_enums import ProductItemCategory

from products.growth.backend.models import ProductPushCampaign
from products.growth.backend.product_push.cadence import SKIP_RETRY_DAYS
from products.growth.backend.product_push.selection import (
    BLESSED_PRODUCT_ORDER,
    FALLBACK_PRODUCT_ORDER,
    PUSH_PRODUCT_PATHS,
    select_next_product,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


class TestSelectNextProduct(BaseTest):
    def _campaign(self, product_key: str, status: str, **kwargs) -> ProductPushCampaign:
        return ProductPushCampaign.objects.create(
            organization=self.organization, product_key=product_key, status=status, **kwargs
        )

    def test_walks_blessed_order_from_the_top(self) -> None:
        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "product_analytics"
        assert selection.scheduled_campaign is None

    def test_activated_intent_excludes_checker_product_but_unactivated_does_not(self) -> None:
        # product_analytics has an activation criterion: only an *activated* intent counts as usage.
        intent = ProductIntent.objects.create(team=self.team, product_type="product_analytics")

        selection = select_next_product(self.organization, NOW)
        assert selection is not None
        assert selection.product_key == "product_analytics"

        intent.activated_at = NOW
        intent.save()

        selection = select_next_product(self.organization, NOW)
        assert selection is not None
        assert selection.product_key == "web_analytics"

    def test_any_intent_excludes_product_without_activation_criterion(self) -> None:
        # web_analytics has no activation criterion — a bare intent row is the usage signal.
        ProductIntent.objects.create(team=self.team, product_type="product_analytics", activated_at=NOW)
        ProductIntent.objects.create(team=self.team, product_type="web_analytics")

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "session_replay"

    @parameterized.expand(
        [
            ("scheduled", ProductPushCampaign.Status.SCHEDULED, {"scheduled_for": (NOW + timedelta(days=30)).date()}),
            ("active", ProductPushCampaign.Status.ACTIVE, {"started_at": NOW - timedelta(days=5)}),
            ("adopted", ProductPushCampaign.Status.ADOPTED, {"ended_at": NOW - timedelta(days=200)}),
            ("recently_skipped", ProductPushCampaign.Status.SKIPPED, {"ended_at": NOW - timedelta(days=30)}),
            ("recently_cancelled", ProductPushCampaign.Status.CANCELLED, {"ended_at": NOW - timedelta(days=30)}),
        ]
    )
    def test_campaign_history_excludes_product_from_blessed_walk(self, _name: str, status: str, fields: dict) -> None:
        self._campaign("product_analytics", status, **fields)

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "web_analytics"

    def test_skipped_product_retries_by_blessed_position_after_cooldown(self) -> None:
        # product_analytics was skipped >SKIP_RETRY_DAYS ago: eligible again, and blessed
        # position (not never-pushed-first) decides — it beats untried web_analytics.
        self._campaign(
            "product_analytics",
            ProductPushCampaign.Status.SKIPPED,
            ended_at=NOW - timedelta(days=SKIP_RETRY_DAYS + 1),
        )

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "product_analytics"

    def test_product_used_in_a_minority_of_projects_is_still_pushed(self) -> None:
        _, second_team = Project.objects.create_with_team(
            initiating_user=None, organization=self.organization, name="second"
        )
        Project.objects.create_with_team(initiating_user=None, organization=self.organization, name="third")
        ProductIntent.objects.create(team=self.team, product_type="product_analytics", activated_at=NOW)

        selection = select_next_product(self.organization, NOW)
        assert selection is not None
        assert selection.product_key == "product_analytics"

        # A second project starts using it — now a majority (2 of 3) does, so it's excluded.
        ProductIntent.objects.create(team=second_team, product_type="product_analytics", activated_at=NOW)

        selection = select_next_product(self.organization, NOW)
        assert selection is not None
        assert selection.product_key == "web_analytics"

    def test_due_tam_rows_win_over_blessed_order_by_position(self) -> None:
        self._campaign("error_tracking", ProductPushCampaign.Status.SCHEDULED, position=1)
        self._campaign("surveys", ProductPushCampaign.Status.SCHEDULED, position=0)

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "surveys"
        assert selection.scheduled_campaign is not None
        assert selection.scheduled_campaign.product_key == "surveys"

    def test_future_dated_pin_falls_through_to_blessed_order(self) -> None:
        self._campaign("surveys", ProductPushCampaign.Status.SCHEDULED, scheduled_for=(NOW + timedelta(days=10)).date())

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key == "product_analytics"
        assert selection.scheduled_campaign is None

    def test_falls_back_to_the_random_pool_once_the_blessed_order_is_exhausted(self) -> None:
        for product_key in BLESSED_PRODUCT_ORDER:
            self._campaign(product_key.value, ProductPushCampaign.Status.ADOPTED, ended_at=NOW - timedelta(days=10))

        selection = select_next_product(self.organization, NOW)

        assert selection is not None
        assert selection.product_key in {product_key.value for product_key in FALLBACK_PRODUCT_ORDER}
        assert selection.scheduled_campaign is None

    def test_returns_none_when_every_pushable_product_is_excluded(self) -> None:
        for product_key in [*BLESSED_PRODUCT_ORDER, *FALLBACK_PRODUCT_ORDER]:
            self._campaign(product_key.value, ProductPushCampaign.Status.ADOPTED, ended_at=NOW - timedelta(days=10))

        assert select_next_product(self.organization, NOW) is None


class TestPushProductConfig(SimpleTestCase):
    def test_every_pushable_product_resolves_to_a_released_catalog_item(self) -> None:
        # Guards against catalog drift: a key that doesn't resolve (or resolves to an
        # unreleased item) would render a broken or dead-end promo card.
        catalog = {product.path: product.category for product in Products.products()}
        for product_key in [*BLESSED_PRODUCT_ORDER, *FALLBACK_PRODUCT_ORDER]:
            path = PUSH_PRODUCT_PATHS.get(product_key)
            assert path is not None, f"{product_key} has no PUSH_PRODUCT_PATHS entry"
            assert path in catalog, f"{product_key} maps to {path!r}, which is not in the product catalog"
            assert catalog[path] != ProductItemCategory.UNRELEASED, f"{product_key} maps to unreleased {path!r}"
