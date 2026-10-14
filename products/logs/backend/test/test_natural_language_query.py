from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.natural_language_query import (
    FilterCandidate,
    FilterContext,
    NaturalLanguageQueryResult,
    _ProposedCandidate,
    rank_candidates,
    validate_candidate,
)
from products.logs.backend.presentation.views.natural_language_api import (
    LogsNaturalLanguageQueryRequestSerializer,
    LogsNaturalLanguageQueryResponseSerializer,
)
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionGatewayError, DecisionResult

CONTEXT = FilterContext(
    services=("checkout", "api-gateway"),
    services_truncated=False,
    log_attribute_keys=("http.status_code",),
    log_attribute_keys_truncated=False,
    resource_attribute_keys=("k8s.namespace.name",),
    resource_attribute_keys_truncated=False,
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
            ("all_as_end_date", {"date_to": "all"}),
        ]
    )
    def test_drops_readings_the_team_cannot_run(self, _name: str, overrides: dict[str, Any]) -> None:
        assert validate_candidate(_proposal(**overrides), CONTEXT) is None

    @parameterized.expand([("start_of_today", "dStart"), ("all_time", "all")])
    def test_keeps_readings_with_viewer_date_anchors(self, _name: str, date_from: str) -> None:
        query = validate_candidate(_proposal(date_from=date_from), CONTEXT)

        assert query is not None
        assert query["dateRange"] == {"date_from": date_from}

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
            log_attribute_keys_truncated=True,
            resource_attribute_keys=(),
            resource_attribute_keys_truncated=True,
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

    def test_drops_unknown_keys_from_a_complete_list_when_the_other_list_is_truncated(self) -> None:
        context = FilterContext(
            services=("checkout",),
            services_truncated=False,
            log_attribute_keys=("http.status_code",),
            log_attribute_keys_truncated=True,
            resource_attribute_keys=("k8s.namespace.name",),
            resource_attribute_keys_truncated=False,
        )

        unknown_resource_key = _proposal(filters=[_filter("resource_attribute", "k8s.pod.name", "exact", ["web-1"])])
        unknown_log_key = _proposal(filters=[_filter("log_attribute", "user.id", "exact", ["1"])])

        assert validate_candidate(unknown_resource_key, context) is None
        assert validate_candidate(unknown_log_key, context) is not None


class TestRankCandidates(SimpleTestCase):
    CANDIDATES = [
        FilterCandidate(label="First proposed", query={"severityLevels": ["error"]}, probability=None),
        FilterCandidate(label="Second proposed", query={"severityLevels": ["warn"]}, probability=None),
    ]

    @patch("products.logs.backend.natural_language_query.ml_inference.decide_when_available")
    def test_orders_by_decision_model_probability(self, decide: Any) -> None:
        decide.return_value = DecisionResult(
            model="jevk5",
            answers={"best": ChoiceAnswer(choice="c2", confidence=0.6, probabilities={"c1": 0.2, "c2": 0.8})},
            input_tokens=10,
        )

        ranking = rank_candidates("warnings", self.CANDIDATES, team_id=1, distinct_id="u")

        assert [c.label for c in ranking.candidates] == ["Second proposed", "First proposed"]
        assert [c.probability for c in ranking.candidates] == [0.8, 0.2]
        assert ranking.ranked_by == "decision_model"
        # The winner's probability, not the decision model's margin, drives auto-apply.
        assert ranking.confidence == 0.8

    @patch("products.logs.backend.natural_language_query.ml_inference.decide_when_available")
    def test_falls_back_to_proposal_order_when_the_decision_model_fails(self, decide: Any) -> None:
        decide.side_effect = DecisionGatewayError(503, "unavailable")

        ranking = rank_candidates("warnings", self.CANDIDATES, team_id=1, distinct_id="u")

        assert [c.label for c in ranking.candidates] == ["First proposed", "Second proposed"]
        assert (ranking.confidence, ranking.ranked_by) == (None, "proposal_order")


class TestRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("relative_range", {"date_from": "-2h", "date_to": None}, True),
            ("iso_range", {"date_from": "2026-10-01T10:00:00Z", "date_to": "2026-10-01T12:00:00Z"}, True),
            ("unreadable_start", {"date_from": "garbage"}, False),
            ("unreadable_end", {"date_from": "-2h", "date_to": "yesterday-ish"}, False),
            ("start_of_today", {"date_from": "dStart", "date_to": None}, True),
            ("start_of_month", {"date_from": "mStart"}, True),
            ("all_time", {"date_from": "all"}, True),
            ("all_as_end_date", {"date_from": "-2h", "date_to": "all"}, False),
            ("bare_number", {"date_from": "-2"}, False),
        ]
    )
    def test_date_range_validation(self, _name: str, date_range: dict[str, Any], valid: bool) -> None:
        serializer = LogsNaturalLanguageQueryRequestSerializer(
            data={"query": "error logs from checkout", "dateRange": date_range}
        )

        assert serializer.is_valid() is valid


class TestResponseSerializer(SimpleTestCase):
    def test_renders_a_result_with_a_valueless_filter(self) -> None:
        query = {
            "dateRange": {"date_from": "-2h"},
            "severityLevels": ["error"],
            "serviceNames": ["checkout"],
            "filterGroup": [
                {"key": "message", "type": "log", "operator": "icontains", "value": "timeout"},
                {"key": "user.id", "type": "log_attribute", "operator": "is_set"},
            ],
        }
        result = NaturalLanguageQueryResult(
            candidates=(FilterCandidate(label="Checkout errors", query=query, probability=0.8),),
            confidence=0.8,
            ranked_by="decision_model",
            dropped_count=1,
        )

        data = LogsNaturalLanguageQueryResponseSerializer(instance=result).data

        # The serializer fills the nullable date_to the dataclass left out, so the wire shape matches the schema.
        rendered_query = {**query, "dateRange": {"date_from": "-2h", "date_to": None}}
        assert data == {
            "candidates": [{"label": "Checkout errors", "query": rendered_query, "probability": 0.8}],
            "confidence": 0.8,
            "ranked_by": "decision_model",
            "dropped_count": 1,
        }
