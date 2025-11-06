import json
import urllib.parse
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.utils.timezone import now

import jwt
from dateutil.relativedelta import relativedelta
from requests import Response, get
from rest_framework import status

from posthog.cloud_utils import TEST_clear_instance_license_cache, get_cached_instance_license
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.enterprise.backend.api.billing import BillingUsageRequestSerializer
from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.billing.billing_types import (
    BillingPeriod,
    CustomerInfo,
    CustomerProduct,
    CustomerProductAddon,
)
from products.enterprise.backend.billing.quota_limiting import QuotaResource
from products.enterprise.backend.billing.test.test_billing_manager import create_default_products_response
from products.enterprise.backend.models.license import License


def create_usage_summary(**kwargs) -> dict[str, Any]:
    data: dict[str, Any] = {
        "period": ["2022-10-07T11:12:48", "2022-11-07T11:12:48"],
    }
    for resource in QuotaResource:
        data[resource.value] = {"limit": None, "usage": 0, "todays_usage": 0}

    data.update(kwargs)
    return data


def create_billing_response(**kwargs) -> dict[str, Any]:
    data: Any = {"license": {"type": "cloud"}}
    data.update(kwargs)
    return data


def create_missing_billing_customer(**kwargs) -> CustomerInfo:
    data = CustomerInfo(
        customer_id="cus_123",
        deactivated=False,
        custom_limits_usd={},
        has_active_subscription=False,
        current_total_amount_usd="0.00",
        products=None,
        billing_period=BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
        ),
        usage_summary=create_usage_summary(),
        free_trial_until=None,
        available_product_features=[],
    )
    data.update(kwargs)
    return data


def create_billing_customer(**kwargs) -> CustomerInfo:
    data = CustomerInfo(
        customer_id="cus_123",
        custom_limits_usd={},
        has_active_subscription=True,
        current_total_amount_usd="100.00",
        deactivated=False,
        products=[
            CustomerProduct(
                name="Product OS",
                description="Product Analytics, event pipelines, data warehousing",
                price_description=None,
                type="product_analytics",
                image_url="https://posthog.com/static/images/product-os.png",
                free_allocation=10000,
                tiers=[
                    {
                        "unit_amount_usd": "0.00",
                        "up_to": 1000000,
                        "current_amount_usd": "0.00",
                    },
                    {
                        "unit_amount_usd": "0.00045",
                        "up_to": 2000000,
                        "current_amount_usd": "0.00",
                    },
                ],
                tiered=True,
                unit_amount_usd="0.00",
                current_amount_usd="0.00",
                current_usage=0,
                usage_limit=None,
                has_exceeded_limit=False,
                percentage_usage=0,
                projected_usage=0,
                projected_amount_usd="0.00",
                projected_amount_usd_with_limit="0.00",
                usage_key="events",
                addons=[
                    CustomerProductAddon(
                        name="Addon",
                        description="Test Addon",
                        price_description=None,
                        type="addon",
                        image_url="https://posthog.com/static/images/product-os.png",
                        free_allocation=10000,
                        tiers=[
                            {
                                "unit_amount_usd": "0.00",
                                "up_to": 1000000,
                                "current_amount_usd": "0.00",
                            },
                            {
                                "unit_amount_usd": "0.0000135",
                                "up_to": 2000000,
                                "current_amount_usd": "0.00",
                            },
                        ],
                        tiered=True,
                        unit_amount_usd="0.00",
                        current_amount_usd="0.00",
                        current_usage=0,
                        usage_limit=None,
                        has_exceeded_limit=False,
                        percentage_usage=0,
                        projected_usage=0,
                        projected_amount_usd="0.00",
                        usage_key="events",
                        subscribed=True,
                    )
                ],
            )
        ],
        customer_trust_scores={
            "surveys": 15,
            "feature_flags": 15,
            "data_warehouse": 15,
            "session_replay": 15,
            "product_analytics": 15,
        },
        billing_period=BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
        ),
        usage_summary=create_usage_summary(),
        free_trial_until=None,
    )
    data.update(kwargs)
    return data


