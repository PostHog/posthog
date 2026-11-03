from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.auto_assignment.base import Candidate, HistoryEvidence, Processor
from products.error_tracking.backend.logic.auto_assignment.gate import (
    AutoAssignmentConfig,
    parse_auto_assignment_config,
)
from products.error_tracking.backend.logic.auto_assignment.pipeline import ProcessorStatus, run
from products.error_tracking.backend.logic.issue_changes import AssigneeRef

CONFIG = AutoAssignmentConfig()


class FakeProcessor(Processor):
    def __init__(
        self,
        name: str,
        confidence: float | None,
        threshold: float = 0.5,
        sends_data_to_model: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.sends_data_to_model = sends_data_to_model
        self._confidence = confidence
        self._threshold = threshold
        self._error = error
        self.calls = 0

    def threshold(self, config: AutoAssignmentConfig) -> float:
        return self._threshold

    def propose(self, evidence: object, config: AutoAssignmentConfig) -> Candidate | None:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if self._confidence is None:
            return None
        return Candidate(
            assignee=AssigneeRef(type="user", id=self.name),
            confidence=self._confidence,
            source=self.name,
            reason="fake",
            evidence=HistoryEvidence(similar_issue_ids=(), nearest_distance=0.0),
        )


def _evidence(ai_approved: bool = True) -> MagicMock:
    evidence = MagicMock(ai_processing_approved=ai_approved, issue_id="issue")
    evidence.team.id = 1
    evidence.similar_issue_lookup_ms = None
    return evidence


class TestPipeline(SimpleTestCase):
    def test_first_candidate_over_its_threshold_wins_and_later_processors_do_not_run(self) -> None:
        none = FakeProcessor("none", confidence=None)
        weak = FakeProcessor("weak", confidence=0.4, threshold=0.5)
        strong = FakeProcessor("strong", confidence=0.6, threshold=0.5)
        later = FakeProcessor("later", confidence=1.0)

        result = run(_evidence(), processors=[none, weak, strong, later], config=CONFIG)

        assert result.decision is not None
        assert result.decision.candidate.source == "strong"
        assert [(o.processor, o.status) for o in result.outcomes] == [
            ("none", ProcessorStatus.NO_CANDIDATE),
            ("weak", ProcessorStatus.BELOW_THRESHOLD),
            ("strong", ProcessorStatus.ACCEPTED),
            ("later", ProcessorStatus.SKIPPED_ALREADY_DECIDED),
        ]
        assert result.outcomes[1].candidate is not None and result.outcomes[1].candidate.confidence == 0.4
        assert later.calls == 0

    def test_confidence_equal_to_threshold_is_accepted(self) -> None:
        result = run(_evidence(), processors=[FakeProcessor("p", confidence=0.5, threshold=0.5)], config=CONFIG)

        assert result.decision is not None

    def test_model_processor_is_skipped_without_ai_approval(self) -> None:
        model = FakeProcessor("model", confidence=1.0, sends_data_to_model=True)
        local = FakeProcessor("local", confidence=1.0)

        result = run(_evidence(ai_approved=False), processors=[model, local], config=CONFIG)

        assert [(o.processor, o.status) for o in result.outcomes] == [
            ("model", ProcessorStatus.SKIPPED_AI_NOT_APPROVED),
            ("local", ProcessorStatus.ACCEPTED),
        ]
        assert model.calls == 0

    @patch("products.error_tracking.backend.logic.auto_assignment.pipeline.capture_exception")
    def test_failing_processor_does_not_stop_the_next(self, _capture: MagicMock) -> None:
        broken = FakeProcessor("broken", confidence=None, error=RuntimeError("boom"))
        working = FakeProcessor("working", confidence=1.0)

        result = run(_evidence(), processors=[broken, working], config=CONFIG)

        assert [o.status for o in result.outcomes] == [ProcessorStatus.FAILED, ProcessorStatus.ACCEPTED]
        _capture.assert_called_once()


class TestConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_payload", None, (3, 0.15, 0.66)),
            ("valid", {"history": {"top_k": 5, "max_distance": 0.3, "min_confidence": 0.8}}, (5, 0.3, 0.8)),
            (
                "invalid_fields_keep_defaults",
                {"history": {"top_k": 0, "max_distance": "x", "min_confidence": 2}},
                (3, 0.15, 0.66),
            ),
        ]
    )
    def test_parse(self, _name: str, payload: object, expected: tuple[int, float, float]) -> None:
        history = parse_auto_assignment_config(payload).history

        assert (history.top_k, history.max_distance, history.min_confidence) == expected
