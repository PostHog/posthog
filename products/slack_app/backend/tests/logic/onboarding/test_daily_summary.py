from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from slack_sdk.errors import SlackApiError

from posthog.llm.system_one import NoulAnswer, SystemOneResult

from products.slack_app.backend.logic.onboarding.daily_summary import (
    DailySummaryIndexNotReady,
    RootRef,
    build_workspace_index,
    cached_index,
    pick_threads,
    read_thread,
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
    # The person asked the app, which answered: handled, so not news.
    asked_app = _root(AFTER + 5, author=SLACK_USER_ID, replies=1, latest=AFTER + 6, reply_users=("U_BOT",))
    roots = [mine_moved, mine_quiet, replied, mentioned, incident, chatter, launch, not_my_channel, old_news, asked_app]

    kept = pick_threads(roots, SLACK_USER_ID, {"C1"}, since=SINCE, bot_user_id="U_BOT")

    # The person's threads come newest first, then the rest of their channels by Jev's score. A quiet own root,
    # chatter, another channel and a thread that stopped moving before the last run are all left out.
    assert kept == [replied, mentioned, mine_moved, incident, launch]


def test_thread_text_keeps_the_root_and_the_tail_of_a_long_thread() -> None:
    messages = [{"user": "U1", "text": "root"}, *({"user": f"U{n}", "text": f"reply {n}"} for n in range(10))]

    text = thread_text(messages)

    assert text.startswith("<@U1>: root\n(+4 earlier replies)\n<@U4>: reply 4")
    assert text.endswith("<@U9>: reply 9")


@pytest.mark.django_db
@time_machine.travel(datetime(2026, 11, 9, 9, 30, tzinfo=UTC), tick=False)
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
    client.conversations_history.side_effect = lambda channel, **_: {"messages": history.get(channel, [])}
    client.users_conversations.return_value = {"channels": [{"id": "C1"}]}
    client.conversations_replies.return_value = {
        "messages": [history["C1"][0], {"user": SLACK_USER_ID, "text": "on it"}]
    }
    client.chat_getPermalink.return_value = {"ok": True, "permalink": "https://example.slack.com/archives/C1/p1"}

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
        patch(f"{DAILY_SUMMARY}.wants_summary", return_value=True),
    ):
        slack.return_value.client = client
        slack.return_value.missing_scopes.side_effect = lambda required: frozenset(required) - {
            "channels:read",
            "channels:history",
        }
        ranker.return_value.decide.side_effect = decide
        # A run before the sweep built today's index reads no channel itself.
        assert summary_threads(workspace_integration, SLACK_USER_ID, since=SINCE, bot_user_id=None) == []
        assert client.conversations_history.call_count == 0
        # The lunch question got no replies, names nobody and Jev passed over it, so the index keeps only one root.
        assert build_workspace_index(workspace_integration) == 1
        assert build_workspace_index(workspace_integration) == 1
        first = summary_threads(workspace_integration, SLACK_USER_ID, since=SINCE, bot_user_id=None)
        second = summary_threads(workspace_integration, "U_SOMEONE_ELSE", since=SINCE, bot_user_id=None)

    # The bot and the join notice never reach Jev, and only the rollback thread is worth a read.
    assert [thread.text.split("\n")[0] for thread in first] == ["<@U_OTHER>: we are rolling back the release <@U_LEAD>"]
    assert first[0].involves_person is True and first[0].permalink == "https://example.slack.com/archives/C1/p1"
    assert second[0].involves_person is False
    # The second build and both runs reuse the day's index: one channel list and one history read for the workspace.
    assert sum("user" not in call.kwargs for call in client.users_conversations.call_args_list) == 1
    assert client.conversations_history.call_count == 1
    assert ranker.return_value.decide.call_count == 1
    cached = cache.get(f"slack_app:daily_summary:index:{SLACK_TEAM_ID}:{timezone.now().strftime('%Y-%m-%dT%H')}")
    assert cached and "text" not in str(cached) and "rolling back" not in str(cached)


def test_read_thread_follows_the_pages_to_the_latest_replies() -> None:
    root = {"ts": "1.0", "user": "U_OTHER", "text": "the export is broken"}
    client = MagicMock()
    client.conversations_replies.side_effect = [
        {
            "messages": [root, {"ts": "1.1", "user": SLACK_USER_ID, "text": "looking"}],
            "response_metadata": {"next_cursor": "c2"},
        },
        {"messages": [root, {"ts": "1.2", "user": "U_BOT", "bot_id": "B1", "text": "Done, merged."}]},
    ]

    read = read_thread(client, "C1", "1.0", bot_user_id="U_BOT")

    # The app's reply sits on the second page, which a single read would never see.
    assert read is not None and read.app_took_part is True
    assert [message["ts"] for message in read.messages] == ["1.0", "1.1"]
    assert client.conversations_replies.call_args_list[1].kwargs["cursor"] == "c2"


def _index_client(history: list[Any]) -> MagicMock:
    client = MagicMock()
    client.users_conversations.return_value = {"channels": [{"id": "C1"}]}
    client.conversations_history.side_effect = history
    return client


def _patched_slack(client: MagicMock) -> Any:
    slack = patch(f"{DAILY_SUMMARY}.SlackIntegration")
    started = slack.start()
    started.return_value.client = client
    started.return_value.missing_scopes.side_effect = lambda required: frozenset(required) - {
        "channels:read",
        "channels:history",
    }
    return slack


@pytest.mark.django_db
@time_machine.travel(datetime(2026, 11, 9, 9, 30, tzinfo=UTC), tick=False)
def test_a_failed_build_caches_nothing_and_its_retry_can_build(workspace_integration) -> None:
    cache.clear()
    root = {"ts": f"{AFTER:.6f}", "user": "U_OTHER", "text": "rolling back", "reply_count": 2}
    client = _index_client([SlackApiError("rate limited", {"ok": False, "error": "ratelimited"}), {"messages": [root]}])
    slack = _patched_slack(client)
    try:
        with patch(f"{DAILY_SUMMARY}.build_system_one_client") as ranker:
            ranker.return_value.decide.return_value = SystemOneResult(model="jev", answers={}, input_tokens=None)
            # A rate-limited channel read is not a quiet channel, so the build fails instead of caching a partial index.
            with pytest.raises(DailySummaryIndexNotReady):
                build_workspace_index(workspace_integration)
            assert cached_index(workspace_integration) is None
            # The failed build gave its lock back, so the retry builds at once instead of reporting a build under way.
            assert build_workspace_index(workspace_integration) == 1
    finally:
        slack.stop()


@pytest.mark.django_db
def test_a_later_hour_rebuilds_the_index_so_late_runs_see_the_day(workspace_integration) -> None:
    cache.clear()
    client = _index_client([{"messages": []}, {"messages": []}])
    slack = _patched_slack(client)
    try:
        with patch(f"{DAILY_SUMMARY}.build_system_one_client"):
            with time_machine.travel(datetime(2026, 11, 9, 8, 5, tzinfo=UTC), tick=False):
                build_workspace_index(workspace_integration)
                build_workspace_index(workspace_integration)
            with time_machine.travel(datetime(2026, 11, 9, 9, 5, tzinfo=UTC), tick=False):
                build_workspace_index(workspace_integration)
    finally:
        slack.stop()

    # Runs in one hour share a build; the next hour's runs get a fresh one, while the first build is still cached.
    assert client.conversations_history.call_count == 2
