from unittest.mock import MagicMock

from products.subscriptions.backend.logic.slack_subscriptions import _prepare_slack_message


def _make_subscription(title: str = "Weekly report"):
    sub = MagicMock()
    sub.title = title
    sub.target_value = "C12345|#test-channel"
    resource_info = MagicMock()
    resource_info.kind = "Insight"
    resource_info.name = "Pageviews"
    resource_info.url = "https://app.posthog.com/insights/123"
    sub.resource_info = resource_info
    sub.summary = "sent weekly on Monday"
    sub.next_delivery_date = MagicMock()
    sub.next_delivery_date.strftime.return_value = "Monday April 21, 2025"
    return sub


def _make_asset(success: bool = True):
    asset = MagicMock()
    asset.content_location = "s3://bucket/test.png" if success else None
    asset.content = b"png" if success else None
    asset.exception = None if success else "Export failed"
    asset.get_public_content_url.return_value = "https://cdn.posthog.com/test.png"
    asset.insight = MagicMock()
    asset.insight.name = "Pageviews"
    asset.insight.derived_name = "Pageviews"
    return asset


class TestSlackMessageIncludesSummary:
    def test_summary_block_present_when_provided(self):
        sub = _make_subscription()
        asset = _make_asset()

        message_data = _prepare_slack_message(sub, [asset], 1, change_summary="- Pageviews up 15%")

        summary_blocks = [
            b
            for b in message_data.blocks
            if b.get("type") == "container" and "AI summary" in b.get("title", {}).get("text", "")
        ]
        assert len(summary_blocks) == 1
        summary_list = summary_blocks[0]["child_blocks"][0]["elements"][0]
        assert summary_list["type"] == "rich_text_list"
        assert summary_list["style"] == "bullet"
        assert summary_list["elements"][0]["elements"][0]["text"] == "Pageviews up 15%"

    def test_no_summary_block_when_none(self):
        sub = _make_subscription()
        asset = _make_asset()

        message_data = _prepare_slack_message(sub, [asset], 1, change_summary=None)

        assert not any(
            b.get("type") == "container" and "AI summary" in b.get("title", {}).get("text", "")
            for b in message_data.blocks
        )

    def test_summary_truncated_to_block_limit(self):
        sub = _make_subscription()
        asset = _make_asset()
        long_summary = "x" * 5000

        message_data = _prepare_slack_message(sub, [asset], 1, change_summary=long_summary)

        summary_blocks = [
            b
            for b in message_data.blocks
            if b.get("type") == "container" and "AI summary" in b.get("title", {}).get("text", "")
        ]
        assert len(summary_blocks) == 1
        summary_text = summary_blocks[0]["child_blocks"][0]["elements"][0]["elements"][0]["text"]
        assert summary_text == "x" * 2797 + "..."
