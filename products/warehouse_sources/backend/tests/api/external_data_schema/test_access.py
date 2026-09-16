"""External schema access-control tests."""

import pytest
from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

pytestmark = [pytest.mark.django_db]


class TestExternalDataSchemaAPIKeyScopes(APIBaseTest):
    def _make_api_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"stripe_secret_key": "123"},
        )
        self.schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )
        self.client.force_authenticate(None)

    @parameterized.expand(
        [
            ("external_data_source:read", "GET", "list", True),
            ("external_data_source:read", "GET", "retrieve", True),
            ("external_data_source:read", "PATCH", "partial_update", False),
            ("external_data_source:write", "GET", "list", True),
            ("external_data_source:write", "PATCH", "partial_update", True),
            ("other_scope:read", "GET", "list", False),
            ("other_scope:write", "PATCH", "partial_update", False),
        ]
    )
    def test_api_key_scope_gating(self, scope, method, action, should_have_access):
        api_key = self._make_api_key([scope])
        headers = {"authorization": f"Bearer {api_key}"}

        if action == "list":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/"
            response = self.client.get(url, headers=headers)
        elif action == "retrieve":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/"
            response = self.client.get(url, headers=headers)
        elif action == "partial_update":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/"
            response = self.client.patch(url, {"should_sync": False}, format="json", headers=headers)
        else:
            self.fail(f"Unknown action: {action}")

        if should_have_access:
            self.assertNotEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected access but got 403 for {scope} on {method} {action}",
            )
        else:
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected 403 but got {response.status_code} for {scope} on {method} {action}",
            )
