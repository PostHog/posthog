from unittest.mock import patch

from parameterized import parameterized

from products.slack_app.backend.providers.base import ChatThreadHandler
from products.slack_app.backend.services.whatsapp_api import WhatsAppApiError
from products.slack_app.backend.whatsapp_thread import WhatsAppThreadContext, WhatsAppThreadHandler

_CONTEXT = WhatsAppThreadContext(integration_id=1, wa_id="15550001111", root_message_id="wamid.ROOT")

# mypy-enforced Protocol conformance: signature drift between WhatsAppThreadHandler and
# ChatThreadHandler fails typecheck here even though no test executes this assignment.
_conformance: ChatThreadHandler = WhatsAppThreadHandler(_CONTEXT)


def test_context_round_trip_stamps_provider():
    # A dropped provider key would mis-dispatch the context into SlackThreadContext,
    # which KeyErrors on "channel" — every terminal update for WhatsApp runs dies.
    data = _CONTEXT.to_dict()
    assert data["provider"] == "whatsapp"
    assert WhatsAppThreadContext.from_dict(data) == _CONTEXT


@parameterized.expand(
    [
        (
            "pr_opened",
            lambda h: h.post_pr_opened("https://github.com/x/pull/1", "https://ph/task"),
            "Pull request opened",
        ),
        ("completion", lambda h: h.post_completion("https://ph/task"), "Task completed"),
        ("error", lambda h: h.post_error("boom " * 100, "https://ph/task"), "Task failed"),
        ("cancelled", lambda h: h.post_cancelled("https://ph/task"), "Stopped this run"),
    ]
)
@patch("products.slack_app.backend.whatsapp_thread.WhatsAppBotClient")
def test_terminal_posts_are_replies_to_root(_name, post, expected_snippet, mock_client_cls):
    handler = WhatsAppThreadHandler(_CONTEXT)

    post(handler)

    send = mock_client_cls.return_value.send_message
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["to"] == "15550001111"
    assert kwargs["reply_to_message_id"] == "wamid.ROOT"
    assert expected_snippet in kwargs["text"]
    assert _name != "error" or len(kwargs["text"]) < 400  # 200-char error truncation holds


@parameterized.expand([("window_closed", 131047), ("other_api_error", 100)])
@patch("products.slack_app.backend.whatsapp_thread.WhatsAppBotClient")
def test_send_failures_never_propagate(_name, error_code, mock_client_cls):
    # A terminal update landing outside the 24-hour customer service window (or any
    # other send failure) must not fail the task run that triggered it.
    mock_client_cls.return_value.send_message.side_effect = WhatsAppApiError("nope", code=error_code)
    handler = WhatsAppThreadHandler(_CONTEXT)

    handler.post_completion("https://ph/task")


@patch("products.slack_app.backend.whatsapp_thread.WhatsAppBotClient")
def test_progress_and_stream_methods_do_nothing(mock_client_cls):
    # These run on every post_slack_update progress tick for every WhatsApp run; a
    # "helpful" future edit adding HTTP here would hammer the Graph API.
    handler = WhatsAppThreadHandler(_CONTEXT)

    assert handler.start_status_stream(first_task_id="t", first_task_title="x") is None
    handler.append_status_chunks(ts="1", task_updates=[{"id": "t"}])
    handler.stop_status_stream(ts="1")
    handler.post_or_update_progress("cloning")
    handler.delete_progress()

    mock_client_cls.assert_not_called()
