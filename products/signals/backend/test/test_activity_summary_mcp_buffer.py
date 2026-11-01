import datetime
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import redis
import fakeredis
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.activity_summary import mcp_buffer
from products.signals.backend.activity_summary.inputs import McpRead, user_mcp_records
from products.signals.backend.activity_summary.mcp_buffer import (
    CIRCUIT_OPEN_SECONDS,
    DIRTY_KEY,
    BufferSettings,
    McpIntentBuffer,
    count_key,
    records_key,
)

NOW = datetime.datetime(2026, 10, 20, 12, tzinfo=datetime.UTC)
DAY = "20261020"
TEAM_ID = 1
USER_ID = 7


def _dropped(reason: str) -> float:
    return REGISTRY.get_sample_value("activity_summary_mcp_intent_records_total", {"outcome": reason}) or 0.0


@time_machine.travel(NOW, tick=False)
class TestMcpIntentBuffer(SimpleTestCase):
    def setUp(self) -> None:
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.now = 1000.0

    def _buffer(self, **kwargs) -> McpIntentBuffer:
        buffer = McpIntentBuffer(start_thread=False, clock=lambda: self.now, **kwargs)
        buffer.buffer_settings = BufferSettings(team_ids=frozenset({TEAM_ID}), calls_per_day=2, buffer_days=10)
        return buffer

    def _append(self, buffer: McpIntentBuffer, intent: str, team_id: int = TEAM_ID) -> None:
        buffer.append(team_id=team_id, user_id=USER_ID, session_id="s|1", route_name="insight-list", intent=intent)

    def test_flush_writes_the_trimmed_list_the_count_the_ttl_and_the_dirty_member(self) -> None:
        buffer = self._buffer(redis_client=lambda: self.redis)
        for intent in ("first", "second", "third"):
            self._append(buffer, intent)
        self._append(buffer, "not enrolled", team_id=2)

        buffer.flush()

        key = records_key(TEAM_ID, USER_ID, DAY)
        assert [record.split("|")[1:] for record in self.redis.lrange(key, 0, -1)] == [
            ["s 1", "insight-list", "second"],
            ["s 1", "insight-list", "third"],
        ]
        assert self.redis.get(count_key(TEAM_ID, USER_ID, DAY)) == "3"
        assert 0 < self.redis.ttl(key) <= 10 * 24 * 3600
        assert 0 < self.redis.ttl(count_key(TEAM_ID, USER_ID, DAY)) <= 10 * 24 * 3600
        assert self.redis.smembers(DIRTY_KEY) == {f"{TEAM_ID}:{USER_ID}"}
        assert self.redis.keys("as:mcp:2:*") == []

    def test_a_full_queue_drops_the_record(self) -> None:
        buffer = self._buffer(queue_size=1, redis_client=lambda: self.redis)
        dropped = _dropped("dropped_queue_full")

        self._append(buffer, "kept")
        self._append(buffer, "dropped")
        buffer.flush()

        assert _dropped("dropped_queue_full") == dropped + 1
        assert self.redis.get(count_key(TEAM_ID, USER_ID, DAY)) == "1"

    def test_a_failed_flush_opens_the_circuit_until_the_cool_down_ends(self) -> None:
        client = MagicMock(side_effect=redis.TimeoutError("timed out"))
        buffer = self._buffer(redis_client=client)
        self._append(buffer, "lost to the error")
        buffer.flush()
        client.side_effect = None
        client.return_value = self.redis

        self.now += CIRCUIT_OPEN_SECONDS - 1
        self._append(buffer, "lost to the open circuit")
        buffer.flush()
        assert client.call_count == 1
        assert self.redis.keys("as:mcp:*") == []

        self.now += 2
        self._append(buffer, "written")
        buffer.flush()
        assert [record.split("|")[3] for record in self.redis.lrange(records_key(TEAM_ID, USER_ID, DAY), 0, -1)] == [
            "written"
        ]


