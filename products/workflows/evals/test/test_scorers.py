from __future__ import annotations

import pytest

from products.workflows.evals.scorers import MergedSpfRecord

EXPECTED = {"merged_spf_record": {"includes": ["include:_spf.google.com", "include:amazonses.com"]}}


@pytest.mark.parametrize(
    "message,score",
    [
        ("Replace it with:\n```\nv=spf1 include:_spf.google.com include:amazonses.com ~all\n```", 1.0),
        ("| TXT | @ | `v=spf1 include:_spf.google.com include:amazonses.com ~all` |", 1.0),
        ("Keep `v=spf1 include:_spf.google.com ~all` and add `v=spf1 include:amazonses.com ~all`", 0.0),
        ("Add `v=spf1 include:amazonses.com ~all` at the root.", 0.0),
    ],
)
def test_merged_spf_record_needs_one_record_with_every_include(message: str, score: float) -> None:
    result = MergedSpfRecord()._run_eval_sync({"last_message": message}, expected=EXPECTED)

    assert result.score == score
