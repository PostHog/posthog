from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.natural_language_query import (
    FilterCandidate,
    FilterContext,
    _ProposedCandidate,
    rank_candidates,
    validate_candidate,
)
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionGatewayError, DecisionResult

CONTEXT = FilterContext(
    services=("checkout", "api-gateway"),
    services_truncated=False,
    log_attribute_keys=("http.status_code",),
    resource_attribute_keys=("k8s.namespace.name",),
    attribute_keys_truncated=False,
)


def _proposal(**overrides: Any) -> _ProposedCandidate:
    fields: dict[str, Any] = {
        "label": "Errors",
        "date_from": "-2h",
        "date_to": None,
        "severity_levels": ["error"],
        "service_names": [],
        "filters": [],
        **overrides,
    }
    return _ProposedCandidate.model_validate(fields)


def _filter(source: str, key: str, operator: str, values: list[str]) -> dict[str, Any]:
    return {"source": source, "key": key, "operator": operator, "values": values}


class TestValidateCandidate(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_service", {"service_names": ["payments"]}),
            ("unknown_attribute_key", {"filters": [_filter("log_attribute", "user.id", "exact", ["1"])]}),
            (
                "key_from_the_wrong_attribute_list",
                {"filters": [_filter("log_attribute", "k8s.namespace.name", "exact", ["prod"])]},
            ),
            ("empty_message_search", {"filters": [_filter("message", "message", "icontains", ["  "])]}),
            ("unparseable_date", {"date_from": "two hours ago"}),
        ]
    )
    def test_drops_readings_the_team_cannot_run(self, _name: str, overrides: dict[str, Any]) -> None:
        assert validate_candidate(_proposal(**overrides), CONTEXT) is None

    def test_builds_viewer_query_with_canonical_names(self) -> None:
        query = validate_candidate(
            _proposal(
                service_names=["Checkout"],
                filters=[
                    _filter("resource_attribute", "k8s.namespace.name", "exact", ["prod"]),
                    _filter("log_attribute", "http.status_code", "is_set", ["ignored"]),
                    _filter("message", "message", "icontains", ["timeout"]),
                ],
            ),
            CONTEXT,
        )

        assert query == {
            "dateRange": {"date_from": "-2h"},
            "severityLevels": ["error"],
            "serviceNames": ["checkout"],
            "filterGroup": [
                {"key": "k8s.namespace.name", "type": "log_resource_attribute", "operator": "exact", "value": ["prod"]},
                {"key": "http.status_code", "type": "log_attribute", "operator": "is_set"},
                {"key": "message", "type": "log", "operator": "icontains", "value": "timeout"},
            ],
        }

    def test_keeps_unlisted_names_when_the_known_list_is_truncated(self) -> None:
        context = FilterContext(
            services=("checkout",),
            services_truncated=True,
            log_attribute_keys=(),
            resource_attribute_keys=(),
            attribute_keys_truncated=True,
        )

        query = validate_candidate(
            _proposal(
                service_names=["payments"],
                filters=[_filter("log_attribute", "user.id", "exact", ["1"])],
            ),
            context,
        )

        assert query is not None
        assert query["serviceNames"] == ["payments"]
        assert query["filterGroup"][0]["key"] == "user.id"


class TestRankCandidates(SimpleTestCase):
    CANDIDATES = [
        FilterCandidate(label="First proposed", query={"severityLevels": ["error"]}, probability=None),
        FilterCandidate(label="Second proposed", query={"severityLevels": ["warn"]}, probability=None),
    ]

    @patch("products.logs.backend.natural_language_query.ml_inference.decide_when_available")
    def test_orders_by_decision_model_probability(self, decide: Any) -> None:
        decide.return_value = DecisionResult(
            model="jevk5",
            answers={"best": ChoiceAnswer(choice="c2", confidence=0.8, probabilities={"c1": 0.2, "c2": 0.8})},
            input_tokens=10,
        )

        ranked, confidence, ranked_by = rank_candidates("warnings", self.CANDIDATES, team_id=1, distinct_id="u")

        assert [c.label for c in ranked] == ["Second proposed", "First proposed"]
        assert [c.probability for c in ranked] == [0.8, 0.2]
        assert (confidence, ranked_by) == (0.8, "decision_model")

    @patch("products.logs.backend.natural_language_query.ml_inference.decide_when_available")
    def test_falls_back_to_proposal_order_when_the_decision_model_fails(self, decide: Any) -> None:
        decide.side_effect = DecisionGatewayError(503, "unavailable")

        ranked, confidence, ranked_by = rank_candidates("warnings", self.CANDIDATES, team_id=1, distinct_id="u")

        assert [c.label for c in ranked] == ["First proposed", "Second proposed"]
        assert (confidence, ranked_by) == (None, "proposal_order")
