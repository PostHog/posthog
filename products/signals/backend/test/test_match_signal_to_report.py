import json

import pytest
from unittest.mock import patch

from products.signals.backend.temporal.grouping import HallucinatedSignalIdError, match_signal_to_report
from products.signals.backend.temporal.types import ExistingReportMatch, NewReportMatch, SignalCandidate

MODULE_PATH = "products.signals.backend.temporal.grouping"


def _candidate(signal_id: str = "real-signal-1", report_id: str = "report-1") -> SignalCandidate:
    return SignalCandidate(
        signal_id=signal_id,
        report_id=report_id,
        content="some related content",
        source_product="error_tracking",
        source_type="exception",
        distance=0.1,
    )


async def _capture_validate(query_results):
    """Run match_signal_to_report with call_llm stubbed to hand back the real validate closure."""
    captured: dict = {}

    async def fake_call_llm(*, validate, **kwargs):
        captured["validate"] = validate
        # Mimic exhausted retries: surface whatever the validator raises on a hallucinated id.
        return validate(json.dumps({"reason": "n/a", "match_type": "new", "title": "t", "summary": "s"}))

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        await match_signal_to_report(
            team_id=1,
            description="a new signal",
            source_product="error_tracking",
            source_type="exception",
            queries=["q0"],
            query_results=query_results,
            report_contexts={},
        )
    return captured["validate"]


@pytest.mark.asyncio
async def test_validate_rejects_out_of_set_signal_id_and_lists_valid_ids():
    validate = await _capture_validate([[_candidate("real-signal-1")]])

    hallucinated = json.dumps(
        {"reason": "looks related", "match_type": "existing", "signal_id": "made-up-id", "query_index": 0}
    )
    with pytest.raises(HallucinatedSignalIdError) as exc_info:
        validate(hallucinated)

    # The retry feedback must re-anchor the model on the actual candidate ids.
    assert "real-signal-1" in str(exc_info.value)
    assert "made-up-id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_accepts_in_set_signal_id():
    validate = await _capture_validate([[_candidate("real-signal-1", report_id="report-1")]])

    valid = json.dumps({"reason": "related", "match_type": "existing", "signal_id": "real-signal-1", "query_index": 0})
    result = validate(valid)
    assert isinstance(result, ExistingReportMatch)
    assert result.report_id == "report-1"
    assert result.match_metadata.parent_signal_id == "real-signal-1"


@pytest.mark.asyncio
async def test_match_falls_back_to_new_report_when_retries_exhausted():
    """A persistently hallucinated signal_id must not crash the activity — it falls back to a new report."""

    async def fake_call_llm(*, validate, **kwargs):
        raise HallucinatedSignalIdError('signal_id "ghost" is not one of the candidates')

    with patch(f"{MODULE_PATH}.call_llm", new=fake_call_llm):
        result = await match_signal_to_report(
            team_id=1,
            description="first line of description\nsecond line",
            source_product="error_tracking",
            source_type="exception",
            queries=["q0"],
            query_results=[[_candidate("real-signal-1")]],
            report_contexts={},
        )

    assert isinstance(result, NewReportMatch)
    assert result.title == "first line of description"
    assert result.match_metadata.rejected_signal_ids == ["real-signal-1"]
