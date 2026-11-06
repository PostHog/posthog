from copy import deepcopy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.today.backend.presentation.serializers import AnalyticsSidebarLayoutField

GROWTH_LAYOUT: dict[str, Any] = {
    "version": 1,
    "sections": [
        {
            "id": "growth",
            "title": "Growth",
            "icon": "rocket",
            "items": [
                {"type": "metric", "insight": "aB3dE5fG", "label": "Signups"},
                {"type": "link", "to": {"kind": "dashboard", "id": 12}, "label": "Growth board", "icon": "dashboard"},
                {"type": "link", "to": {"kind": "notebook", "short_id": "Zx9Yw8Vu"}, "label": "Launch notes"},
                {"type": "link", "to": {"kind": "page", "page": "web_analytics"}},
                {
                    "type": "button",
                    "to": {"kind": "page", "page": "new_insight"},
                    "label": "New insight",
                    "variant": "primary",
                },
            ],
        },
        {"id": "pinned", "title": "Pinned", "items": [{"type": "list", "source": "pinned"}]},
    ],
}


def _with(path: list[str | int], value: Any) -> dict[str, Any]:
    layout = deepcopy(GROWTH_LAYOUT)
    target: Any = layout
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    return layout


def _item(item: dict[str, Any]) -> dict[str, Any]:
    return _with(["sections", 0, "items", 0], item)


class TestAnalyticsSidebarLayout(SimpleTestCase):
    def test_a_layout_with_every_kind_of_item_round_trips(self) -> None:
        field = AnalyticsSidebarLayoutField()

        assert field.to_representation(field.to_internal_value(GROWTH_LAYOUT)) == GROWTH_LAYOUT

    @parameterized.expand(
        [
            (
                "an unknown item type",
                _item({"type": "html", "html": "<script>alert(1)</script>"}),
                "sections.0.items.0",
            ),
            (
                "a link to another site",
                _item({"type": "link", "to": {"kind": "url", "url": "https://evil.example.com"}, "label": "Login"}),
                "sections.0.items.0.link.to",
            ),
            (
                "a key the schema does not name",
                _item({"type": "button", "to": {"kind": "page", "page": "alerts"}, "label": "Go", "onClick": "x()"}),
                "sections.0.items.0.button.onClick",
            ),
            (
                "a page that does not exist",
                _item({"type": "link", "to": {"kind": "page", "page": "admin"}}),
                "sections.0.items.0.link.to.page.page",
            ),
            (
                "an insight link without a label",
                _item({"type": "link", "to": {"kind": "insight", "short_id": "aB3dE5fG"}}),
                "sections.0.items.0.link",
            ),
            (
                "a short id that is a path",
                _item({"type": "metric", "insight": "../../x", "label": "Signups"}),
                "sections.0.items.0.metric.insight",
            ),
            (
                "a metric without a label",
                _item({"type": "metric", "insight": "aB3dE5fG"}),
                "sections.0.items.0.metric.label",
            ),
            ("a color in place of an icon", _with(["sections", 0, "icon"], "#ff0000"), "sections.0.icon"),
            ("a section id with spaces", _with(["sections", 0, "id"], "Growth team"), "sections.0.id"),
            ("a label that is too long", _with(["sections", 0, "title"], "x" * 61), "sections.0.title"),
            ("a section with no items", _with(["sections", 0, "items"], []), "sections.0.items"),
            ("no sections", _with(["sections"], []), "sections"),
            ("two sections with one id", _with(["sections", 1, "id"], "growth"), "layout"),
            (
                "the same list twice",
                _with(["sections", 1, "items"], [{"type": "list", "source": "pinned"}] * 2),
                "layout",
            ),
            (
                "more metrics than fit",
                _with(["sections", 1, "items"], [{"type": "metric", "insight": "aB3dE5fG", "label": "Signups"}] * 4),
                "layout",
            ),
        ]
    )
    def test_a_layout_outside_the_schema_is_rejected_at_its_path(
        self, _name: str, layout: dict[str, Any], path: str
    ) -> None:
        with self.assertRaises(serializers.ValidationError) as raised:
            AnalyticsSidebarLayoutField().to_internal_value(layout)

        assert any(str(message).startswith(f"{path}:") for message in raised.exception.detail), raised.exception.detail
