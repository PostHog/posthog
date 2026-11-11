import pytest

from products.slack_app.backend.services.bare_mention import (
    AWAITED_REQUEST_TTL_SECONDS,
    is_bare_mention,
    thread_is_recent,
)

NOW = 1_800_000_000.0


def _mention(**overrides) -> dict:
    return {"type": "app_mention", "channel": "C001", "user": "U123", "ts": "1234.5678", **overrides}


@pytest.mark.parametrize(
    "event, expected",
    [
        pytest.param(_mention(text="<@U0BOT>"), True, id="tag_only"),
        pytest.param(_mention(text="  <@U0BOT|posthog>  "), True, id="labeled_tag_with_whitespace"),
        pytest.param(_mention(text="<@U0BOT>", thread_ts="1234.5678"), True, id="thread_root"),
        pytest.param(_mention(text="<@U0BOT> how many signups"), False, id="tag_with_a_question"),
        pytest.param(
            _mention(
                text="<@U0BOT>",
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "Checkout errors doubled"}}],
            ),
            False,
            id="words_only_in_blocks",
        ),
        pytest.param(_mention(text="<@U0BOT>", files=[{"id": "F1", "mimetype": "image/png"}]), False, id="file"),
        pytest.param(_mention(text="<@U0BOT>", thread_ts="1000.0000"), False, id="reply_inside_a_thread"),
    ],
)
def test_only_a_top_level_mention_with_nothing_in_it_is_bare(event, expected):
    assert is_bare_mention(event) is expected


@pytest.mark.parametrize(
    "thread_ts, expected",
    [
        pytest.param(f"{NOW - 20:.6f}", True, id="started_seconds_ago"),
        pytest.param(f"{NOW - AWAITED_REQUEST_TTL_SECONDS - 1:.6f}", False, id="older_than_the_claim_can_live"),
        pytest.param("not-a-timestamp", False, id="malformed"),
        pytest.param(None, False, id="missing"),
    ],
)
def test_thread_is_recent_only_while_a_claim_can_exist(thread_ts, expected):
    assert thread_is_recent(thread_ts, now=NOW) is expected
