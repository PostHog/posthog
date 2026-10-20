from parameterized import parameterized

from products.logs.backend.onset_detection import find_onset


class TestFindOnset:
    def test_step_change_starts_at_the_first_high_bucket(self) -> None:
        onset = find_onset([10] * 8 + [200, 210, 190, 205])

        assert onset is not None
        assert onset.index == 8
        assert onset.peak_index == 9
        assert onset.end_index is None
        assert onset.confirmed
        assert 9.0 <= onset.expected <= 11.0

    def test_spike_that_ends_reports_its_last_bucket(self) -> None:
        onset = find_onset([10] * 8 + [200, 210, 10, 10])

        assert onset is not None
        assert (onset.index, onset.end_index) == (8, 9)

    def test_gradual_ramp_starts_where_counts_leave_the_band(self) -> None:
        onset = find_onset([10] * 6 + [12, 40, 80, 160, 320, 640])

        assert onset is not None
        assert onset.index == 7
        assert onset.peak_index == 11

    @parameterized.expand(
        [
            ("flat", [10] * 12),
            ("noisy_but_steady", [8, 12, 9, 11, 10, 13, 7, 10, 12, 9, 11, 10]),
            ("drop_is_not_a_spike", [10] * 8 + [0, 0, 0, 0]),
            ("too_little_history", [10, 10, 200, 200]),
        ]
    )
    def test_no_onset(self, _name: str, counts: list[int]) -> None:
        assert find_onset(counts) is None

    def test_unconfirmed_single_bucket_spike_is_reported_unconfirmed(self) -> None:
        onset = find_onset([10] * 11 + [300])

        assert onset is not None
        assert onset.index == 11
        assert not onset.confirmed

    def test_excluded_partial_bucket_stays_out_of_the_baseline(self) -> None:
        # A window that starts mid-bucket has a short first bucket; it must not drag the baseline down.
        with_partial = find_onset([1] + [10] * 7 + [200, 200], exclude_from_baseline={0})

        assert with_partial is not None
        assert with_partial.index == 8
        assert with_partial.baseline_samples == 7
