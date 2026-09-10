import json
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.signals.backend.models import SignalReport
from products.signals.backend.signal_costs import add_cost
from products.signals.backend.signal_handoffs import SignalHandoff, publish_handoff, read_handoff, write_handoff
from products.signals.backend.temporal.grouping import dispatch_signal_handoffs_activity
from products.signals.backend.temporal.types import SignalData, SignalReportSummaryWorkflowInputs


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted,unsafe", [(False, False), (True, False), (False, True)])
async def test_handoff_round_trip_and_single_publication(deleted: bool, unsafe: bool) -> None:
    signal = SignalData(
        signal_id="signal-1",
        content="Synthetic signal",
        source_product="github",
        source_type="issue",
        source_id="issue-1",
        weight=1,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={"report_id": "report-1"},
    )
    add_cost(signal.metadata, "model-a", token_cost=3)
    add_cost(signal.metadata, "model-b", token_cost=8, compute_cost=4, stage="implementation")
    handoff = SignalHandoff(team_id=1, signal=signal, embedding=[0.1, 0.2])
    storage: dict[str, str] = {}
    report_query = MagicMock()
    report_query.values_list.return_value.afirst = AsyncMock(
        return_value=SignalReport.Status.DELETED if deleted else SignalReport.Status.READY
    )
    safety_query = MagicMock()
    safety_query.order_by.return_value.values_list.return_value.afirst = AsyncMock(
        return_value=json.dumps({"choice": not unsafe})
    )
    with (
        patch("products.signals.backend.signal_handoffs.object_storage.read", side_effect=storage.get),
        patch("products.signals.backend.signal_handoffs.object_storage.write", side_effect=storage.__setitem__),
        patch("products.signals.backend.signal_handoffs.SignalReport.objects.filter", return_value=report_query),
        patch(
            "products.signals.backend.signal_handoffs.SignalReportArtefact.objects.filter", return_value=safety_query
        ),
        patch("products.signals.backend.signal_handoffs.producer_scope"),
        patch("products.signals.backend.signal_handoffs.emit_embedding_request") as emit,
    ):
        key = await write_handoff(handoff)
        stored = await read_handoff(key, 1)
        assert stored == handoff
        with pytest.raises(ValueError, match="another team"):
            await read_handoff(key, 2)
        assert json.loads(storage[key])["signal"]["metadata"]["token_cost"] == {
            "research": 3,
            "implementation": 8,
        }
        await publish_handoff(key, 1)
        await publish_handoff(key, 1)
        assert (await read_handoff(key, 1)).published is True
        with patch("products.signals.backend.temporal.grouping.async_connect", new_callable=AsyncMock) as connect:
            await dispatch_signal_handoffs_activity(
                SignalReportSummaryWorkflowInputs(team_id=1, report_id="report-1", signal_keys=[key])
            )
        connect.assert_not_called()

    emit.assert_called_once()
    record = emit.call_args.kwargs
    metadata = record["metadata"]
    assert metadata["token_cost"] == {"research": 3, "implementation": 8}
    assert metadata["compute_cost"] == {"research": 0, "implementation": 4}
    assert metadata.get("deleted", False) is (deleted or unsafe)
    assert record["document_id"] == signal.signal_id
    assert record["timestamp"] == signal.timestamp
    assert record["content"] == signal.content
    assert record["models"] == ["text-embedding-3-small-1536", "text-embedding-3-large-3072"]
