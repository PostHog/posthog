import uuid

import pytest
from posthog.test.base import BaseTest

import dagster
import pydantic

from products.error_tracking.backend.models import ErrorTrackingSymbolSet
from products.error_tracking.dags.symbol_set_backfill_last_used import (
    SymbolSetBackfillLastUsedConfig,
    _backfill_last_used_bucket,
    symbol_set_backfill_last_used,
)


def test_rejects_zero_batch_size() -> None:
    with pytest.raises(pydantic.ValidationError):
        SymbolSetBackfillLastUsedConfig(total_per_run=1, batch_size=0)


class TestSymbolSetBackfillLastUsed(BaseTest):
    def test_backfills_only_the_requested_bucket(self) -> None:
        selected = ErrorTrackingSymbolSet.objects.create(team=self.team, ref="selected", id=uuid.UUID(int=256))
        unselected = ErrorTrackingSymbolSet.objects.create(team=self.team, ref="unselected", id=uuid.UUID(int=1))

        updated = _backfill_last_used_bucket(bucket=0, batch_size=10)

        assert updated == 1
        selected.refresh_from_db()
        unselected.refresh_from_db()
        assert selected.last_used is not None
        assert unselected.last_used is None

    def test_backfill_advances_to_the_next_bucket(self) -> None:
        symbol_set = ErrorTrackingSymbolSet.objects.create(team=self.team, ref="bucket-one", id=uuid.UUID(int=1))

        result = symbol_set_backfill_last_used(
            dagster.build_asset_context(),
            SymbolSetBackfillLastUsedConfig(total_per_run=1, batch_size=1),
        )

        symbol_set.refresh_from_db()
        assert symbol_set.last_used is not None
        assert isinstance(result, dagster.MaterializeResult)
