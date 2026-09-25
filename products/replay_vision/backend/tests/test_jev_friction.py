from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from products.ml_inference.backend.facade.contracts import (
    DecisionGatewayUnreachableError,
    DecisionResult,
    DecisionsDisabledError,
    NoulAnswer,
)
from products.replay_vision.backend.jev_friction import judge_scan_friction
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput
from products.replay_vision.backend.temporal.types import ScannerCallOutput

_FLAG = "products.replay_vision.backend.jev_friction.get_feature_flag_or_none"
_API = "products.replay_vision.backend.jev_friction.decision_api"
_CAPTURE = "products.replay_vision.backend.jev_friction.posthoganalytics"


def _calm_output() -> ScannerCallOutput:
    return ScannerCallOutput(
        model_output=SummarizerOutput(title="Quick visit", summary="The user skimmed the pricing page.", confidence=0.9)
    )


def _decision(probability: float) -> DecisionResult:
    return DecisionResult(
        model="jevk5-fp8-0.2", answers={"friction": NoulAnswer(probability=probability)}, input_tokens=120
    )


class TestJudgeScanFriction(SimpleTestCase):
    @parameterized.expand(
        [
            ("flag_off", None),
            ("boolean_flag", True),
            ("unknown_variant", "something-else"),
            ("default_arm", "regex-only"),
        ]
    )
    def test_no_decision_call_outside_the_experiment(self, _name: str, flag_value: object) -> None:
        output = _calm_output()
        with patch(_FLAG, return_value=flag_value), patch(_API) as api:
            assert judge_scan_friction(1, uuid4(), output) is output
        api.decide_when_available.assert_not_called()

    @parameterized.expand([("shadow", "jev-shadow"), ("graduated", "jev-only")])
    def test_both_experiment_arms_store_the_probability(self, _name: str, mode: str) -> None:
        output = _calm_output()
        with patch(_FLAG, return_value=mode), patch(_API) as api, patch(_CAPTURE):
            api.decide_when_available.return_value = _decision(0.42)
            judged = judge_scan_friction(1, uuid4(), output)
        assert judged.friction_probability == 0.42
        assert judged.friction_model == "jevk5-fp8-0.2"
        assert judged.model_output is output.model_output

    def test_a_monitor_non_event_is_not_judged(self) -> None:
        output = ScannerCallOutput(
            model_output=MonitorOutput(
                verdict="no", reasoning="The user did not struggle and saw no errors.", confidence=0.9
            )
        )
        with patch(_FLAG, return_value="jev-only"), patch(_API) as api:
            assert judge_scan_friction(1, uuid4(), output) is output
        api.decide_when_available.assert_not_called()

    @parameterized.expand(
        [
            ("team_not_enrolled", DecisionsDisabledError(1)),
            ("gateway_unreachable", DecisionGatewayUnreachableError("timed out")),
        ]
    )
    def test_a_failed_decision_leaves_the_scan_output_unchanged(self, _name: str, error: Exception) -> None:
        output = _calm_output()
        with patch(_FLAG, return_value="jev-only"), patch(_API) as api:
            api.decide_when_available.side_effect = error
            judged = judge_scan_friction(1, uuid4(), output)
        assert judged is output

    def test_an_out_of_range_probability_is_not_stored(self) -> None:
        output = _calm_output()
        with patch(_FLAG, return_value="jev-only"), patch(_API) as api:
            api.decide_when_available.return_value = _decision(7.0)
            judged = judge_scan_friction(1, uuid4(), output)
        assert judged is output

    def test_disagreement_with_the_regex_is_counted(self) -> None:
        output = ScannerCallOutput(
            model_output=SummarizerOutput(
                title="Upload trouble", summary="The user hit an error and retried twice.", confidence=0.9
            )
        )
        labels = {"regex_verdict": "true", "jev_verdict": "false"}
        before = REGISTRY.get_sample_value("replay_vision_jev_friction_disagreements_total", labels) or 0.0
        with patch(_FLAG, return_value="jev-shadow"), patch(_API) as api, patch(_CAPTURE):
            api.decide_when_available.return_value = _decision(0.1)
            judge_scan_friction(1, uuid4(), output)
        assert REGISTRY.get_sample_value("replay_vision_jev_friction_disagreements_total", labels) == before + 1
