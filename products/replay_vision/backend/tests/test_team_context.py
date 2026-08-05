from posthog.test.base import BaseTest

from products.posthog_ai.backend.models.assistant import CoreMemory
from products.replay_vision.backend.temporal.activities.fetch_session_events import (
    ProcessedEvents,
    _event_names_by_frequency,
)
from products.replay_vision.backend.temporal.team_context import (
    _MAX_EVENT_DESCRIPTIONS,
    fetch_event_descriptions,
    fetch_product_context,
)

from ee.models.event_definition import EnterpriseEventDefinition


class TestFetchProductContext(BaseTest):
    def test_prefers_core_memory_over_product_description(self):
        self.team.project.product_description = "Old description"
        self.team.project.save()
        CoreMemory.objects.create(team=self.team, text="Acme sells rockets to coyotes.")
        assert fetch_product_context(self.team) == "Acme sells rockets to coyotes."

    def test_falls_back_to_project_product_description(self):
        self.team.project.product_description = "A B2B invoicing tool."
        self.team.project.save()
        assert fetch_product_context(self.team) == "A B2B invoicing tool."

    def test_empty_when_neither_source_exists(self):
        assert fetch_product_context(self.team) == ""

    def test_sanitizes_control_chars_and_caps_length(self):
        CoreMemory.objects.create(team=self.team, text="line one\x07\nline two   spaced" + "x" * 9000)
        result = fetch_product_context(self.team)
        assert result.startswith("line one line two spaced")
        assert "\x07" not in result
        assert len(result) <= 4001  # cap plus the ellipsis


class TestFetchEventDescriptions(BaseTest):
    def _define(self, name: str, description: str | None) -> None:
        EnterpriseEventDefinition.objects.create(team=self.team, name=name, description=description)

    def test_returns_only_described_custom_events_in_given_order(self):
        self._define("checkout_completed", "User paid for their cart.")
        self._define("quote_expired", "A saved quote passed its validity window.")
        self._define("undescribed_event", "")
        self._define("$pageview", "Customer override that must not surface.")
        result = fetch_event_descriptions(
            self.team.pk,
            ["quote_expired", "$pageview", "undescribed_event", "checkout_completed", "unknown_event"],
        )
        assert result == {
            "quote_expired": "A saved quote passed its validity window.",
            "checkout_completed": "User paid for their cart.",
        }
        assert list(result) == ["quote_expired", "checkout_completed"]

    def test_caps_count_and_description_length_and_strips_control_chars(self):
        names = [f"event_{i:03d}" for i in range(_MAX_EVENT_DESCRIPTIONS + 5)]
        for name in names:
            self._define(name, "desc\x07 " + "y" * 600)
        result = fetch_event_descriptions(self.team.pk, names)
        assert len(result) == _MAX_EVENT_DESCRIPTIONS
        sample = result[names[0]]
        assert sample.startswith("desc y")
        assert "\x07" not in sample
        assert len(sample) <= 501  # cap plus the ellipsis

    def test_drops_names_containing_backticks(self):
        self._define("bad`name", "Would escape the prompt's code fencing.")
        assert fetch_event_descriptions(self.team.pk, ["bad`name"]) == {}


class TestEventNamesByFrequency:
    def test_orders_by_count_then_alphabetically(self):
        processed = ProcessedEvents(
            columns=["event_uuid", "event"],
            rows=[["u1", "b_event"], ["u2", "a_event"], ["u3", "b_event"], ["u4", "c_event"], ["u5", "a_event"]],
            url_mapping={},
            window_mapping={},
            event_timestamps={},
            navigation=[],
            navigation_dropped=0,
        )
        assert _event_names_by_frequency(processed) == ["a_event", "b_event", "c_event"]
