import json

import pytest
from unittest.mock import patch

from temporalio.testing import ActivityEnvironment

from products.signals.backend.temporal.grouping_v2 import read_signals_from_s3_activity
from products.signals.backend.temporal.types import EmitSignalInputs, ReadSignalsFromS3Input

MODULE = "products.signals.backend.temporal.grouping_v2"


def _batch_item(**overrides: object) -> dict:
    item = {
        "team_id": 1,
        "source_product": "github",
        "source_type": "issue",
        "source_id": "42",
        "description": "the signal",
        "weight": 0.5,
        "extra": {},
        "remediation": None,
        "metadata": {},
    }
    item.update(overrides)
    return item


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        pytest.param(_batch_item(), id="current_shape"),
        pytest.param(_batch_item(written_by_a_newer_worker={"cost": 3}), id="field_this_worker_does_not_know"),
    ],
)
async def test_batch_read_accepts_a_batch_written_by_another_version(item: dict) -> None:
    with patch(f"{MODULE}.object_storage.read", return_value=json.dumps([item])):
        result = await ActivityEnvironment().run(
            read_signals_from_s3_activity, ReadSignalsFromS3Input(object_key="signals/buffer/batch-1")
        )

    assert result.signals == [
        EmitSignalInputs(
            team_id=1,
            source_product="github",
            source_type="issue",
            source_id="42",
            description="the signal",
            weight=0.5,
        )
    ]
