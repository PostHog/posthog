from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.utils import timezone

from slack_sdk.errors import SlackApiError

from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.channel_metadata import (
    GROUP_LOOKUP_RETRY_SECONDS,
    METADATA_REFRESH_SECONDS,
    OwnerGroup,
    parse_owner_groups,
    refresh_channel_metadata,
    schedule_channel_metadata_refresh,
)


def _slack(
    channel: dict | None = None, error: Exception | None = None, missing_scopes: frozenset = frozenset()
) -> MagicMock:
    slack = MagicMock()
    slack.integration.integration_id = "T01"
    slack.missing_scopes.return_value = missing_scopes
    slack.client.usergroups_list.return_value = {"usergroups": [{"id": "S0123", "handle": "team-replay"}]}
    if error is not None:
        slack.client.conversations_info.side_effect = error
    else:
        slack.client.conversations_info.return_value = {"channel": channel or {}}
    return slack


class TestParseOwnerGroups:
    @pytest.mark.parametrize(
        "texts,expected",
        [
            (("Owned by <!subteam^S0123|@team-replay>",), [OwnerGroup(id="S0123", handle="team-replay")]),
            (("Ping <!subteam^S0123>",), [OwnerGroup(id="S0123")]),
            (
                ("<!subteam^S0123> on call", "Run by <!subteam^S0123|@team-replay> and <!subteam^S0456|@infra>"),
                [OwnerGroup(id="S0123", handle="team-replay"), OwnerGroup(id="S0456", handle="infra")],
            ),
            (
                ("Owned by <!subteam^S0123|@team-replay>", "Escalate to <!subteam^S0123>"),
                [OwnerGroup(id="S0123", handle="team-replay")],
            ),
            (("Ask <@U0123> or <!here>",), []),
        ],
    )
    def test_reads_each_tagged_group_once(self, texts: tuple[str, ...], expected: list[OwnerGroup]) -> None:
        assert parse_owner_groups(*texts) == expected


@pytest.mark.django_db
class TestRefreshChannelMetadata:
    def test_stores_the_description_of_a_public_channel(self) -> None:
        slack = _slack(
            {
                "is_channel": True,
                "topic": {"value": "Replays and <!subteam^S0123|@team-replay>"},
                "purpose": {"value": "Session replay R&amp;D"},
            }
        )

        assert refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")

        channel = SlackChannel.objects.get(slack_workspace_id="T01", slack_channel_id="C01")
        assert (channel.topic, channel.purpose) == ("Replays and <!subteam^S0123|@team-replay>", "Session replay R&D")
        assert channel.owner_groups == [{"id": "S0123", "handle": "team-replay"}]

    @pytest.mark.parametrize(
        "missing_scopes,expected_handle",
        [(frozenset(), "team-replay"), (frozenset({"usergroups:read"}), "")],
    )
    def test_names_an_unlabeled_group_only_with_the_usergroups_scope(
        self, missing_scopes: frozenset, expected_handle: str
    ) -> None:
        cache.clear()
        slack = _slack(
            {"is_channel": True, "topic": {"value": "Owned by <!subteam^S0123>"}}, missing_scopes=missing_scopes
        )

        assert refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")

        channel = SlackChannel.objects.get(slack_channel_id="C01")
        assert channel.owner_groups == [{"id": "S0123", "handle": expected_handle}]

    def test_a_failed_group_lookup_keeps_the_handle_stored_before(self) -> None:
        cache.clear()
        SlackChannel.objects.create(
            slack_workspace_id="T01",
            slack_channel_id="C01",
            owner_groups=[{"id": "S0123", "handle": "team-replay"}],
        )
        slack = _slack({"is_channel": True, "topic": {"value": "Owned by <!subteam^S0123>"}})
        slack.client.usergroups_list.side_effect = TimeoutError()

        assert refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")

        assert SlackChannel.objects.get(slack_channel_id="C01").owner_groups == [
            {"id": "S0123", "handle": "team-replay"}
        ]

    @pytest.mark.parametrize(
        "read_in_flight,expected_handle,retries_soon",
        [(True, "", True), (False, "team-replay", False)],
    )
    def test_a_channel_that_loses_the_group_lookup_race_retries_soon(
        self, read_in_flight: bool, expected_handle: str, retries_soon: bool
    ) -> None:
        cache.clear()
        slack = _slack({"is_channel": True, "topic": {"value": "Owned by <!subteam^S0123>"}})
        slack.integration.id = 7
        slot = "slack_app_channel_metadata:7:C01"
        with time_machine.travel(datetime(2026, 11, 27, 9, 0, tzinfo=UTC), tick=False) as traveller:
            cache.set(slot, 1, timeout=METADATA_REFRESH_SECONDS)
            if read_in_flight:
                cache.set("slack_app_usergroup_handles:T01:read", 1, timeout=60)

            assert refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")
            traveller.shift(timedelta(seconds=GROUP_LOOKUP_RETRY_SECONDS + 60))

            assert (cache.get(slot) is None) == retries_soon
        assert SlackChannel.objects.get(slack_channel_id="C01").owner_groups == [
            {"id": "S0123", "handle": expected_handle}
        ]

    def test_channels_of_one_workspace_share_one_group_lookup(self) -> None:
        cache.clear()
        slack = _slack({"is_channel": True, "topic": {"value": "Owned by <!subteam^S0123>"}})

        for channel_id in ("C01", "C02"):
            refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id=channel_id)

        assert slack.client.usergroups_list.call_count == 1
        assert SlackChannel.objects.get(slack_channel_id="C02").owner_groups == [
            {"id": "S0123", "handle": "team-replay"}
        ]

    @pytest.mark.parametrize(
        "channel",
        [
            {"is_channel": True, "is_private": True, "topic": {"value": "secret"}},
            {"is_channel": True, "is_ext_shared": True, "topic": {"value": "shared"}},
            {"is_channel": True, "is_pending_ext_shared": True, "topic": {"value": "invite sent"}},
            {"is_im": True},
        ],
    )
    def test_skips_channels_whose_page_the_organization_must_not_read(self, channel: dict) -> None:
        assert not refresh_channel_metadata(_slack(channel), slack_workspace_id="T01", slack_channel_id="C01")
        assert not SlackChannel.objects.filter(slack_channel_id="C01").exists()

    def test_a_channel_that_turned_private_loses_its_stored_description(self) -> None:
        SlackChannel.objects.create(
            slack_workspace_id="T01", slack_channel_id="C01", topic="Deal room", owner_groups=[{"id": "S01"}]
        )

        refresh_channel_metadata(
            _slack({"is_channel": True, "is_private": True}), slack_workspace_id="T01", slack_channel_id="C01"
        )

        channel = SlackChannel.objects.get(slack_channel_id="C01")
        assert (channel.topic, channel.owner_groups) == ("", [])

    @pytest.mark.parametrize(
        "error,expected_topic",
        [("ratelimited", "Replays"), ("missing_scope", ""), ("channel_not_found", "")],
    )
    def test_a_failed_lookup_clears_the_description_only_when_access_is_lost(
        self, error: str, expected_topic: str
    ) -> None:
        SlackChannel.objects.create(slack_workspace_id="T01", slack_channel_id="C01", topic="Replays")
        slack_error = SlackApiError(error, response={"ok": False, "error": error})

        assert not refresh_channel_metadata(_slack(error=slack_error), slack_workspace_id="T01", slack_channel_id="C01")
        assert SlackChannel.objects.get(slack_channel_id="C01").topic == expected_topic