def create_billing_products_response(**kwargs) -> dict[str, list[CustomerProduct]]:
    data: Any = {
        "products": [
            CustomerProduct(
                name="Product OS",
                description="Product Analytics, event pipelines, data warehousing",
                price_description=None,
                type="events",
                image_url="https://posthog.com/static/images/product-os.png",
                free_allocation=10000,
                tiers=[
                    {
                        "unit_amount_usd": "0.00",
                        "up_to": 1000000,
                        "current_amount_usd": "0.00",
                        "current_usage": 0,
                        "flat_amount_usd": "0",
                        "projected_amount_usd": "None",
                        "projected_usage": None,
                    },
                    {
                        "unit_amount_usd": "0.00045",
                        "up_to": 2000000,
                        "current_amount_usd": "0.00",
                        "current_usage": 0,
                        "flat_amount_usd": "0",
                        "projected_amount_usd": "None",
                        "projected_usage": None,
                    },
                ],
                addons=[
                    {
                        "current_amount_usd": 0.0,
                        "current_usage": 0,
                        "description": "Test Addon",
                        "free_allocation": 10000,
                        "has_exceeded_limit": False,
                        "image_url": "https://posthog.com/static/images/product-os.png",
                        "name": "Addon",
                        "percentage_usage": 0,
                        "price_description": None,
                        "projected_amount_usd": "0.00",
                        "projected_usage": 0,
                        "subscribed": True,
                        "tiered": True,
                        "tiers": [
                            {
                                "current_amount_usd": "0.00",
                                "current_usage": 0,
                                "flat_amount_usd": "0",
                                "projected_amount_usd": "None",
                                "projected_usage": None,
                                "unit_amount_usd": "0.00",
                                "up_to": 1000000,
                            },
                            {
                                "current_amount_usd": "0.00",
                                "current_usage": 0,
                                "flat_amount_usd": "0",
                                "projected_amount_usd": "None",
                                "projected_usage": None,
                                "unit_amount_usd": "0.0000135",
                                "up_to": 2000000,
                            },
                        ],
                        "type": "events",
                        "unit_amount_usd": "0.00",
                        "usage_key": "events",
                        "usage_limit": None,
                    },
                ],
                tiered=True,
                unit_amount_usd="0.00",
                current_amount_usd=0.0,
                current_usage=0,
                usage_limit=None,
                has_exceeded_limit=False,
                percentage_usage=0,
                projected_usage=0,
                projected_amount=0,
                projected_amount_usd=0.00,
                projected_amount_usd_with_limit=0.00,
                usage_key="events",
            )
        ]
    }
    data.update(kwargs)
    return data


