from django.conf import settings

import structlog

from posthog.ph_client import feature_enabled_or_false

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.ml_inference.backend.facade import api as ml_inference
from products.ml_inference.backend.facade.contracts import ChoiceAnswer, DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType

logger = structlog.get_logger(__name__)

SEVERITY_INFERENCE_FLAG = "error-tracking-severity-inference"
SEVERITY_INFERENCE_MODEL = "posthog/hogference/jevk5-fp8-0.2"

_SEVERITY_QUESTION_ID = "severity"
_SEVERITY_QUESTION = DecisionQuestion(
    type=DecisionQuestionType.CHOICE,
    instructions="How severe is this error for the people using the application?",
    criteria={
        ErrorTrackingIssue.Severity.CRITICAL.value: "Crashes the app, loses data, or blocks a core flow such as sign-in, checkout or payment",
        ErrorTrackingIssue.Severity.HIGH.value: "Breaks a feature for the users who hit it, with no workaround",
        ErrorTrackingIssue.Severity.MEDIUM.value: "Degrades a feature, or the app recovers or retries on its own",
        ErrorTrackingIssue.Severity.LOW.value: "Noise with no user impact, such as expected errors, cancelled requests, or browser extension and third-party script errors",
    },
)


def severity_inference_enabled(team_id: int) -> bool:
    # The analytics SDK is disabled in local dev, so the flag always reads as off there.
    if settings.DEBUG:
        return True
    try:
        return feature_enabled_or_false(
            SEVERITY_INFERENCE_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("error_tracking_severity_inference_flag_check_failed", team_id=team_id)
        return False


def build_severity_state(stacktrace: str, event_properties: dict[str, object]) -> str:
    handled = event_properties.get("$exception_handled")
    lines = [stacktrace.rstrip("\n")]
    if isinstance(handled, bool):
        lines.append(f"Handled by the application: {'yes' if handled else 'no'}")
    for label, key in (("Level", "$exception_level"), ("SDK", "$lib")):
        value = event_properties.get(key)
        if isinstance(value, str) and value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def infer_severity(team_id: int, state: str) -> ChoiceAnswer | None:
    """Ask the decision model for a severity. Raises the ml_inference gateway errors unchanged."""
    result = ml_inference.decide(
        DecisionRequest(
            team_id=team_id,
            state=state,
            questions={_SEVERITY_QUESTION_ID: _SEVERITY_QUESTION},
            model=SEVERITY_INFERENCE_MODEL,
        )
    )
    answer = result.answers.get(_SEVERITY_QUESTION_ID)
    if not isinstance(answer, ChoiceAnswer) or answer.choice not in ErrorTrackingIssue.Severity.values:
        logger.warning("error_tracking_severity_inference_unexpected_answer", team_id=team_id, answer=repr(answer))
        return None
    return answer
