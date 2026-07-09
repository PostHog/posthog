"""Tests for ``cached_collect_thread_messages``.

The cache exists to absorb bursts: a chatty thread or a classifier-then-forwarder
pipeline shouldn't fan out into N Slack ``conversations.replies`` calls within a
few seconds. These tests pin the hit/miss/expiry/invalidation contract so future
refactors don't silently regress the rate-limit-friendliness of the path.
"""

import time

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.slack_messages import (
    THREAD_REPLIES_CACHE_TTL_SECONDS,
    cached_collect_thread_messages,
    invalidate_thread_messages_cache,
)


@pytest.fixture(autouse=True)
def clear_thread_cache():
    # Default cache is shared across the test process — clear before each test so
    # earlier hits don't poison subsequent assertions about miss/fetch behaviour.
    cache.clear()
    yield
    cache.clear()


class TestCachedCollectThreadMessages:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_TEST",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.slack = MagicMock(spec=SlackIntegration)
        self.slack.client = MagicMock()

    def test_miss_then_hit_calls_underlying_once(self):
        # Burst case: two callers within the TTL — the underlying Slack fetch must
        # run exactly once, with the second caller served from cache.
        sentinel = [{"user": "alice", "user_id": "U_A", "text": "hi", "ts": "1.000"}]
        with patch(
            "products.slack_app.backend.services.slack_messages.collect_thread_messages",
            return_value=sentinel,
        ) as mock_fetch:
            first = cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)
            second = cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)

        assert first == sentinel
        assert second == sentinel
        # The contract worth pinning is "one underlying fetch" — not identity, since
        # a serializing cache backend (Redis in CI) will hand back a deserialized
        # copy on the hit.
        assert mock_fetch.call_count == 1

    def test_distinct_threads_have_distinct_cache_entries(self):
        # Two separate (channel, thread_ts) tuples must not collide in the cache —
        # otherwise a busy workspace would see one thread's snapshot bleed into another's.
        with patch(
            "products.slack_app.backend.services.slack_messages.collect_thread_messages",
            side_effect=[
                [{"user": "alice", "user_id": "U_A", "text": "a", "ts": "1.000"}],
                [{"user": "bob", "user_id": "U_B", "text": "b", "ts": "2.000"}],
            ],
        ) as mock_fetch:
            a = cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)
            b = cached_collect_thread_messages(self.slack, self.integration, "C002", "2.000", our_bot_id=None)

        assert a[0]["user"] == "alice"
        assert b[0]["user"] == "bob"
        assert mock_fetch.call_count == 2

    def test_distinct_integrations_have_distinct_cache_entries(self):
        # Same channel + thread_ts across two installations of the app must not
        # collide — a Slack workspace can host multiple PostHog integrations.
        other_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_OTHER",
            sensitive_config={"access_token": "xoxb-other"},
        )
        with patch(
            "products.slack_app.backend.services.slack_messages.collect_thread_messages",
            side_effect=[
                [{"user": "alice", "user_id": "U_A", "text": "a", "ts": "1.000"}],
                [{"user": "bob", "user_id": "U_B", "text": "b", "ts": "1.000"}],
            ],
        ) as mock_fetch:
            a = cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)
            b = cached_collect_thread_messages(self.slack, other_integration, "C001", "1.000", our_bot_id=None)

        assert a[0]["user"] == "alice"
        assert b[0]["user"] == "bob"
        assert mock_fetch.call_count == 2

    def test_underlying_exception_does_not_populate_cache(self):
        # If Slack is sad and the underlying fetch raises, we MUST NOT cache the
        # failure — the next caller deserves a fresh attempt rather than a silent
        # "thread is empty" forever.
        with patch(
            "products.slack_app.backend.services.slack_messages.collect_thread_messages",
            side_effect=RuntimeError("slack down"),
        ) as mock_fetch:
            with pytest.raises(RuntimeError):
                cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)

            mock_fetch.side_effect = None
            mock_fetch.return_value = [{"user": "alice", "user_id": "U_A", "text": "hi", "ts": "1.000"}]
            recovered = cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)

        assert recovered[0]["user"] == "alice"
        assert mock_fetch.call_count == 2

    def test_ttl_expiry_triggers_refetch(self):
        # A snapshot that's older than the TTL should be re-fetched; otherwise a
        # long-lived workflow run would risk handing the agent indefinitely-stale data.
        # `cache.set` with a tiny TTL is the cheapest way to verify this without
        # waiting 10 seconds — patch `cache.set` to use a 1-second TTL instead.
        original_set = cache.set

        def short_lived_set(key, value, timeout=None, **kw):
            return original_set(key, value, timeout=1)

        sentinel = [{"user": "alice", "user_id": "U_A", "text": "hi", "ts": "1.000"}]
        with (
            patch.object(cache, "set", side_effect=short_lived_set),
            patch(
                "products.slack_app.backend.services.slack_messages.collect_thread_messages",
                return_value=sentinel,
            ) as mock_fetch,
        ):
            cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)
            time.sleep(1.1)
            cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)

        assert mock_fetch.call_count == 2

    def test_invalidate_drops_cached_snapshot(self):
        # Downstream callers that need a guaranteed-fresh fetch (e.g. just before a
        # destructive workflow decision) can drop the cache entry explicitly.
        sentinel = [{"user": "alice", "user_id": "U_A", "text": "hi", "ts": "1.000"}]
        with patch(
            "products.slack_app.backend.services.slack_messages.collect_thread_messages",
            return_value=sentinel,
        ) as mock_fetch:
            cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)
            invalidate_thread_messages_cache(self.integration.id, "C001", "1.000")
            cached_collect_thread_messages(self.slack, self.integration, "C001", "1.000", our_bot_id=None)

        assert mock_fetch.call_count == 2

    def test_default_ttl_is_short(self):
        # Guard rail: the cache is for absorbing bursts, not as a source of truth.
        # If someone bumps the TTL to "1 hour" they should fail this test and reconsider.
        assert THREAD_REPLIES_CACHE_TTL_SECONDS <= 30