class TestUnlicensedBillingAPI(APIBaseTest):
    @patch("products.enterprise.backend.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_calls_the_service_without_token(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 401
                mock.json.return_value = {"detail": "Authorization is missing."}
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_default_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        assert res.json() == {
            "available_product_features": [],
            "products": create_default_products_response()["products"],
        }


class TestBillingAPI(APILicensedTest):
    def test_billing_fails_for_old_license_type(self):
        self.license.key = "test_key"
        self.license.save()
        TEST_clear_instance_license_cache()

        res = self.client.get("/api/billing")
        assert res.status_code == 404
        assert res.json()["detail"] == "Billing is not supported for this license type"

    @patch("products.enterprise.backend.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_calls_the_service_with_appropriate_token(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_billing_customer())

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()

        self.client.get("/api/billing")
        assert mock_request.call_args_list[0].args[0].endswith("/api/billing")
        token = mock_request.call_args_list[0].kwargs["headers"]["Authorization"].split(" ")[1]

        secret = self.license.key.split("::")[1]

        decoded_token = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="posthog:license-key",
            options={"verify_aud": True},
        )

        assert decoded_token == {
            "aud": "posthog:license-key",
            "distinct_id": str(self.user.distinct_id),
            "exp": 1640996100,
            "id": self.license.key.split("::")[0],
            "organization_id": str(self.organization.id),
            "organization_name": "Test",
            "organization_role": "member",
        }

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_billing_returns_if_billing_exists(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_billing_customer())

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()
        response = self.client.get("/api/billing")
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == {
            "customer_id": "cus_123",
            "customer_id": "cus_123",
            "customer_trust_scores": {
                "data_warehouse": 15,
                "feature_flags": 15,
                "product_analytics": 15,
                "session_replay": 15,
                "surveys": 15,
            },
            "license": {"plan": "cloud"},
            "available_product_features": [],
            "custom_limits_usd": {},
            "has_active_subscription": True,
            "stripe_portal_url": "http://localhost:8010/api/billing/portal",
            "current_total_amount_usd": "100.00",
            "deactivated": False,
            "products": [
                {
                    "name": "Product OS",
                    "description": "Product Analytics, event pipelines, data warehousing",
                    "price_description": None,
                    "type": "product_analytics",
                    "image_url": "https://posthog.com/static/images/product-os.png",
                    "free_allocation": 10000,
                    "tiers": [
                        {
                            "unit_amount_usd": "0.00",
                            "up_to": 1000000,
                            "current_amount_usd": "0.00",
                        },
                        {
                            "unit_amount_usd": "0.00045",
                            "up_to": 2000000,
                            "current_amount_usd": "0.00",
                        },
                    ],
                    "tiered": True,
                    "current_amount_usd": "0.00",
                    "current_usage": 0,
                    "usage_limit": None,
                    "percentage_usage": 0,
                    "has_exceeded_limit": False,
                    "unit_amount_usd": "0.00",
                    "projected_amount_usd": "0.00",
                    "projected_amount_usd_with_limit": "0.00",
                    "projected_usage": 0,
                    "usage_key": "events",
                    "addons": [
                        {
                            "current_amount_usd": "0.00",
                            "current_usage": 0,
                            "description": "Test Addon",
                            "free_allocation": 10000,
                            "has_exceeded_limit": False,
                            "image_url": "https://posthog.com/static/images/product-os.png",
                            "name": "Addon",
                            "percentage_usage": 0,
                            "price_description": None,
                            "projected_amount_usd": "0.00",
                            "projected_usage": 0,
                            "subscribed": True,
                            "tiered": True,
                            "tiers": [
                                {
                                    "current_amount_usd": "0.00",
                                    "unit_amount_usd": "0.00",
                                    "up_to": 1000000,
                                },
                                {
                                    "current_amount_usd": "0.00",
                                    "unit_amount_usd": "0.0000135",
                                    "up_to": 2000000,
                                },
                            ],
                            "type": "addon",
                            "unit_amount_usd": "0.00",
                            "usage_key": "events",
                            "usage_limit": None,
                        },
                    ],
                },
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
            },
            "usage_summary": create_usage_summary(),
            "free_trial_until": None,
        }

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_billing_returns_if_doesnt_exist(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_missing_billing_customer())
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        response = self.client.get("/api/billing")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "customer_id": "cus_123",
            "license": {"plan": "cloud"},
            "custom_limits_usd": {},
            "has_active_subscription": False,
            "available_product_features": [],
            "products": [
                {
                    "name": "Product OS",
                    "description": "Product Analytics, event pipelines, data warehousing",
                    "price_description": None,
                    "type": "events",
                    "free_allocation": 10000,
                    "tiers": [
                        {
                            "unit_amount_usd": "0.00",
                            "up_to": 1000000,
                            "current_amount_usd": "0.00",
                            "current_usage": 0,
                            "flat_amount_usd": "0",
                            "projected_amount_usd": "None",
                            "projected_usage": None,
                        },
                        {
                            "unit_amount_usd": "0.00045",
                            "up_to": 2000000,
                            "current_amount_usd": "0.00",
                            "current_usage": 0,
                            "flat_amount_usd": "0",
                            "projected_amount_usd": "None",
                            "projected_usage": None,
                        },
                    ],
                    "current_usage": 0,
                    "percentage_usage": 0,
                    "current_amount_usd": 0.0,
                    "has_exceeded_limit": False,
                    "projected_amount": 0,
                    "projected_amount_usd": 0.0,
                    "projected_amount_usd_with_limit": 0.0,
                    "projected_usage": 0,
                    "tiered": True,
                    "unit_amount_usd": "0.00",
                    "usage_limit": None,
                    "image_url": "https://posthog.com/static/images/product-os.png",
                    "percentage_usage": 0,
                    "usage_key": "events",
                    "addons": [
                        {
                            "current_amount_usd": 0.0,
                            "current_usage": 0,
                            "description": "Test Addon",
                            "free_allocation": 10000,
                            "has_exceeded_limit": False,
                            "image_url": "https://posthog.com/static/images/product-os.png",
                            "name": "Addon",
                            "percentage_usage": 0,
                            "price_description": None,
                            "projected_amount_usd": "0.00",
                            "projected_usage": 0,
                            "subscribed": True,
                            "tiered": True,
                            "tiers": [
                                {
                                    "current_amount_usd": "0.00",
                                    "current_usage": 0,
                                    "flat_amount_usd": "0",
                                    "projected_amount_usd": "None",
                                    "projected_usage": None,
                                    "unit_amount_usd": "0.00",
                                    "up_to": 1000000,
                                },
                                {
                                    "current_amount_usd": "0.00",
                                    "current_usage": 0,
                                    "flat_amount_usd": "0",
                                    "projected_amount_usd": "None",
                                    "projected_usage": None,
                                    "unit_amount_usd": "0.0000135",
                                    "up_to": 2000000,
                                },
                            ],
                            "type": "events",
                            "unit_amount_usd": "0.00",
                            "usage_key": "events",
                            "usage_limit": None,
                        },
                    ],
                }
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
            },
            "usage_summary": create_usage_summary(),
            "free_trial_until": None,
            "current_total_amount_usd": "0.00",
            "deactivated": False,
            "stripe_portal_url": "http://localhost:8010/api/billing/portal",
        }

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_billing_stores_valid_license(self, mock_request):
        self.license.delete()

        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            }
        }
        response = self.client.patch(
            "/api/billing/license",
            {
                "license": "test::test",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"success": True}
        license = License.objects.first_valid()
        assert license
        assert license.key == "test::test"
        assert license.plan == "scale"

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_billing_ignores_invalid_license(self, mock_request):
        self.license.delete()

        mock_request.return_value.status_code = 403
        mock_request.return_value.json.return_value = {}
        response = self.client.patch(
            "/api/billing/license",
            {
                "license": "test::test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "attr": "license",
            "code": "invalid_input",
            "detail": "License could not be activated. Please contact support. (BillingService status 403)",
            "type": "validation_error",
        }

    @freeze_time("2022-01-01T12:00:00Z")
    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_license_is_updated_on_billing_load(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            },
            "customer": create_billing_customer(),
        }

        assert self.license.plan == "enterprise"
        self.client.get("/api/billing")
        self.license.refresh_from_db()

        self.license.valid_until = datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        self.license.save()
        assert self.license.plan == "scale"
        TEST_clear_instance_license_cache()
        license = get_cached_instance_license()
        assert license.plan == "scale"
        assert license.valid_until == datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

        mock_request.return_value.json.return_value = {
            "license": {
                "type": "enterprise",
            },
            "customer": create_billing_customer(),
        }

        self.client.get("/api/billing")
        license = get_cached_instance_license()
        assert license.plan == "enterprise"
        # Should be extended by 30 days
        assert license.valid_until == datetime(2022, 1, 31, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_organization_available_product_features_updated_if_different(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(
                        available_product_features=[
                            {"key": "feature1", "name": "feature1"},
                            {"key": "feature2", "name": "feature2"},
                        ]
                    )
                )

            return mock

        mock_request.side_effect = mock_implementation

        self.organization.available_product_features = []
        self.organization.save()

        assert self.organization.available_product_features == []
        self.client.get("/api/billing")
        self.organization.refresh_from_db()
        assert self.organization.available_product_features == [
            {
                "key": "feature1",
                "name": "feature1",
            },
            {"key": "feature2", "name": "feature2"},
        ]

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_organization_update_usage(self, mock_request):
        self.organization.customer_id = None
        self.organization.usage = None
        self.organization.save()

        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(has_active_subscription=True),
                )
                mock.json.return_value["customer"]["usage_summary"]["events"]["usage"] = 1000
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        assert not self.organization.usage
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        self.organization.refresh_from_db()
        TestCase().assertDictEqual(
            self.organization.usage,
            create_usage_summary(events={"usage": 1000, "limit": None, "todays_usage": 0}),
        )

        self.organization.usage = {"events": {"limit": None, "usage": 1000, "todays_usage": 1100000}}
        self.organization.save()

        res = self.client.get("/api/billing")
        assert res.status_code == 200
        res_json = res.json()
        # Should update product usage to reflect today's usage
        assert res_json["products"][0]["current_usage"] == 1101000
        assert res_json["products"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["tiers"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["tiers"][1]["current_amount_usd"] == "0.00"

        assert res_json["products"][0]["addons"][0]["current_usage"] == 0
        assert res_json["products"][0]["addons"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["addons"][0]["tiers"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["addons"][0]["tiers"][1]["current_amount_usd"] == "0.00"

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_organization_usage_count_with_demo_project(self, mock_request, *args):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock | Response:
            mock = MagicMock()
            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
                return mock
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    # Set usage to none so it is calculated from scratch
                    customer=create_billing_customer(has_active_subscription=False, usage=None)
                )
                return mock
            else:
                return get(url, headers=headers, params=params)

        mock_request.side_effect = mock_implementation

        self.organization.customer_id = None
        self.organization.usage = None
        self.organization.save()
        # Create a demo project
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(Team.objects.count(), 1)
        response = self.client.post("/api/projects/", {"name": "Test", "is_demo": True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 3)

        demo_team = Team.objects.filter(is_demo=True).first()

        # We create some events for the demo project
        with self.settings(USE_TZ=False):
            distinct_id = str(uuid4())
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$demo-event",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(hours=12),
                    team=demo_team,
                )
            flush_persons_and_events()

        assert not self.organization.usage
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.usage == create_usage_summary()

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_org_trust_score_updated(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    # Set usage to none so it is calculated from scratch
                    customer=create_billing_customer(has_active_subscription=False, usage=None)
                )

            return mock

        mock_request.side_effect = mock_implementation

        self.organization.customer_id = None
        # For key values check: TRUST_SCORE_KEYS
        self.organization.customer_trust_scores = {
            "events": 0,
            "exceptions": 0,
            "recordings": 0,
            "rows_synced": 0,
            "feature_flags": 0,
            "api_queries_read_bytes": 17,
            "surveys": 0,
        }
        self.organization.save()

        res = self.client.get("/api/billing")
        assert res.status_code == 200
        self.organization.refresh_from_db()

        assert self.organization.customer_trust_scores == {
            "events": 15,
            "exceptions": 0,
            "recordings": 0,
            "rows_synced": 0,
            "feature_flags": 0,
            "api_queries_read_bytes": 17,
            "surveys": 0,
        }

    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_billing_with_supported_params(self, mock_get):
        """Test that the include_forecasting param is passed through to the billing service."""

        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 200

            if "api/billing/portal" in url:
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(has_active_subscription=True)
                )

            return mock

        mock_get.side_effect = mock_implementation

        response = self.client.get("/api/billing/?include_forecasting=true")
        assert response.status_code == 200

        # Verify the billing service was called with the correct query param
        billing_calls = [
            call
            for call in mock_get.call_args_list
            if "api/billing" in call[0][0] and "api/billing/portal" not in call[0][0]
        ]
        assert len(billing_calls) == 1
        assert billing_calls[0].kwargs["params"] == {"include_forecasting": "true"}


class TestPortalBillingAPI(APILicensedTest):
    @patch("products.enterprise.backend.api.billing.requests.get")
    def test_portal_success(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}

        response = self.client.get("/api/billing/portal")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("https://billing.stripe.com/p/session/test_1234", response.url)


class TestActivateBillingAPI(APILicensedTest):
    def test_activate_success(self):
        url = "/api/billing/activate"
        data = {"products": "product_1:plan_1,product_2:plan_2", "redirect_path": "custom/path"}

        response = self.client.get(url, data=data)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        self.assertIn("/activate", response.url)
        self.assertIn("products=product_1:plan_1,product_2:plan_2", response.url)
        url_pattern = r"redirect_uri=http://[^/]+/custom/path"
        self.assertRegex(response.url, url_pattern)

    def test_deprecated_activation_success(self):
        url = "/api/billing/activate"
        data = {"products": "product_1:plan_1,product_2:plan_2", "redirect_path": "custom/path"}

        response = self.client.get(url, data=data)
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

        self.assertIn("/activate", response.url)
        self.assertIn("products=product_1:plan_1,product_2:plan_2", response.url)
        url_pattern = r"redirect_uri=http://[^/]+/custom/path"
        self.assertRegex(response.url, url_pattern)

    def test_activate_with_default_redirect_path(self):
        url = "/api/billing/activate"
        data = {
            "products": "product_1:plan_1,product_2:plan_2",
        }

        response = self.client.get(url, data)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("products=product_1:plan_1,product_2:plan_2", response.url)
        url_pattern = r"redirect_uri=http://[^/]+/organization/billing"
        self.assertRegex(response.url, url_pattern)

    def test_activate_failure(self):
        url = "/api/billing/activate"
        data = {"none": "nothing"}

        response = self.client.get(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_activate_with_plan_error(self):
        url = "/api/billing/activate"
        data = {"plan": "plan"}

        response = self.client.get(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "attr": "plan",
                "code": "invalid_input",
                "detail": "The 'plan' parameter is no longer supported. Please use the 'products' parameter instead.",
                "type": "validation_error",
            },
        )

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.deactivate_products")
    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.get_billing")
    def test_deactivate_success(self, mock_get_billing, mock_deactivate_products):
        mock_deactivate_products.return_value = MagicMock()
        mock_get_billing.return_value = {
            "available_features": [],
            "products": [],
        }

        url = "/api/billing/deactivate"
        data = {"products": "product_1"}

        response = self.client.get(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_deactivate_products.assert_called_once_with(self.organization, "product_1")
        mock_get_billing.assert_called_once_with(self.organization, {})

    def test_deactivate_failure(self):
        url = "/api/billing/deactivate"
        data = {"none": "nothing"}

        response = self.client.get(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestStartupApplicationBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        # Set user as admin/owner by default
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.url = "/api/billing/startups/apply"
        self.data = {"organization_id": str(self.organization.id)}

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.apply_startup_program")
    def test_startup_apply_owner_success(self, mock_apply_startup_program):
        mock_apply_startup_program.return_value = {"success": True}

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})
        mock_apply_startup_program.assert_called_once()

    def test_startup_apply_non_admin_failure(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"], "You need to be an organization admin or owner to apply for the startup program"
        )

    def test_startup_apply_missing_org_id(self):
        empty_data: dict[str, Any] = {}

        response = self.client.post(self.url, empty_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This field is required.",
                "attr": "organization_id",
            },
        )

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.apply_startup_program")
    def test_startup_apply_passes_user_info(self, mock_apply_startup_program):
        mock_apply_startup_program.return_value = {"success": True}

        # Set user properties
        self.user.email = "test@example.com"
        self.user.first_name = "Test"
        self.user.last_name = "User"
        self.user.save()

        # Add additional data fields
        data = {
            **self.data,
            "raised": "1000000",
            "incorporation_date": "2023-01-01",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_data = {
            "organization_id": str(self.organization.id),
            "raised": "1000000",
            "incorporation_date": "2023-01-01",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

        # Check that apply_startup_program was called with the organization and the expected data
        mock_apply_startup_program.assert_called_once()
        _, call_args, _ = mock_apply_startup_program.mock_calls[0]
        self.assertEqual(call_args[0], self.organization)
        self.assertEqual(call_args[1], expected_data)


class TestBillingUsageRequestSerializer(TestCase):
    def test_valid_dates(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "2025-01-01", "end_date": "2025-01-31"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2025-01-01")
        self.assertEqual(serializer.validated_data["end_date"], "2025-01-31")

    @freeze_time("2025-02-15")
    def test_relative_dates(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "-7d", "end_date": "-1d"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2025-02-08")
        self.assertEqual(serializer.validated_data["end_date"], "2025-02-14")

    def test_start_date_all(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "all"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2020-01-01")

    def test_passthrough_fields(self):
        data = {
            "usage_types": urllib.parse.quote('["event_count_in_period","recording_count_in_period"]'),
            "team_ids": urllib.parse.quote("[1,2,3]"),
            "breakdowns": urllib.parse.quote("[type,team]"),
            "interval": "week",
        }
        serializer = BillingUsageRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        for key, value in data.items():
            self.assertEqual(serializer.validated_data[key], value)

    def test_empty_and_null_dates_are_valid(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "", "end_date": None})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data.get("start_date"))
        self.assertIsNone(serializer.validated_data.get("end_date"))


class TestBillingUsageAndSpendAPI(APILicensedTest):
    MOCK_USAGE_DATA = {"results": [{"data": [1, 2], "count": 2}]}
    MOCK_SPEND_DATA = {"results": [{"spend": 100.0, "usage": 10000}]}

    def setUp(self):
        super().setUp()
        # Ensure the user is an admin for these tests by default
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_success(self, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get(f"/api/billing/usage/?start_date=2025-01-01&team_ids=[{self.team.pk}]")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_USAGE_DATA)
        mock_get_usage_data.assert_called_once()
        call_args = mock_get_usage_data.call_args[0]
        self.assertEqual(call_args[0], self.organization)  # First arg is organization
        passed_params = call_args[1]  # Second arg is params dict
        self.assertEqual(passed_params["start_date"], "2025-01-01")
        self.assertEqual(passed_params["team_ids"], f"[{str(self.team.pk)}]")
        self.assertIn("teams_map", passed_params)

        teams_map_dict = json.loads(passed_params["teams_map"])
        self.assertEqual(teams_map_dict, {str(self.team.pk): self.team.name})

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.get_spend_data")
    def test_get_spend_success(self, mock_get_spend_data):
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(
            f"/api/billing/spend/?start_date=2025-01-01&usage_types=events&team_ids=[{self.team.pk}]"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_SPEND_DATA)
        mock_get_spend_data.assert_called_once()
        call_args = mock_get_spend_data.call_args[0]
        self.assertEqual(call_args[0], self.organization)
        passed_params = call_args[1]
        self.assertEqual(passed_params["start_date"], "2025-01-01")
        self.assertEqual(passed_params["usage_types"], "events")
        self.assertEqual(passed_params["team_ids"], f"[{str(self.team.pk)}]")
        self.assertIn("teams_map", passed_params)

        teams_map_dict = json.loads(passed_params["teams_map"])
        self.assertEqual(teams_map_dict, {str(self.team.pk): self.team.name})

    def test_get_usage_permission_denied_for_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get("/api/billing/usage/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_spend_permission_denied_for_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get("/api/billing/spend/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.get_usage_data")
    @patch("products.enterprise.backend.api.billing.BillingViewset._get_teams_map")
    def test_get_usage_empty_teams_map_graceful_handling(self, mock_get_teams_map, mock_get_usage_data):
        mock_get_teams_map.return_value = {}
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get(f"/api/billing/usage/?start_date=2025-01-01")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_USAGE_DATA)
        mock_get_usage_data.assert_called_once()
        call_args = mock_get_usage_data.call_args[0]
        passed_params = call_args[1]
        self.assertIn("teams_map", passed_params)

        teams_map_dict = json.loads(passed_params["teams_map"])
        self.assertEqual(teams_map_dict, {})
        mock_get_teams_map.assert_called_once()

    @patch("products.enterprise.backend.billing.billing_manager.BillingManager.get_spend_data")
    @patch("products.enterprise.backend.api.billing.BillingViewset._get_teams_map")
    def test_get_spend_empty_teams_map_graceful_handling(self, mock_get_teams_map, mock_get_spend_data):
        mock_get_teams_map.return_value = {}
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(f"/api/billing/spend/?start_date=2025-01-01")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_SPEND_DATA)
        mock_get_spend_data.assert_called_once()
        call_args = mock_get_spend_data.call_args[0]
        passed_params = call_args[1]
        self.assertIn("teams_map", passed_params)

        teams_map_dict = json.loads(passed_params["teams_map"])
        self.assertEqual(teams_map_dict, {})
        mock_get_teams_map.assert_called_once()