class TestUserMcpRecords(SimpleTestCase):
    def setUp(self) -> None:
        self.redis = fakeredis.FakeRedis()

    def _write(self, at: datetime.datetime, session_id: str, intent: str) -> None:
        buffer = McpIntentBuffer(start_thread=False, redis_client=lambda: self.redis)
        buffer.buffer_settings = BufferSettings(team_ids=frozenset({TEAM_ID}), calls_per_day=2, buffer_days=10)
        with time_machine.travel(at, tick=False):
            buffer.append(
                team_id=TEAM_ID, user_id=USER_ID, session_id=session_id, route_name="insight-list", intent=intent
            )
        buffer.flush()

    def test_reads_what_the_writer_wrote_inside_the_window_and_counts_trimmed_days(self) -> None:
        older = NOW - datetime.timedelta(days=2)
        for minutes, intent in ((0, "trimmed"), (1, "before the window"), (2, "kept")):
            self._write(older + datetime.timedelta(minutes=minutes), "s|1", intent)
        self._write(NOW - datetime.timedelta(days=1), "", "kept too")
        self._write(NOW, "s2", "at the end of the window")
        start = older + datetime.timedelta(minutes=1, seconds=30)

        read = user_mcp_records(TEAM_ID, USER_ID, start, NOW, max_days=10, redis_client=lambda: self.redis)
        newest_days = user_mcp_records(TEAM_ID, USER_ID, start, NOW, max_days=2, redis_client=lambda: self.redis)

        assert [(record.session_id, record.route_name, record.intent) for record in read.records] == [
            ("s 1", "insight-list", "kept"),
            ("", "insight-list", "kept too"),
        ]
        assert read.records[0].at == older + datetime.timedelta(minutes=2)
        assert (read.truncated_days, read.read_error) == (1, False)
        assert [record.intent for record in newest_days.records] == ["kept too"]
        assert newest_days.truncated_days == 0

    @parameterized.expand(
        [
            ("missing keys are an empty read", None, McpRead()),
            (
                "a timeout is an empty read with the error set",
                redis.TimeoutError("timed out"),
                McpRead(read_error=True),
            ),
            (
                "a refused connection is an empty read with the error set",
                redis.ConnectionError(),
                McpRead(read_error=True),
            ),
        ]
    )
    def test_a_missing_or_failed_read_never_raises(
        self, _name: str, error: Exception | None, expected: McpRead
    ) -> None:
        client = MagicMock(side_effect=error, return_value=self.redis)

        read = user_mcp_records(
            TEAM_ID, USER_ID, NOW - datetime.timedelta(days=3), NOW, max_days=10, redis_client=client
        )

        assert read == expected


@time_machine.travel(NOW, tick=False)
class TestMcpIntentCapture(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.redis_client = MagicMock(side_effect=redis.ConnectionError("unreachable"))
        self.buffer = McpIntentBuffer(start_thread=False, redis_client=self.redis_client)
        self.buffer.buffer_settings = BufferSettings(team_ids=frozenset({self.team.id}))
        patcher = patch.object(mcp_buffer, "BUFFER", self.buffer)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.logout()

    def _personal_api_key(self) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="MCP", user=self.user, secure_value=hash_key_value(value), scopes=["dashboard:read"]
        )
        return value

    def _oauth_token(self, sandbox_task_id: UUID | None) -> str:
        application = OAuthApplication.objects.create(
            name="MCP",
            client_id="mcp-client",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        return OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_mcp_test_token",
            scope="dashboard:read",
            expires=timezone.now() + datetime.timedelta(hours=1),
            scoped_teams=[self.team.id],
            sandbox_task_id=sandbox_task_id,
        ).token

    @parameterized.expand(
        [
            ("personal api key", "personal_api_key", {}, True),
            ("own oauth token", "oauth", {}, True),
            ("sandbox oauth token", "sandbox", {}, False),
            ("no mcp client header", "personal_api_key", {"HTTP_X_POSTHOG_CLIENT": "posthog-js"}, False),
            ("no intent", "personal_api_key", {"HTTP_X_POSTHOG_INTENT": ""}, False),
            ("team not enrolled", "personal_api_key", {"enrolled": False}, False),
            ("setting off", "personal_api_key", {"setting": False}, False),
        ]
    )
    def test_buffers_only_a_person_s_own_mcp_reads(
        self, _name: str, credential: str, overrides: dict, buffered: bool
    ) -> None:
        if credential == "personal_api_key":
            token = self._personal_api_key()
        else:
            token = self._oauth_token(UUID("019f4c2a-0000-7000-8000-0000000000aa") if credential == "sandbox" else None)
        if overrides.pop("enrolled", True) is False:
            self.buffer.buffer_settings = BufferSettings()
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {token}",
            "HTTP_X_POSTHOG_CLIENT": "mcp",
            "HTTP_X_POSTHOG_INTENT": "Checking why weekly signups dropped",
            "HTTP_X_POSTHOG_MCP_SESSION_ID": "session-1",
            **{key: value for key, value in overrides.items() if key.startswith("HTTP_")},
        }

        with self.settings(ACTIVITY_SUMMARY_MCP_BUFFER_ENABLED=overrides.get("setting", True)):
            response = self.client.get(f"/api/environments/{self.team.id}/dashboards/", **headers)

        assert response.status_code == 200, response.content
        self.redis_client.assert_not_called()
        self.redis_client.side_effect = None
        self.redis_client.return_value = self.redis
        self.buffer.flush()
        records = self.redis.lrange(records_key(self.team.id, self.user.id, DAY), 0, -1)
        if buffered:
            assert [record.split("|")[1:] for record in records] == [
                ["session-1", "project_dashboards-list", "Checking why weekly signups dropped"]
            ]
        else:
            assert records == []
