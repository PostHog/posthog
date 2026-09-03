from unittest.mock import patch

from products.workflows.backend.services.step_resume import RESULT_STRING_CAP, resume_workflow_step

_PRODUCE = "products.workflows.backend.services.step_resume.produce_internal_event"


def test_emits_the_wake_keyed_to_the_step_with_capped_strings() -> None:
    with patch(_PRODUCE) as produce:
        resume_workflow_step(
            team_id=7,
            origin_key="job:step:3",
            status="completed",
            result={"final_message": "x" * (RESULT_STRING_CAP + 1), "pr_urls": ["u"], "error_message": None},
        )

    produce.assert_called_once()
    assert produce.call_args.kwargs["team_id"] == 7
    event = produce.call_args.kwargs["event"]
    assert event.event == "$workflow_step_resume"
    assert event.distinct_id == "team_7"
    assert event.properties == {
        "origin_key": "job:step:3",
        "status": "completed",
        "result": {"final_message": "x" * RESULT_STRING_CAP, "pr_urls": ["u"]},
    }


def test_a_failed_emit_does_not_raise() -> None:
    with patch(_PRODUCE, side_effect=RuntimeError("kafka down")):
        resume_workflow_step(team_id=7, origin_key="job:step:3", status="failed")
