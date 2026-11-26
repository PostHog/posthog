import pytest
from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.channel_metadata import (
    OwnerGroup,
    parse_owner_groups,
    refresh_channel_metadata,
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
                "purpose": {"value": "Session replay work"},
            }
        )

        assert refresh_channel_metadata(slack, slack_workspace_id="T01", slack_channel_id="C01")

        channel = SlackChannel.objects.get(slack_workspace_id="T01", slack_channel_id="C01")
        assert (channel.topic, channel.purpose) == ("Replays and <!subteam^S0123|@team-replay>", "Session replay work")
        assert channel.owner_groups == [{"id": "S0123", "handle": "team-replay"}]
        assert channel.metadata_refreshed_at is not None

    @pytest.mark.parametrize(
        "channel",
        [
            {"is_channel": True, "is_private": True, "topic": {"value": "secret"}},
            {"is_channel": True, "is_ext_shared": True, "topic": {"value": "shared"}},
            {"is_im": True},
        ],
    )
    def test_skips_channels_whose_page_the_organization_must_not_read(self, channel: dict) -> None:
        assert not refresh_channel_metadata(_slack(channel), slack_workspace_id="T01", slack_channel_id="C01")
        assert not SlackChannel.objects.filter(slack_channel_id="C01").exists()

    def test_a_failed_lookup_keeps_the_stored_description(self) -> None:
        SlackChannel.objects.create(slack_workspace_id="T01", slack_channel_id="C01", topic="Replays")
        error = SlackApiError("missing_scope", response={"ok": False, "error": "missing_scope"})

        assert not refresh_channel_metadata(_slack(error=error), slack_workspace_id="T01", slack_channel_id="C01")
        assert SlackChannel.objects.get(slack_channel_id="C01").topic == "Replays"
