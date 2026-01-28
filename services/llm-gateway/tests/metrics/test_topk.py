from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.metrics.topk import TopKCounter


class TestTopKCounter:
    @pytest.fixture
    def counter(self) -> TopKCounter:
        with patch("llm_gateway.metrics.topk.Gauge") as mock_gauge_class:
            mock_gauge_class.return_value = MagicMock()
            return TopKCounter(name="test_metric", documentation="Test metric", k=3)

    def test_inc_tracks_value(self, counter: TopKCounter) -> None:
        counter.inc("label_a", 10.0)
        assert counter.get("label_a") == 10.0

    def test_inc_accumulates_values(self, counter: TopKCounter) -> None:
        counter.inc("label_a", 10.0)
        counter.inc("label_a", 5.0)
        assert counter.get("label_a") == 15.0

    def test_inc_with_default_value(self, counter: TopKCounter) -> None:
        counter.inc("label_a")
        assert counter.get("label_a") == 1.0

    def test_get_returns_zero_for_unknown_label(self, counter: TopKCounter) -> None:
        assert counter.get("unknown") == 0.0

    def test_inc_ignores_none_label(self, counter: TopKCounter) -> None:
        counter.inc(None, 10.0)
        assert counter.get("None") == 0.0

    def test_inc_ignores_zero_value(self, counter: TopKCounter) -> None:
        counter.inc("label_a", 0.0)
        assert counter.get("label_a") == 0.0

    def test_inc_ignores_negative_value(self, counter: TopKCounter) -> None:
        counter.inc("label_a", -5.0)
        assert counter.get("label_a") == 0.0

    def test_exports_up_to_k_labels(self, counter: TopKCounter) -> None:
        counter.inc("a", 1.0)
        counter.inc("b", 2.0)
        counter.inc("c", 3.0)
        assert len(counter._exported_labels) == 3

    def test_evicts_minimum_when_exceeding_k(self, counter: TopKCounter) -> None:
        counter.inc("a", 1.0)
        counter.inc("b", 2.0)
        counter.inc("c", 3.0)
        counter.inc("d", 4.0)

        assert len(counter._exported_labels) == 3
        assert "a" not in counter._exported_labels
        assert "d" in counter._exported_labels

    def test_does_not_evict_when_new_value_is_lower(self, counter: TopKCounter) -> None:
        counter.inc("a", 10.0)
        counter.inc("b", 20.0)
        counter.inc("c", 30.0)
        counter.inc("d", 5.0)

        assert len(counter._exported_labels) == 3
        assert "d" not in counter._exported_labels
        assert "a" in counter._exported_labels

    def test_updates_existing_exported_label(self, counter: TopKCounter) -> None:
        counter.inc("a", 1.0)
        counter.inc("b", 2.0)
        counter.inc("c", 3.0)
        counter.inc("a", 100.0)

        assert counter.get("a") == 101.0
        assert "a" in counter._exported_labels

    def test_tracks_all_values_even_when_not_exported(self, counter: TopKCounter) -> None:
        counter.inc("a", 10.0)
        counter.inc("b", 20.0)
        counter.inc("c", 30.0)
        counter.inc("d", 5.0)

        assert counter.get("a") == 10.0
        assert counter.get("b") == 20.0
        assert counter.get("c") == 30.0
        assert counter.get("d") == 5.0

    def test_previously_evicted_can_return_to_top_k(self, counter: TopKCounter) -> None:
        counter.inc("a", 1.0)
        counter.inc("b", 2.0)
        counter.inc("c", 3.0)
        counter.inc("d", 4.0)

        assert "a" not in counter._exported_labels
        counter.inc("a", 100.0)
        assert "a" in counter._exported_labels

    def test_gauge_labels_called_on_export(self) -> None:
        with patch("llm_gateway.metrics.topk.Gauge") as mock_gauge_class:
            mock_gauge = MagicMock()
            mock_gauge_class.return_value = mock_gauge

            counter = TopKCounter(name="test_metric", documentation="Test metric", k=3)
            counter.inc("label_a", 10.0)

            mock_gauge.labels.assert_called_with(label="label_a")
            mock_gauge.labels.return_value.set.assert_called_with(10.0)

    def test_gauge_remove_called_on_eviction(self) -> None:
        with patch("llm_gateway.metrics.topk.Gauge") as mock_gauge_class:
            mock_gauge = MagicMock()
            mock_gauge_class.return_value = mock_gauge

            counter = TopKCounter(name="test_metric", documentation="Test metric", k=2)
            counter.inc("a", 1.0)
            counter.inc("b", 2.0)
            counter.inc("c", 3.0)

            mock_gauge.remove.assert_called_with("a")

    def test_handles_gauge_remove_key_error(self) -> None:
        with patch("llm_gateway.metrics.topk.Gauge") as mock_gauge_class:
            mock_gauge = MagicMock()
            mock_gauge.remove.side_effect = KeyError("label not found")
            mock_gauge_class.return_value = mock_gauge

            counter = TopKCounter(name="test_metric", documentation="Test metric", k=2)
            counter.inc("a", 1.0)
            counter.inc("b", 2.0)
            counter.inc("c", 3.0)

            assert "c" in counter._exported_labels
            assert "a" not in counter._exported_labels


@pytest.mark.parametrize(
    "increments,expected_exported,expected_values",
    [
        (
            [("a", 1.0), ("b", 2.0)],
            {"a", "b"},
            {"a": 1.0, "b": 2.0},
        ),
        (
            [("a", 1.0), ("b", 2.0), ("c", 3.0), ("d", 4.0)],
            {"b", "c", "d"},
            {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0},
        ),
        (
            [("a", 10.0), ("b", 20.0), ("c", 30.0), ("a", 50.0)],
            {"a", "b", "c"},
            {"a": 60.0, "b": 20.0, "c": 30.0},
        ),
        (
            [("a", 1.0), ("b", 2.0), ("c", 3.0), ("d", 0.5)],
            {"a", "b", "c"},
            {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.5},
        ),
    ],
    ids=[
        "under_k_all_exported",
        "over_k_evicts_minimum",
        "accumulates_keeps_in_top",
        "low_value_not_exported",
    ],
)
def test_topk_scenarios(
    increments: list[tuple[str, float]],
    expected_exported: set[str],
    expected_values: dict[str, float],
) -> None:
    with patch("llm_gateway.metrics.topk.Gauge"):
        counter = TopKCounter(name="test_metric", documentation="Test metric", k=3)

        for label, value in increments:
            counter.inc(label, value)

        assert counter._exported_labels == expected_exported
        for label, value in expected_values.items():
            assert counter.get(label) == value
