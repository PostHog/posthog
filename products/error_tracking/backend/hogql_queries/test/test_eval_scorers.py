from __future__ import annotations

from ee.hogai.eval.sandboxed.error_tracking.scorers import _recordings_text_has_results


def test_recordings_text_has_results_accepts_toon_lists() -> None:
    assert _recordings_text_has_results(
        """
results[1]:
  - id: 019e4f6a-b3d7-7000-8a3a-f18fc1f9d80a
    session_id: session-1
hasMore: false
"""
    )


def test_recordings_text_has_results_rejects_empty_toon_lists() -> None:
    assert not _recordings_text_has_results(
        """
results:
hasMore: false
"""
    )
