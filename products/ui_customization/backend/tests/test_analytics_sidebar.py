from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers

from products.ui_customization.backend.presentation.serializers import CustomizationRequestSerializer

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


class TestAnalyticsFragmentLayout(SimpleTestCase):
    @parameterized.expand([(30, True), (31, False)])
    def test_total_item_limit_across_sections(self, item_count: int, accepted: bool) -> None:
        layout = {
            "version": 1,
            "sections": [
                {
                    "id": f"section-{start}",
                    "items": [
                        {"type": "button", "to": {"kind": "page", "page": "new_insight"}, "label": "New insight"}
                        for _ in range(min(12, item_count - start))
                    ],
                }
                for start in range(0, item_count, 12)
            ],
        }
        field = CustomizationRequestSerializer(
            context={"view": SimpleNamespace(kwargs={"context": "analytics_sidebar"})}
        ).fields["layout"]
        if accepted:
            result = field.to_representation(field.to_internal_value(layout))
            assert sum(len(section["items"]) for section in result["sections"]) == item_count
        else:
            with self.assertRaises(serializers.ValidationError) as raised:
                field.to_internal_value(layout)
            assert "Show at most 30 items across all sections" in str(raised.exception.detail)

    @parameterized.expand([("aB3dE5fG",), ("99999999999",), ("aB3dE5fG7hIj",), ("a",)])
    def test_current_and_legacy_insight_ids_round_trip_in_links_and_metrics(self, short_id: str) -> None:
        layout = _with(["sections", 0, "items", 0, "insight"], short_id)
        layout["sections"][0]["items"][1] = {
            "type": "link",
            "to": {"kind": "insight", "short_id": short_id},
            "label": "Signups",
        }

        field = CustomizationRequestSerializer(
            context={"view": SimpleNamespace(kwargs={"context": "analytics_sidebar"})}
        ).fields["layout"]
        assert field.to_representation(field.to_internal_value(layout)) == layout

    @parameterized.expand([("",), ("a" * 13,), ("../insights",), ("a?query",), ("a#hash",)])
    def test_unsafe_or_unbounded_insight_ids_are_rejected_in_links_and_metrics(self, short_id: str) -> None:
        items: list[dict[str, Any]] = [
            {"type": "metric", "insight": short_id, "label": "Signups"},
            {"type": "link", "to": {"kind": "insight", "short_id": short_id}, "label": "Signups"},
        ]
        for item in items:
            with self.assertRaises(serializers.ValidationError):
                CustomizationRequestSerializer(
                    context={"view": SimpleNamespace(kwargs={"context": "analytics_sidebar"})}
                ).fields["layout"].to_internal_value(_item(item))

    @parameterized.expand([("Zx9Yw8Vu",), ("scratchpad",), ("aB3dE5fG7hIj",), ("a",)])
    def test_a_layout_with_every_kind_of_item_round_trips(self, notebook_short_id: str) -> None:
        field = CustomizationRequestSerializer(
            context={"view": SimpleNamespace(kwargs={"context": "analytics_sidebar"})}
        ).fields["layout"]
        layout = _with(["sections", 0, "items", 2, "to", "short_id"], notebook_short_id)

        assert field.to_representation(field.to_internal_value(layout)) == layout

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
            (
                "a notebook id that is too long",
                _with(["sections", 0, "items", 2, "to", "short_id"], "a" * 13),
                "sections.0.items.2.link.to.notebook.short_id",
            ),
            (
                "a notebook id that is a path",
                _with(["sections", 0, "items", 2, "to", "short_id"], "../notes"),
                "sections.0.items.2.link.to.notebook.short_id",
            ),
            (
                "an empty notebook id",
                _with(["sections", 0, "items", 2, "to", "short_id"], ""),
                "sections.0.items.2.link.to.notebook.short_id",
            ),
            ("a color in place of an icon", _with(["sections", 0, "icon"], "#ff0000"), "sections.0.icon"),
            ("a section id with spaces", _with(["sections", 0, "id"], "Growth team"), "sections.0.id"),
            ("a label that is too long", _with(["sections", 0, "title"], "x" * 61), "sections.0.title"),
            ("a title with NUL", _with(["sections", 0, "title"], "Growth\x00"), "sections.0.title"),
            (
                "a metric label with NUL",
                _with(["sections", 0, "items", 0, "label"], "Signups\x00"),
                "sections.0.items.0.metric.label",
            ),
            (
                "a link label with NUL",
                _with(["sections", 0, "items", 1, "label"], "Growth\x00board"),
                "sections.0.items.1.link.label",
            ),
            (
                "a button label with NUL",
                _with(["sections", 0, "items", 4, "label"], "\x00New insight"),
                "sections.0.items.4.button.label",
            ),
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
            CustomizationRequestSerializer(
                context={"view": SimpleNamespace(kwargs={"context": "analytics_sidebar"})}
            ).fields["layout"].to_internal_value(layout)

        detail = raised.exception.detail
        assert isinstance(detail, list)
        messages = str(detail[0]).split("; ")
        assert any(message.startswith(f"{path}:") for message in messages), messages
