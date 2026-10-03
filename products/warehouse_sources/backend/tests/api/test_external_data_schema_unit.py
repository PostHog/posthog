from parameterized import parameterized

from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase

from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.presentation.views.external_data_schema import schema_display_status


class TestSchemaDisplayStatus(ClickhouseFreeSimpleTestCase):
    @parameterized.expand(
        [
            (ExternalDataSchema.Status.BILLING_LIMIT_REACHED, "Billing limits"),
            (ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW, "Billing limits too low"),
            (ExternalDataSchema.Status.RUNNING, ExternalDataSchema.Status.RUNNING),
            (None, None),
        ]
    )
    def test_maps_billing_statuses_to_labels(self, raw_status: str | None, expected: str | None) -> None:
        assert schema_display_status(ExternalDataSchema(status=raw_status)) == expected
