from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.today.backend.admin import SeasonalCampaignItemForm
from products.today.backend.logic.seasonal_checklist import InvalidActionSettings, parse_action_settings
from products.today.backend.models import SeasonalCampaign, SeasonalCampaignItem

BOTH_FLAGS = frozenset({"today-rail-nav", "today-seasonal-checklist"})


def make_campaign(**overrides: object) -> SeasonalCampaign:
    fields: dict[str, object] = {
        "key": "winter-2026",
        "is_active": True,
        "title": "Before you log off",
        "description": "Things to set up before a break.",
        "bubble": "4 things before you log off",
        "done_title": "You're all set",
        "done_description": "Enjoy the break.",
        "accessories": ["xmas-hat"],
        **overrides,
    }
    return SeasonalCampaign.objects.create(**fields)


def add_item(campaign: SeasonalCampaign, key: str, order: int, settings: object) -> None:
    SeasonalCampaignItem.objects.create(
        campaign=campaign,
        key=key,
        order=order,
        title=f"Item {key}",
        description="Why it matters.",
        icon="bell",
        action_kind="ask_ai",
        action_settings=settings,
    )


class TestSeasonalChecklistAPI(APIBaseTest):
    def _get(self, flags: frozenset[str]):
        with patch(
            "products.today.backend.feature_flags.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag in flags,
        ):
            return self.client.get(f"/api/projects/{self.team.id}/today/seasonal_checklist/")

    def test_returns_the_active_campaign_with_ordered_items_and_skips_broken_ones(self) -> None:
        campaign = make_campaign()
        add_item(campaign, "second", 2, {"prompt": "Set up an alert"})
        add_item(campaign, "broken", 1, {"prompt": ""})
        add_item(campaign, "first", 0, {"prompt": "Connect Slack"})

        response = self._get(BOTH_FLAGS)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["campaign"] == "winter-2026"
        assert body["accessories"] == ["xmas-hat"]
        assert [(item["key"], item["action"], item["done"]) for item in body["items"]] == [
            ("first", {"kind": "ask_ai", "prompt": "Connect Slack"}, None),
            ("second", {"kind": "ask_ai", "prompt": "Set up an alert"}, None),
        ]

    @parameterized.expand(
        [
            ("no new navigation", frozenset({"today-seasonal-checklist"}), {}),
            ("no checklist flag", frozenset({"today-rail-nav"}), {}),
            ("inactive campaign", BOTH_FLAGS, {"is_active": False}),
            ("campaign not started", BOTH_FLAGS, {"starts_at": timedelta(days=1)}),
            ("campaign ended", BOTH_FLAGS, {"ends_at": timedelta(days=-1)}),
        ]
    )
    def test_hides_the_checklist(self, _name: str, flags: frozenset[str], overrides: dict[str, object]) -> None:
        dates = {name: timezone.now() + value for name, value in overrides.items() if isinstance(value, timedelta)}
        add_item(make_campaign(**{**overrides, **dates}), "only", 0, {"prompt": "Set up an alert"})

        assert self._get(flags).status_code == status.HTTP_404_NOT_FOUND


class TestParseActionSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown action", "send_fax", {"prompt": "x"}),
            ("empty prompt", "ask_ai", {"prompt": ""}),
            ("whitespace prompt", "ask_ai", {"prompt": "   "}),
            ("missing prompt", "ask_ai", {}),
            ("unknown setting", "ask_ai", {"prompt": "x", "url": "https://example.com"}),
            ("settings not an object", "ask_ai", ["x"]),
        ]
    )
    def test_rejects(self, _name: str, kind: str, settings: object) -> None:
        with self.assertRaises(InvalidActionSettings):
            parse_action_settings(kind, settings)


class TestSeasonalCampaignItemForm(TestCase):
    def test_admin_refuses_settings_the_handler_cannot_run(self) -> None:
        form = SeasonalCampaignItemForm(
            data={
                "order": 0,
                "key": "alerts",
                "title": "Get alerted",
                "description": "Why it matters.",
                "icon": "bell",
                "action_kind": "ask_ai",
                "action_settings": '{"prompt": ""}',
            },
            instance=SeasonalCampaignItem(campaign=make_campaign()),
        )

        assert not form.is_valid()
        assert "action_settings" in form.errors
