from temporalio.exceptions import ActivityError, ApplicationError

from products.signals.backend.temporal.error_details import MAX_ERROR_MESSAGE_LENGTH, describe_exception


def _activity_error(message: str) -> ActivityError:
    return ActivityError(
        message,
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="select_repository_activity",
        activity_id="1",
        retry_state=None,
    )


def test_unwraps_activity_error_to_application_error_type():
    # The real spike shape: the workflow catches an ActivityError wrapping an ApplicationError
    # whose `type` carries the original exception's class name.
    app = ApplicationError("GitHub installation suspended", type="GitHubIntegrationError")
    activity = _activity_error("Activity task failed")
    activity.__cause__ = app

    assert describe_exception(activity) == ("GitHubIntegrationError", "GitHub installation suspended")


def test_prefers_concrete_cause_over_temporal_wrapper():
    root = ValueError("bad repo selection")
    activity = _activity_error("Activity task failed")
    activity.__cause__ = root

    assert describe_exception(activity) == ("ValueError", "bad repo selection")


def test_application_error_without_type_falls_back_to_class_name():
    assert describe_exception(ApplicationError("some message")) == ("ApplicationError", "some message")


def test_plain_exception_reports_its_own_type_and_message():
    assert describe_exception(RuntimeError("boom")) == ("RuntimeError", "boom")


def test_message_is_truncated():
    _, message = describe_exception(ValueError("x" * (MAX_ERROR_MESSAGE_LENGTH + 50)))
    assert len(message) == MAX_ERROR_MESSAGE_LENGTH


def test_cyclic_cause_chain_terminates():
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a

    # Deepest reachable concrete cause wins; the guard just has to stop.
    assert describe_exception(a) == ("ValueError", "b")
