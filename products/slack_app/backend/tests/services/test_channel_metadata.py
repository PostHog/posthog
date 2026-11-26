import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from slack_sdk.errors import SlackApiError

from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.channel_metadata import (
    OwnerGroup,
    parse_owner_groups,
    refresh_channel_metadata,
    schedule_channel_metadata_refresh,
)


def _slack(channel: dict | None = None, error: Exception | None = None) -> MagicMock:
    slack = MagicMock()
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

    def test_a_failed_lookup_keeps_the_stored_description(self) -> None:
        SlackChannel.objects.create(slack_workspace_id="T01", slack_channel_id="C01", topic="Replays")
        error = SlackApiError("missing_scope", response={"ok": False, "error": "missing_scope"})

        assert not refresh_channel_metadata(_slack(error=error), slack_workspace_id="T01", slack_channel_id="C01")
        assert SlackChannel.objects.get(slack_channel_id="C01").topic == "Replays"


@pytest.mark.django_db
class TestScheduleChannelMetadataRefresh:
    @pytest.mark.parametrize(
        "scope,channels,expected",
        [
            ("channels:read", ["C01", "C01", "C02"], ["C01", "C02"]),
            ("", ["C01"], []),
            ("channels:read", ["D01"], []),
            ("channels:read", ["shared:C01"], []),
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

    def test_a_failed_lookup_frees_the_day_for_the_next_mention(self, workspace_integration) -> None:
        cache.clear()
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()
        slack = _slack(error=SlackApiError("ratelimited", response={"ok": False, "error": "ratelimited"}))
        slack.integration.id = workspace_integration.id

        with patch("products.slack_app.backend.tasks.refresh_slack_channel_metadata.delay") as dispatch:
            schedule_channel_metadata_refresh(workspace_integration, "C01")
            refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")
            schedule_channel_metadata_refresh(workspace_integration, "C01")

        assert dispatch.call_count == 2

    def test_a_cache_outage_does_not_break_the_mention(self, workspace_integration) -> None:
        workspace_integration.config = {"scope": "channels:read"}
        workspace_integration.save()

        with patch("products.slack_app.backend.services.channel_metadata.cache.add", side_effect=ConnectionError):
            schedule_channel_metadata_refresh(workspace_integration, "C01")
