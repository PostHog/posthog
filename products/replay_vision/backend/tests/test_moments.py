import datetime as dt

import pytest

from products.replay_vision.backend.moments import MomentOccurrence, coalesce_moments

_T0 = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _occ(seconds: float, uuid: str = "u-1", event: str = "checkout_error") -> MomentOccurrence:
    return MomentOccurrence(uuid=uuid, timestamp=_T0 + dt.timedelta(seconds=seconds), event=event)


def test_empty_returns_empty():
    assert coalesce_moments([], before_seconds=60, after_seconds=60) == []


def test_single_occurrence_yields_anchor_window():
    [moment] = coalesce_moments([_occ(0)], before_seconds=30, after_seconds=90)
    assert moment.anchor_uuid == "u-1"
    assert moment.anchor_event == "checkout_error"
    assert moment.anchor_timestamp == _T0
    assert moment.window_start == _T0 - dt.timedelta(seconds=30)
    assert moment.window_end == _T0 + dt.timedelta(seconds=90)
    assert moment.occurrence_count == 1


@pytest.mark.parametrize(
    "separation_s, expected_moments",
    [
        pytest.param(120, 1, id="overlapping_windows_merge"),
        pytest.param(125, 1, id="within_merge_gap_merges"),
        pytest.param(126, 2, id="past_merge_gap_splits"),
    ],
)
def test_merge_boundary(separation_s: int, expected_moments: int):
    # before=after=60 puts adjacent window edges 120s apart; the 5s merge gap extends that to 125s.
    occurrences = [_occ(0, uuid="u-1"), _occ(separation_s, uuid="u-2")]
    moments = coalesce_moments(occurrences, before_seconds=60, after_seconds=60)
    assert len(moments) == expected_moments


def test_merged_group_keeps_first_anchor_and_spans_union():
    occurrences = [_occ(0, uuid="u-1"), _occ(30, uuid="u-2", event="payment_failed"), _occ(60, uuid="u-3")]
    [moment] = coalesce_moments(occurrences, before_seconds=60, after_seconds=60)
    assert moment.anchor_uuid == "u-1"
    assert moment.anchor_event == "checkout_error"
    assert moment.occurrence_count == 3
    assert moment.window_start == _T0 - dt.timedelta(seconds=60)
    assert moment.window_end == _T0 + dt.timedelta(seconds=120)


def test_max_clip_length_starts_a_new_moment():
    # Occurrences every 100s chain-merge; the 6th would stretch the clip past 600s, so it starts a new moment.
    occurrences = [_occ(100 * i, uuid=f"u-{i}") for i in range(6)]
    moments = coalesce_moments(occurrences, before_seconds=60, after_seconds=60)
    assert [m.occurrence_count for m in moments] == [5, 1]
    assert moments[1].anchor_uuid == "u-5"


def test_deterministic_for_ties_and_input_order():
    # Same-timestamp occurrences tie-break on uuid, regardless of input order — anchors are identity.
    forward = [_occ(0, uuid="b"), _occ(0, uuid="a")]
    moments_forward = coalesce_moments(forward, before_seconds=60, after_seconds=60)
    moments_reversed = coalesce_moments(list(reversed(forward)), before_seconds=60, after_seconds=60)
    assert moments_forward == moments_reversed
    assert moments_forward[0].anchor_uuid == "a"