@pytest.mark.django_db
class TestScheduleChannelMetadataRefresh:
    @pytest.mark.parametrize(
        "scope,channels,expected",
        [
            ("channels:read", ["C01", "C01", "C02"], ["C01", "C02"]),
            ("", ["C01"], []),
            ("channels:read", ["D01"], []),
        ],
    )
    def test_dispatches_once_per_readable_channel_per_day(
        self, workspace_integration, scope: str, channels: list[str], expected: list[str]
    ) -> None:
        cache.clear()
        workspace_integration.config = {"scope": scope}
        workspace_integration.save()

        with patch("products.slack_app.backend.tasks.refresh_slack_channel_metadata.delay") as dispatch:
            for channel in channels:
                shared, _, channel_id = channel.rpartition(":")
                schedule_channel_metadata_refresh(workspace_integration, channel_id, is_ext_shared=bool(shared))

        assert [call.kwargs["slack_channel_id"] for call in dispatch.call_args_list] == expected

    def test_a_rate_limited_lookup_waits_before_the_next_mention_retries(self, workspace_integration) -> None:
        cache.clear()
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()
        slack = _slack(error=SlackApiError("ratelimited", response={"ok": False, "error": "ratelimited"}))
        slack.integration.id = workspace_integration.id

        with patch("products.slack_app.backend.tasks.refresh_slack_channel_metadata.delay") as dispatch:
            schedule_channel_metadata_refresh(workspace_integration, "C01")
            refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")
            schedule_channel_metadata_refresh(workspace_integration, "C01")
            cache.delete(f"slack_app_channel_metadata:{workspace_integration.id}:C01")
            schedule_channel_metadata_refresh(workspace_integration, "C01")

        assert dispatch.call_count == 2

    def test_a_failed_dispatch_frees_the_day_for_the_next_mention(self, workspace_integration) -> None:
        cache.clear()
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()

        with patch(
            "products.slack_app.backend.tasks.refresh_slack_channel_metadata.delay", side_effect=[ConnectionError, None]
        ) as dispatch:
            schedule_channel_metadata_refresh(workspace_integration, "C01")
            schedule_channel_metadata_refresh(workspace_integration, "C01")

        assert dispatch.call_count == 2

    def test_a_mention_in_a_channel_that_became_shared_clears_its_description(self, workspace_integration) -> None:
        cache.clear()
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()
        channel = SlackChannel.objects.create(
            slack_workspace_id=workspace_integration.integration_id,
            slack_channel_id="C01",
            topic="Deal room",
            owner_groups=[{"id": "S01", "handle": "deals"}],
            approved_at=timezone.now(),
        )

        with patch("products.slack_app.backend.tasks.refresh_slack_channel_metadata.delay") as dispatch:
            schedule_channel_metadata_refresh(workspace_integration, "C01", is_ext_shared=True)

        channel.refresh_from_db()
        assert (channel.topic, channel.owner_groups) == ("", [])
        assert channel.approved_at is not None
        assert dispatch.call_count == 0

    def test_a_cache_outage_does_not_break_the_mention(self, workspace_integration) -> None:
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()

        with patch("products.slack_app.backend.services.channel_metadata.cache.add", side_effect=ConnectionError):
            schedule_channel_metadata_refresh(workspace_integration, "C01")
