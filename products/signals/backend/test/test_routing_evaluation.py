import pytest

from products.signals.eval.evaluate_routing import Labels, Predictions, evaluate


def test_routing_evaluation_measures_false_exclusion_separately_from_coverage():
    labels = Labels.model_validate(
        {
            "dataset_version": "test",
            "domains": ["checkout", "delivery"],
            "cases": [
                {"id": "a", "domain": "checkout", "excluded_domains": ["delivery"]},
                {"id": "b", "domain": "checkout", "excluded_domains": ["delivery"]},
                {"id": "c", "domain": "delivery"},
            ],
        }
    )
    predictions = Predictions.model_validate(
        {
            "dataset_version": "test",
            "model_version": "test",
            "cases": [
                {"id": "a", "domain": "delivery", "confidence": 0.6},
                {"id": "b", "domain": "checkout", "confidence": 0.9},
                {"id": "c", "domain": None},
            ],
        }
    )
    result = evaluate(labels, predictions)
    assert result["coverage"] == 2 / 3
    assert result["precision_when_classified"] == 0.5
    assert result["false_exclusions"] == 1
    assert evaluate(labels, predictions, threshold=0.8)["false_exclusions"] == 0
    predictions.cases.pop()
    with pytest.raises(ValueError, match="exactly one"):
        evaluate(labels, predictions)
