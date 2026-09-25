"""Compare frozen routing predictions. No model calls, report writes, or rollout changes.

python -m products.signals.eval.evaluate_routing --labels /path/labels.json \
    --predictions agent=/path/agent.json --predictions code=/path/code.json \
    --predictions jev=/path/jev.json --threshold 0.8

Labels: {"dataset_version": "v1", "domains": ["checkout"], "cases": [
  {"id": "case-1", "domain": "checkout", "excluded_domains": ["delivery"]}
]}. Predictions: {"dataset_version": "v1", "model_version": "prompt-v1",
"cases": [{"id": "case-1", "domain": "checkout", "confidence": 0.9}]}.
Use owner-reviewed held-out cases. Never tune the threshold on this test set.
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    domain: str | None
    excluded_domains: list[str] = Field(default_factory=list, max_length=100)


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version: str = Field(min_length=1, max_length=100)
    domains: list[str] = Field(min_length=1, max_length=100)
    cases: list[Case] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate label IDs")
        allowed = set(self.domains)
        for case in self.cases:
            if (case.domain is not None and case.domain not in allowed) or set(case.excluded_domains) - allowed:
                raise ValueError("Labels reference an unknown domain")
        return self


class Prediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    domain: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Predictions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_version: str
    model_version: str = Field(min_length=1, max_length=100)
    cases: list[Prediction] = Field(max_length=500)


def evaluate(labels: Labels, predictions: Predictions, threshold: float | None = None) -> dict:
    if predictions.dataset_version != labels.dataset_version:
        raise ValueError("Dataset versions differ")
    predicted = {case.id: case for case in predictions.cases}
    if len(predicted) != len(predictions.cases) or set(predicted) != {case.id for case in labels.cases}:
        raise ValueError("Every labeled case needs exactly one prediction (null for abstention)")
    covered = correct = false_exclusions = relevant = 0
    confusion: dict[str, dict[str, int]] = {}
    for case in labels.cases:
        prediction = predicted[case.id]
        domain = prediction.domain
        if domain is not None and domain not in labels.domains:
            raise ValueError("Prediction references an unknown domain")
        if threshold is not None and (prediction.confidence is None or prediction.confidence < threshold):
            domain = None
        covered += domain is not None
        correct += domain is not None and domain == case.domain
        is_relevant = case.domain is not None and case.domain not in case.excluded_domains
        relevant += is_relevant
        false_exclusions += is_relevant and domain in case.excluded_domains
        row = confusion.setdefault(case.domain or "unclassified", {})
        row[domain or "abstain"] = row.get(domain or "abstain", 0) + 1
    return {
        "dataset_version": labels.dataset_version,
        "model_version": predictions.model_version,
        "threshold": threshold,
        "cases": len(labels.cases),
        "classified": covered,
        "coverage": covered / len(labels.cases),
        "precision_when_classified": correct / covered if covered else None,
        "false_exclusions": false_exclusions,
        "relevant_cases": relevant,
        "false_exclusion_rate": false_exclusions / relevant if relevant else None,
        "confusion": confusion,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument(
        "--predictions", action="append", required=True, help="method=path; repeat for agent, code, and Jev"
    )
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()
    if args.threshold is not None and not 0 <= args.threshold <= 1:
        parser.error("threshold must be between 0 and 1")
    labels = Labels.model_validate_json(args.labels.read_text())
    results = {}
    for entry in args.predictions:
        method, filename = entry.split("=", 1)
        if method in results:
            parser.error("Prediction method names must be unique")
        predictions = Predictions.model_validate_json(Path(filename).read_text())
        results[method] = evaluate(labels, predictions, args.threshold)
    sys.stdout.write(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
