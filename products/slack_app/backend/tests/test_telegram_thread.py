from unittest.mock import patch

from parameterized import parameterized

from products.slack_app.backend.providers.base import ChatThreadHandler
from products.slack_app.backend.telegram_thread import TelegramThreadContext, TelegramThreadHandler

_CONTEXT = TelegramThreadContext(integration_id=1, chat_id="-100555", root_message_id="42", telegram_user_id="777")

# mypy-enforced Protocol conformance: signature drift between TelegramThreadHandler and
# ChatThreadHandler fails typecheck here even though no test executes this assignment.
_conformance: ChatThreadHandler = TelegramThreadHandler(_CONTEXT)


def test_context_round_trip_stamps_provider():
    # A dropped provider key would mis-dispatch the context into SlackThreadContext,
    # which KeyErrors on "channel" — every terminal update for Telegram runs dies.
    data = _CONTEXT.to_dict()
    assert data["provider"] == "telegram"
    assert TelegramThreadContext.from_dict(data) == _CONTEXT


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
@patch("products.slack_app.backend.telegram_thread.TelegramBotClient")
def test_terminal_posts_are_replies_to_root(_name, post, expected_snippet, mock_client_cls):
    handler = TelegramThreadHandler(_CONTEXT)

    post(handler)

    send = mock_client_cls.return_value.send_message
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["chat_id"] == "-100555"
    assert kwargs["reply_to_message_id"] == "42"
    assert expected_snippet in kwargs["text"]
    assert _name != "error" or len(kwargs["text"]) < 400  # 200-char error truncation holds


@patch("products.slack_app.backend.telegram_thread.TelegramBotClient")
def test_progress_and_stream_methods_do_nothing(mock_client_cls):
    # These run on every post_slack_update progress tick for every Telegram run; a
    # "helpful" future edit adding HTTP here would hammer the Bot API.
    handler = TelegramThreadHandler(_CONTEXT)

    assert handler.start_status_stream(first_task_id="t", first_task_title="x") is None
    handler.append_status_chunks(ts="1", task_updates=[{"id": "t"}])
    handler.stop_status_stream(ts="1")
    handler.post_or_update_progress("cloning")
    handler.delete_progress()

    mock_client_cls.assert_not_called()
