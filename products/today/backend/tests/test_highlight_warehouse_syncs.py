import uuid
from datetime import date
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import warehouse_syncs
from products.today.backend.logic.highlight_types import Context
from products.warehouse_sources.backend.facade.contracts import FailingSource


class TestWarehouseSyncs(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "ids and the retry note are cut",
                None,
                1,
                "Request failed for team 123456; deferring the next run",
                "Postgres sync failed once in the last 7 days",
                "Last error: Request failed",
            ),
            (
                "a labeled source names its label",
                "stripe_",
                4,
                None,
                "Postgres sync ‘stripe_’ failed 4 times in the last 7 days",
                "Last error: unknown",
            ),
            (
                "an error of only ids reads unknown",
                None,
                2,
                "1234567",
                "Postgres sync failed 2 times in the last 7 days",
                "Last error: unknown",
            ),
        ]
    )
    def test_each_failing_source_is_one_risk_item(
        self, _name: str, label: str | None, failures: int, error: str | None, title: str, detail: str
    ) -> None:
        source = FailingSource(
            source_id=uuid.uuid4(), source_type="Postgres", source_label=label, failures=failures, latest_error=error
        )
        context = cast(
            Context, SimpleNamespace(team=SimpleNamespace(id=1), user=SimpleNamespace(id=2), today=date(2026, 10, 13))
        )
        registered = next(s for s in load_sources() if s.name == "warehouse_syncs")

        with patch.object(warehouse_syncs, "list_failing_sources", return_value=[source]):
            found = registered.find(context)

        self.assertEqual(
            [(c.title, c.detail, c.url) for c in found.items],
            [(title, detail, f"/data-warehouse/sources/{source.source_id}")],
        )
