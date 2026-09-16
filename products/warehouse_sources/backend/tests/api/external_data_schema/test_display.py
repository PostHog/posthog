"""External schema display status tests."""

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.presentation.views.external_data_schema.serializers import schema_display_status

pytestmark = [pytest.mark.django_db]


class TestSchemaDisplayStatus(SimpleTestCase):
    @parameterized.expand(
        [
            (ExternalDataSchema.Status.BILLING_LIMIT_REACHED, "Billing limits"),
            (ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW, "Billing limits too low"),
            (ExternalDataSchema.Status.RUNNING, ExternalDataSchema.Status.RUNNING),
            (None, None),
        ]
    )
    def test_maps_billing_statuses_to_labels(self, raw_status, expected):
        assert schema_display_status(ExternalDataSchema(status=raw_status)) == expected
