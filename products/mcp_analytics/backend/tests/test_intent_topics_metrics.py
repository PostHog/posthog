import pytest

from products.mcp_analytics.backend.intent_topics.metrics import Drift, drift, focus_band, focus_score


class TestFocusScore:
    def test_single_topic_is_fully_consolidated(self) -> None:
        assert focus_score({"a": 120}) == 1.0

    def test_uniform_spread_scores_zero(self) -> None:
        assert focus_score({"a": 10, "b": 10, "c": 10, "d": 10}) == pytest.approx(0.0)

    def test_dominant_topic_scores_between(self) -> None:
        score = focus_score({"a": 90, "b": 5, "c": 5})
        assert 0.5 < score < 1.0

    def test_empty_and_zero_counts_score_zero(self) -> None:
        assert focus_score({}) == 0.0
        assert focus_score({"a": 0, "b": 0}) == 0.0

    def test_bands(self) -> None:
        assert focus_band(0.95) == "consolidated"
        assert focus_band(0.7) == "consolidated"
        assert focus_band(0.55) == "mixed"
        assert focus_band(0.4) == "mixed"
        assert focus_band(0.1) == "spread"


class TestDrift:
    def test_new_growing_shrinking_and_gone(self) -> None:
        previous = {"a": 50, "b": 50, "c": 20}
        current = {"a": 100, "b": 20, "d": 30}

        result = drift(current, previous, min_calls=5, ratio=1.5)

        assert result == Drift(new=["d"], growing=["a"], shrinking=["b"], gone=["c"])

    def test_tiny_topics_are_ignored(self) -> None:
        previous = {"a": 100, "b": 2}
        current = {"a": 100, "b": 4, "c": 3}

        result = drift(current, previous, min_calls=5, ratio=1.5)

        assert result == Drift(new=[], growing=[], shrinking=[], gone=[])

    def test_no_previous_period_marks_everything_new(self) -> None:
        result = drift({"a": 10, "b": 7}, {}, min_calls=5)

        assert result.new == ["a", "b"]
        assert result.growing == [] and result.shrinking == [] and result.gone == []

    def test_lists_are_ordered_by_current_calls_desc(self) -> None:
        result = drift({"x": 10, "y": 40, "z": 25}, {}, min_calls=5)

        assert result.new == ["y", "z", "x"]
