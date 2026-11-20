from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from posthog.llm.system_one import NoulAnswer, SystemOneResult

from products.slack_app.backend.logic.onboarding.daily_summary import (
    RootRef,
    build_workspace_index,
    pick_threads,
    summary_threads,
    thread_text,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

DAILY_SUMMARY = "products.slack_app.backend.logic.onboarding.daily_summary"
SINCE = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
BEFORE = SINCE.timestamp() - 3600
AFTER = SINCE.timestamp() + 3600


def _root(
    ts: float, *, channel: str = "C1", author: str = "U_OTHER", replies: int = 0, latest: float = 0, **extra
) -> RootRef:
    return RootRef(
        channel_id=channel,
        ts=f"{ts:.6f}",
        author=author,
        reply_count=replies,
        latest_reply=latest,
        reply_users=tuple(extra.get("reply_users", ())),
        mentions=tuple(extra.get("mentions", ())),
        score=extra.get("score", 0.0),
    )


def test_pick_threads_puts_the_persons_threads_first_then_the_best_scored() -> None:
    mine_moved = _root(BEFORE - 10, author=SLACK_USER_ID, replies=3, latest=AFTER - 1)
    mine_quiet = _root(BEFORE - 20, author=SLACK_USER_ID, replies=0)
    replied = _root(BEFORE - 30, replies=2, latest=AFTER + 5, reply_users=(SLACK_USER_ID,))
    mentioned = _root(AFTER, mentions=(SLACK_USER_ID,))
    incident = _root(AFTER + 1, score=0.9)
    chatter = _root(AFTER + 2, score=0.2)
    launch = _root(AFTER + 3, score=0.7)
    not_my_channel = _root(AFTER + 4, channel="C9", score=0.95)
    old_news = _root(BEFORE - 40, score=0.95)
    roots = [mine_moved, mine_quiet, replied, mentioned, incident, chatter, launch, not_my_channel, old_news]

    kept = pick_threads(roots, SLACK_USER_ID, {"C1"}, since=SINCE)

    # The person's threads come newest first, then the rest of their channels by Jev's score. A quiet own root,
    # chatter, another channel and a thread that stopped moving before the last run are all left out.
    assert kept == [replied, mentioned, mine_moved, incident, launch]


def test_thread_text_keeps_the_root_and_the_tail_of_a_long_thread() -> None:
    messages = [{"user": "U1", "text": "root"}, *({"user": f"U{n}", "text": f"reply {n}"} for n in range(10))]

    text = thread_text(messages)

    assert text.startswith("<@U1>: root\n(+4 earlier replies)\n<@U4>: reply 4")
    assert text.endswith("<@U9>: reply 9")


@pytest.mark.django_db
def test_the_sweep_builds_the_index_once_and_the_runs_only_read_it(workspace_integration) -> None:
    cache.clear()
    workspace_integration.config = {"scope": "channels:read,channels:history"}
    workspace_integration.save()
    history: dict[str, list[dict[str, Any]]] = {
        "C1": [
            {
                "ts": f"{AFTER:.6f}",
                "user": "U_OTHER",
                "text": "we are rolling back the release <@U_LEAD>",
                "reply_count": 4,
                "latest_reply": f"{AFTER + 9:.6f}",
                "reply_users": ["U_LEAD", SLACK_USER_ID],
            },
            {"ts": f"{AFTER + 1:.6f}", "user": "U_OTHER", "text": "lunch?"},
            {"ts": f"{AFTER + 2:.6f}", "bot_id": "B1", "text": "deploy finished"},
            {"ts": f"{AFTER + 3:.6f}", "user": "U_OTHER", "subtype": "channel_join", "text": "joined"},
        ]
    }
    client = MagicMock()
    client.conversations_list.return_value = {
        "channels": [{"id": "C1", "is_member": True}, {"id": "C2", "is_member": False}]
    }
    client.conversations_history.side_effect = lambda channel, **_: {"messages": history.get(channel, [])}
    client.users_conversations.return_value = {"channels": [{"id": "C1"}]}
    client.conversations_replies.return_value = {
        "messages": [history["C1"][0], {"user": SLACK_USER_ID, "text": "on it"}]
    }
    client.chat_getPermalink.return_value = {"permalink": "https://example.slack.com/archives/C1/p1"}

    def decide(*, state: dict[str, Any], questions: dict[str, Any]) -> SystemOneResult:
        roots = state["roots"]
        return SystemOneResult(
            model="jev",
            answers={
                key: NoulAnswer(probability=0.9 if "rolling back" in roots[key]["text"] else 0.1) for key in questions
            },
            input_tokens=None,
        )

    with (
        patch(f"{DAILY_SUMMARY}.SlackIntegration") as slack,
        patch(f"{DAILY_SUMMARY}.build_system_one_client") as ranker,
    ):
        slack.return_value.client = client
        slack.return_value.missing_scopes.side_effect = lambda required: frozenset(required) - {
            "channels:read",
            "channels:history",
        }
        ranker.return_value.decide.side_effect = decide
        # A run before the sweep built today's index reads no channel itself.
        assert summary_threads(workspace_integration, SLACK_USER_ID, since=SINCE) == []
        assert client.conversations_history.call_count == 0
        assert build_workspace_index(workspace_integration) == 2
        assert build_workspace_index(workspace_integration) == 2
        first = summary_threads(workspace_integration, SLACK_USER_ID, since=SINCE)
        second = summary_threads(workspace_integration, "U_SOMEONE_ELSE", since=SINCE)

    # The bot and the join notice never reach Jev, and only the rollback thread is worth a read.
    assert [thread.text.split("\n")[0] for thread in first] == ["<@U_OTHER>: we are rolling back the release <@U_LEAD>"]
    assert first[0].involves_person is True and first[0].permalink == "https://example.slack.com/archives/C1/p1"
    assert second[0].involves_person is False
    # The second build and both runs reuse the day's index: one channel list and one history read for the workspace.
    assert client.conversations_list.call_count == 1
    assert client.conversations_history.call_count == 1
    assert ranker.return_value.decide.call_count == 1
    cached = cache.get(f"slack_app:daily_summary:index:{SLACK_TEAM_ID}:{timezone.now().date().isoformat()}")
    assert cached and "text" not in str(cached) and "rolling back" not in str(cached)
