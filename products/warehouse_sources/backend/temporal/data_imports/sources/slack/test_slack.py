from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache as django_cache

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack import (
    SlackResumeConfig,
    _channel_messages_generator,
    _fetch_all_channels,
    _fetch_all_channels_cached,
    _fetch_channels_by_type,
    _join_public_channels,
    auth_test_user_id,
    manual_cache_id,
    slack_source,
)


def _make_response(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.status_code = 200
    return response


def _make_page(messages: list[dict[str, Any]], next_cursor: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "messages": messages,
        "response_metadata": {"next_cursor": next_cursor},
    }


class TestChannelMessagesGeneratorResumable:
    @parameterized.expand(
        [
            (
                "multi_page_saves_each_non_final_cursor",
                [
                    _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor="cursor_page_3"),
                    _make_page([{"ts": "1700000002.000001"}], next_cursor=""),
                ],
                None,
                3,
                [
                    SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts=None),
                    SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_3", oldest_ts=None),
                ],
            ),
            (
                "single_page_does_not_save",
                [_make_page([{"ts": "1700000000.000001"}], next_cursor="")],
                None,
                1,
                [],
            ),
            (
                "oldest_ts_is_persisted_in_state",
                [
                    _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor=""),
                ],
                "1699000000.0",
                2,
                [SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts="1699000000.0")],
            ),
            (
                "empty_first_page_is_noop",
                [_make_page([], next_cursor="")],
                None,
                0,
                [],
            ),
            (
                "multi_page_saves_after_thread_replies_are_drained",
                # page 1 has a parent with 2 replies -> conversations.replies is called
                # between page 1 and page 2. save_state must fire only after the replies
                # have been yielded, producing exactly one save with cursor_page_2.
                [
                    _make_page(
                        [{"ts": "1700000000.000001", "reply_count": 2}],
                        next_cursor="cursor_page_2",
                    ),
                    _make_page(
                        [
                            # conversations.replies includes the parent; it gets filtered.
                            {"ts": "1700000000.000001", "thread_ts": "1700000000.000001"},
                            {"ts": "1700000000.000002", "thread_ts": "1700000000.000001"},
                            {"ts": "1700000000.000003", "thread_ts": "1700000000.000001"},
                        ],
                        next_cursor="",
                    ),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor=""),
                ],
                None,
                4,  # 1 parent + 2 replies from page 1 + 1 message on page 2
                [SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts=None)],
            ),
        ]
    )
    def test_fresh_run(
        self,
        _name: str,
        pages: list[dict[str, Any]],
        oldest_ts: str | None,
        expected_item_count: int,
        expected_save_calls: list[SlackResumeConfig],
    ) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.load_state.return_value = None

        responses = [_make_response(p) for p in pages]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=oldest_ts))

        assert len(items) == expected_item_count
        assert resume_mgr.save_state.call_count == len(expected_save_calls)
        actual_save_args = [call.args[0] for call in resume_mgr.save_state.call_args_list]
        assert actual_save_args == expected_save_calls

    def test_resume_starts_from_saved_cursor_and_skips_initial_request(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.load_state.return_value = SlackResumeConfig(
            channel_id="C123", next_cursor="saved_cursor", oldest_ts="1699000000.0"
        )

        pages = [_make_page([{"ts": "1700000500.000001"}], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=None))

        assert len(items) == 1
        assert mock_get.call_count == 1
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["cursor"] == "saved_cursor"
        assert call_kwargs["params"]["oldest"] == "1699000000.0"
        resume_mgr.save_state.assert_not_called()

    def test_resume_state_for_different_channel_is_ignored(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.load_state.return_value = SlackResumeConfig(
            channel_id="C_OTHER", next_cursor="wrong_cursor", oldest_ts="9999"
        )

        pages = [_make_page([{"ts": "1700000000.000001"}], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts="original_oldest"))

        call_kwargs = mock_get.call_args.kwargs
        assert "cursor" not in call_kwargs["params"]
        assert call_kwargs["params"]["oldest"] == "original_oldest"


def _make_channel_page(channels: list[dict[str, Any]], next_cursor: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": next_cursor},
    }


class TestFetchChannelsByType:
    @parameterized.expand(
        [
            (
                "public_with_authed_user_ignores_user_scoping",
                "public_channel",
                "U_INSTALLER",
                "https://slack.com/api/conversations.list",
                False,
            ),
            (
                "private_with_authed_user_scopes_to_installer",
                "private_channel",
                "U_INSTALLER",
                "https://slack.com/api/users.conversations",
                True,
            ),
            (
                "private_without_authed_user_omits_user_param",
                "private_channel",
                None,
                "https://slack.com/api/users.conversations",
                False,
            ),
        ]
    )
    def test_routes_to_expected_endpoint(
        self,
        _name: str,
        channel_type: str,
        authed_user: str | None,
        expected_url: str,
        expects_user_param: bool,
    ) -> None:
        responses = [_make_response(_make_channel_page([{"id": "X1", "name": "x"}]))]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_channels_by_type("token", channel_type, authed_user=authed_user)

        assert channels == [{"id": "X1", "name": "x"}]
        assert mock_get.call_args.args[0] == expected_url
        params = mock_get.call_args.kwargs["params"]
        assert params["types"] == channel_type
        if expects_user_param:
            assert params["user"] == authed_user
        else:
            assert "user" not in params

    def test_paginates_until_cursor_empty(self) -> None:
        pages = [
            _make_channel_page([{"id": "C1", "name": "a"}], next_cursor="page2"),
            _make_channel_page([{"id": "C2", "name": "b"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_channels_by_type("token", "public_channel")

        assert [c["id"] for c in channels] == ["C1", "C2"]
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[1].kwargs["params"]["cursor"] == "page2"


class TestFetchAllChannels:
    def test_combines_public_and_private(self) -> None:
        pages = [
            _make_channel_page([{"id": "C1", "name": "general"}], next_cursor=""),
            _make_channel_page([{"id": "G1", "name": "secret"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_all_channels("token", authed_user="U_INSTALLER")

        assert [c["id"] for c in channels] == ["C1", "G1"]
        assert mock_get.call_count == 2
        first_url, second_url = mock_get.call_args_list[0].args[0], mock_get.call_args_list[1].args[0]
        assert first_url == "https://slack.com/api/conversations.list"
        assert second_url == "https://slack.com/api/users.conversations"
        # public call must not carry user= scoping; private call must
        assert "user" not in mock_get.call_args_list[0].kwargs["params"]
        assert mock_get.call_args_list[1].kwargs["params"]["user"] == "U_INSTALLER"


class TestFetchAllChannelsCached:
    def setup_method(self) -> None:
        django_cache.clear()

    def teardown_method(self) -> None:
        django_cache.clear()

    def test_second_call_uses_cache(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            return_value=[{"id": "C1", "name": "general"}],
        ) as mock_fetch:
            first = _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")
            second = _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")

        assert first == second == [{"id": "C1", "name": "general"}]
        assert mock_fetch.call_count == 1

    def test_different_integrations_get_independent_cache_entries(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            side_effect=[[{"id": "A1", "name": "a"}], [{"id": "B1", "name": "b"}]],
        ) as mock_fetch:
            a = _fetch_all_channels_cached(cache_id="1", access_token="token", authed_user="U1")
            b = _fetch_all_channels_cached(cache_id="2", access_token="token", authed_user="U1")

        assert a == [{"id": "A1", "name": "a"}]
        assert b == [{"id": "B1", "name": "b"}]
        assert mock_fetch.call_count == 2

    def test_force_refresh_refetches_and_overwrites_cache(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            side_effect=[[{"id": "C1", "name": "general"}], [{"id": "C2", "name": "renamed"}]],
        ) as mock_fetch:
            first = _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")
            second = _fetch_all_channels_cached(
                cache_id="42", access_token="token", authed_user="U_INSTALLER", force_refresh=True
            )
            third = _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")

        assert first == [{"id": "C1", "name": "general"}]
        assert second == [{"id": "C2", "name": "renamed"}]
        # Third call hits the cache populated by the force_refresh write.
        assert third == [{"id": "C2", "name": "renamed"}]
        assert mock_fetch.call_count == 2

    def test_force_refresh_does_not_evict_on_failure(self) -> None:
        # If the upstream fetch raises, the previous cached value must remain so
        # concurrent readers continue to see stale-but-valid data.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            return_value=[{"id": "C1", "name": "general"}],
        ):
            _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            side_effect=RuntimeError("rate limited"),
        ):
            try:
                _fetch_all_channels_cached(
                    cache_id="42", access_token="token", authed_user="U_INSTALLER", force_refresh=True
                )
            except RuntimeError:
                pass

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            return_value=[{"id": "WRONG", "name": "should_not_be_called"}],
        ) as mock_fetch:
            after = _fetch_all_channels_cached(cache_id="42", access_token="token", authed_user="U_INSTALLER")

        assert after == [{"id": "C1", "name": "general"}]
        assert mock_fetch.call_count == 0


class TestSlackSourceGetSchemasForceRefresh:
    def setup_method(self) -> None:
        django_cache.clear()

    def teardown_method(self) -> None:
        django_cache.clear()

    def _build_mocks(self) -> tuple[Any, Any]:
        config = MagicMock()
        config.slack_access_token = None
        config.slack_integration_id = 42

        integration = MagicMock()
        integration.id = 42
        integration.access_token = "token"
        integration.config = {"authed_user": {"id": "U_INSTALLER"}}

        return config, integration

    def test_force_refresh_bypasses_channels_cache(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config, integration = self._build_mocks()
        source = SlackSource()

        with (
            patch.object(source, "get_oauth_integration", return_value=integration),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
                side_effect=[[{"id": "C1", "name": "general"}], [{"id": "C2", "name": "renamed"}]],
            ) as mock_fetch,
        ):
            first = source.get_schemas(config, team_id=1)
            cached = source.get_schemas(config, team_id=1)
            forced = source.get_schemas(config, team_id=1, force_refresh=True)

        # Two upstream fetches total: the first cold call and the force_refresh call.
        # The middle call must be a cache hit.
        assert mock_fetch.call_count == 2

        def channel_names(schemas: Any) -> set[str]:
            return {s.name for s in schemas if s.name not in ENDPOINTS}

        assert channel_names(first) == {"C1"}
        assert channel_names(cached) == {"C1"}
        assert channel_names(forced) == {"C2"}

    def test_channel_schemas_are_webhook_only(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config, integration = self._build_mocks()
        source = SlackSource()

        with (
            patch.object(source, "get_oauth_integration", return_value=integration),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
                return_value=[{"id": "C1", "name": "general"}],
            ),
        ):
            schemas = source.get_schemas(config, team_id=1)

        channel = next(s for s in schemas if s.name == "C1")
        # Webhook is the only valid sync method: full-refresh would wipe the table and
        # reload nothing, incremental/append have no polling endpoint to read from.
        assert channel.supports_webhooks is True
        assert channel.webhook_only is True
        assert channel.supports_incremental is False
        assert channel.supports_append is False
        assert channel.incremental_fields == []


class TestSlackSourceChannelsEndpoint:
    def setup_method(self) -> None:
        django_cache.clear()

    def teardown_method(self) -> None:
        django_cache.clear()

    def _build_source(self, authed_user: str | None) -> Any:
        return slack_source(
            access_token="token",
            cache_id="42",
            endpoint="$channels",
            team_id=1,
            job_id="job-1",
            webhook_source_manager=MagicMock(spec=WebhookSourceManager),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
            authed_user=authed_user,
        )

    @parameterized.expand(
        [
            (
                "with_authed_user",
                "U_INSTALLER",
                [{"id": "C1", "name": "general"}, {"id": "G1", "name": "secret"}],
            ),
            (
                "without_authed_user",
                None,
                [],
            ),
        ]
    )
    def test_uses_fetch_all_channels_and_threads_authed_user(
        self,
        _name: str,
        authed_user: str | None,
        sample: list[dict[str, Any]],
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            return_value=sample,
        ) as mock_fetch:
            response = self._build_source(authed_user=authed_user)
            items = list(response.items())

        assert items == sample
        mock_fetch.assert_called_once_with("token", authed_user)


class TestSlackSourceChannelMessagesWebhookOnly:
    def _build_channel_source(self, webhook_manager: Any) -> Any:
        return slack_source(
            access_token="token",
            cache_id="42",
            endpoint="C123",
            team_id=1,
            job_id="job-1",
            webhook_source_manager=webhook_manager,
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
            channel_id="C123",
        )

    @parameterized.expand(
        [
            ("webhook_enabled", True, ["webhook-item"], True),
            ("webhook_disabled", False, [], False),
        ]
    )
    def test_channel_messages_are_webhook_only_and_never_backfill(
        self,
        _name: str,
        webhook_on: bool,
        expected_items: list[Any],
        expect_get_items_called: bool,
    ) -> None:
        manager = MagicMock(spec=WebhookSourceManager)
        manager.webhook_enabled = AsyncMock(return_value=webhook_on)
        manager.get_items.return_value = ["webhook-item"]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._channel_messages_generator"
        ) as mock_backfill:
            response = self._build_channel_source(manager)
            items = list(response.items())

        # Webhook mode is activated from the first sync (skip the initial-sync-complete gate).
        # When disabled the table stays empty until webhook events arrive — never a historical backfill.
        manager.webhook_enabled.assert_awaited_once_with(webhook_only=True)
        assert items == expected_items
        assert manager.get_items.called == expect_get_items_called
        mock_backfill.assert_not_called()


class TestResolveAccessToken:
    _SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.slack.source"

    def test_token_uses_pasted_token_without_an_integration(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict({"slack_access_token": "xoxb-abc"})
        source = SlackSource()

        with (
            patch(f"{self._SOURCE_MODULE}.auth_test_user_id", return_value="UBOT") as mock_auth_test,
            patch.object(source, "get_oauth_integration") as mock_get_integration,
        ):
            access_token, authed_user, cache_id = source._resolve_access_token(config, team_id=1)

        assert access_token == "xoxb-abc"
        assert authed_user == "UBOT"
        assert cache_id == manual_cache_id("xoxb-abc")
        # The bring-your-own path must never touch an Integration row — that's what keeps it
        # off the shared PostHog app.
        mock_get_integration.assert_not_called()
        mock_auth_test.assert_called_once_with("xoxb-abc")

    def test_legacy_source_resolves_via_linked_integration(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict({"slack_integration_id": 42})
        source = SlackSource()

        integration = MagicMock()
        integration.id = 42
        integration.access_token = "token"
        integration.config = {"authed_user": {"id": "U_INSTALLER"}}

        with patch.object(source, "get_oauth_integration", return_value=integration) as mock_get_integration:
            access_token, authed_user, cache_id = source._resolve_access_token(config, team_id=1)

        assert (access_token, authed_user, cache_id) == ("token", "U_INSTALLER", "42")
        mock_get_integration.assert_called_once_with(42, 1)

    def test_token_takes_precedence_over_a_legacy_integration(self) -> None:
        # Converting a legacy source in place: once a bot token is pasted, the stale integration id
        # is ignored and no Integration lookup happens.
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict({"slack_access_token": "xoxb-new", "slack_integration_id": 42})
        source = SlackSource()

        with (
            patch(f"{self._SOURCE_MODULE}.auth_test_user_id", return_value="UBOT"),
            patch.object(source, "get_oauth_integration") as mock_get_integration,
        ):
            access_token, _authed_user, _cache_id = source._resolve_access_token(config, team_id=1)

        assert access_token == "xoxb-new"
        mock_get_integration.assert_not_called()

    def test_no_credentials_raises(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict({})
        source = SlackSource()

        try:
            source._resolve_access_token(config, team_id=1)
            raise AssertionError("expected ValueError for missing credentials")
        except ValueError as e:
            assert "access token not found" in str(e)


class TestAuthTestUserId:
    @parameterized.expand(
        [
            ("ok_returns_user_id", {"ok": True, "user_id": "U1"}, "U1"),
            ("not_ok_returns_none", {"ok": False, "error": "invalid_auth"}, None),
            ("ok_without_user_id_returns_none", {"ok": True}, None),
        ]
    )
    def test_parses_response(self, _name: str, payload: dict[str, Any], expected: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            return_value=_make_response(payload),
        ):
            assert auth_test_user_id("token") == expected

    def test_network_error_returns_none(self) -> None:
        # A failed auth.test must not blow up discovery — it falls back to unscoped private-channel
        # listing rather than crashing the sync.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=RuntimeError("boom"),
        ):
            assert auth_test_user_id("token") is None


class TestJoinPublicChannels:
    _POST = "products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack._slack_post"

    def test_only_public_non_member_channels_are_joined(self) -> None:
        channels: list[dict[str, Any]] = [
            {"id": "C_PUB_NEW"},  # public, not a member -> join
            {"id": "C_PUB_MEMBER", "is_member": True},  # already in -> skip
            {"id": "C_PRIVATE", "is_private": True},  # private -> skip (can't self-join)
            {"id": "C_ARCHIVED", "is_archived": True},  # archived -> skip
        ]
        with patch(self._POST, return_value=_make_response({"ok": True})) as mock_post:
            joined = _join_public_channels("xoxb", channels)

        assert joined == 1
        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["data"] == {"channel": "C_PUB_NEW"}

    def test_already_in_channel_is_not_counted_or_raised(self) -> None:
        # A race where the bot joined between listing and the join call must be a silent no-op.
        channels = [{"id": "C1"}]
        with patch(self._POST, return_value=_make_response({"ok": False, "error": "already_in_channel"})):
            assert _join_public_channels("xoxb", channels) == 0

    def test_missing_scope_raises(self) -> None:
        # Auto-join silently doing nothing would be worse than failing — surface the missing scope.
        channels = [{"id": "C1"}]
        with patch(self._POST, return_value=_make_response({"ok": False, "error": "missing_scope"})):
            try:
                _join_public_channels("xoxb", channels)
                raise AssertionError("expected an error for missing channels:join scope")
            except Exception as e:
                assert "channels:join" in str(e)


class TestGetSchemasAutoJoin:
    _SRC = "products.warehouse_sources.backend.temporal.data_imports.sources.slack.source"

    def setup_method(self) -> None:
        django_cache.clear()

    def teardown_method(self) -> None:
        django_cache.clear()

    @parameterized.expand(
        [
            ("toggle_on_joins", True, "xoxb-token", True),
            ("toggle_off_skips", False, "xoxb-token", False),
            ("legacy_source_never_joins", True, None, False),
        ]
    )
    def test_join_is_gated_on_toggle_and_byo_token(
        self, _name: str, enabled: bool, token: str | None, expect_join: bool
    ) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = MagicMock()
        config.slack_access_token = token
        config.slack_integration_id = 42 if token is None else None
        config.join_public_channels.enabled = enabled

        integration = MagicMock()
        integration.id = 42
        integration.access_token = "legacy-token"
        integration.config = {"authed_user": {"id": "U_INSTALLER"}}

        source = SlackSource()
        with (
            patch(f"{self._SRC}.auth_test_user_id", return_value="UBOT"),
            patch.object(source, "get_oauth_integration", return_value=integration),
            patch(f"{self._SRC}.join_public_channels") as mock_join,
            patch(f"{self._SRC}.get_channels", return_value=[]),
        ):
            source.get_schemas(config, team_id=1)

        assert mock_join.called == expect_join

    def test_byo_source_joins_by_default(self) -> None:
        # The toggle defaults on: a bring-your-own source that doesn't set it explicitly still
        # auto-joins. (Legacy OAuth sources are held off by the token gate — covered above.)
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict({"slack_access_token": "xoxb-token"})
        assert config.join_public_channels is not None
        assert config.join_public_channels.enabled is True

        source = SlackSource()
        with (
            patch(f"{self._SRC}.auth_test_user_id", return_value="UBOT"),
            patch(f"{self._SRC}.join_public_channels") as mock_join,
            patch(f"{self._SRC}.get_channels", return_value=[]),
        ):
            source.get_schemas(config, team_id=1)

        mock_join.assert_called_once()

    def test_toggle_can_be_explicitly_disabled(self) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import (
            SlackSourceConfig,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.source import SlackSource

        config = SlackSourceConfig.from_dict(
            {"slack_access_token": "xoxb-token", "join_public_channels": {"enabled": False}}
        )
        assert config.join_public_channels is not None
        assert config.join_public_channels.enabled is False

        source = SlackSource()
        with (
            patch(f"{self._SRC}.auth_test_user_id", return_value="UBOT"),
            patch(f"{self._SRC}.join_public_channels") as mock_join,
            patch(f"{self._SRC}.get_channels", return_value=[]),
        ):
            source.get_schemas(config, team_id=1)

        mock_join.assert_not_called()
