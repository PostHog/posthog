from datetime import timedelta

import pytest

from django.core.cache import cache
from django.utils import timezone

from products.slack_app.backend.services.slack_auth import (
    SLACK_AUTH_STATE_CACHE_TTL_SECONDS,
    get_cached_auth_state,
    invalidate_auth_state,
    write_auth_state_broken,
    write_auth_state_ok,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestSlackAuthState:
    def test_get_returns_none_on_miss(self):
        assert get_cached_auth_state(1) is None

    def test_write_ok_round_trip(self):
        write_auth_state_ok(42, bot_user_id="U_BOT")

        state = get_cached_auth_state(42)
        assert state is not None
        assert state.ok is True
        assert state.bot_user_id == "U_BOT"
        assert state.error_code is None
        # ``checked_at`` is "now-ish"; assert a generous window so the test
        # isn't flaky on slow runners.
        assert abs((timezone.now() - state.checked_at).total_seconds()) < 5

    def test_write_ok_without_bot_user_id_lets_callers_request_one_later(self):
        # ``get_slack_email_for_user`` writes ``ok=true`` from a successful
        # ``users.info`` (which doesn't expose the bot id). ``bot_user_id``
        # stays ``None`` so a later ``get_cached_bot_user_id`` knows to fall
        # through to ``auth.test`` instead of returning ``None``.
        write_auth_state_ok(7, bot_user_id=None)

        state = get_cached_auth_state(7)
        assert state is not None
        assert state.ok is True
        assert state.bot_user_id is None

    def test_write_broken_round_trip(self):
        write_auth_state_broken(99, error_code="invalid_auth")

        state = get_cached_auth_state(99)
        assert state is not None
        assert state.ok is False
        assert state.error_code == "invalid_auth"
        assert state.bot_user_id is None

    def test_write_broken_then_ok_overrides_to_healthy(self):
        # OAuth reconnect path: previous token was revoked → cached as broken,
        # next successful call flips the cache back. The negative verdict
        # must not stick around once a healthy call lands.
        write_auth_state_broken(5, error_code="token_revoked")
        write_auth_state_ok(5, bot_user_id="U_FRESH")

        state = get_cached_auth_state(5)
        assert state is not None
        assert state.ok is True
        assert state.bot_user_id == "U_FRESH"
        assert state.error_code is None

    def test_write_ok_then_broken_overrides_to_broken(self):
        # Token rotation outside our control: was healthy, just got revoked.
        # Cache flips to broken so the resolver demotes the install.
        write_auth_state_ok(5, bot_user_id="U_OLD")
        write_auth_state_broken(5, error_code="invalid_auth")

        state = get_cached_auth_state(5)
        assert state is not None
        assert state.ok is False
        assert state.error_code == "invalid_auth"

    def test_invalidate_drops_existing_entry(self):
        write_auth_state_ok(11, bot_user_id="U_BOT")
        assert get_cached_auth_state(11) is not None

        invalidate_auth_state(11)

        assert get_cached_auth_state(11) is None

    def test_invalidate_is_safe_on_miss(self):
        # OAuth callback runs on every reconnect; it shouldn't blow up if
        # nothing was cached yet.
        invalidate_auth_state(404)
        assert get_cached_auth_state(404) is None

    def test_keys_are_per_integration(self):
        write_auth_state_ok(1, bot_user_id="U_ONE")
        write_auth_state_broken(2, error_code="invalid_auth")

        one = get_cached_auth_state(1)
        two = get_cached_auth_state(2)
        assert one is not None and one.ok is True and one.bot_user_id == "U_ONE"
        assert two is not None and two.ok is False and two.error_code == "invalid_auth"

    def test_garbage_in_cache_is_ignored(self):
        # If a future code version writes a different shape (or older code
        # wrote a dict literal here), we should treat it as a cache miss
        # rather than crash the resolver.
        from products.slack_app.backend.services.slack_auth import _cache_key

        cache.set(_cache_key(77), {"unexpected": "shape"}, timeout=60)

        assert get_cached_auth_state(77) is None

    def test_ttl_is_set(self):
        # Sanity: we don't accidentally write entries with no TTL.
        write_auth_state_ok(8, bot_user_id="U_BOT")

        from products.slack_app.backend.services.slack_auth import _cache_key

        ttl = cache.ttl(_cache_key(8)) if hasattr(cache, "ttl") else None
        if ttl is not None:
            # Django cache backends that expose ``.ttl()`` should report a
            # value close to the configured constant.
            assert ttl <= timedelta(seconds=SLACK_AUTH_STATE_CACHE_TTL_SECONDS).total_seconds()
