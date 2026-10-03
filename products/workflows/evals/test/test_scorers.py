from __future__ import annotations

import pytest

from products.workflows.evals.scorers import FinalMessageMentions, MergedSpfRecord

EXPECTED = {"merged_spf_record": {"includes": ["include:_spf.google.com", "include:amazonses.com"]}}
TOKEN = "3f1c9a52b7e04c1e9d0a2f4b8e6c9a10"


@pytest.mark.parametrize(
    "message,score",
    [
        ("Replace it with:\n```\nv=spf1 include:_spf.google.com include:amazonses.com ~all\n```", 1.0),
        ("| TXT | @ | `v=spf1 include:_spf.google.com include:amazonses.com ~all` |", 1.0),
        ("Keep `v=spf1 include:_spf.google.com ~all` and add `v=spf1 include:amazonses.com ~all`", 0.0),
        ("Add `v=spf1 include:amazonses.com ~all` at the root.", 0.0),
        ("Use `v=spf1 include:_spf.google.com ~all include:amazonses.com`", 0.0),
    ],
)
def test_merged_spf_record_needs_one_record_with_every_include(message: str, score: float) -> None:
    result = MergedSpfRecord().eval({"last_message": message}, expected=EXPECTED)

    assert result.score == score


@pytest.mark.parametrize(
    "message,score",
    [
        (f"| TXT | _amazonses.mail.example.com | `{TOKEN}` |", 1.0),
        (f"| TXT | _amazonses.mail.example.com | `{TOKEN.upper()}` |", 0.0),
        (f"| TXT | _amazonses.mail.example.com | `{TOKEN[:16]}...` |", 0.0),
    ],
)
def test_final_message_mentions_needs_each_value_exactly(message: str, score: float) -> None:
    result = FinalMessageMentions().eval(
        {"last_message": message}, expected={"final_message_mentions": {"values": [TOKEN]}}
    )

    assert result.score == score
