import datetime
import xml.etree.ElementTree as ET

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from posthog.schema import CachedTeamTaxonomyQueryResponse, MaxEventContext, TeamTaxonomyItem, TeamTaxonomyQuery

from posthog.hogql_queries.query_runner import ExecutionMode

from products.enterprise.backend.hogai.utils.helpers import format_events_xml

# Mock CORE_FILTER_DEFINITIONS_BY_GROUP for consistent testing
MOCK_CORE_FILTER_DEFINITIONS = {
    "events": {
        "All events": {
            "label": "All events",
            "description": "This is a wildcard that matches all events.",
        },
        "$pageview": {
            "label": "Pageview",
            "description": "When a user loads (or reloads) a page.",
        },
        "$autocapture": {
            "label": "Autocapture",
            "description": "User interactions that were automatically captured.",
            "ignored_in_assistant": True,
        },
        "$pageleave": {
            "label": "Pageleave",
            "description": "When a user leaves a page.",
            "ignored_in_assistant": True,
        },
        "custom_event": {
            "label": "Custom Event",
            "description": "A custom event defined by the user.",
        },
    }
}


class TestFormatEventsPrompt(BaseTest):
    def setUp(self):
        super().setUp()
        # Mock CORE_FILTER_DEFINITIONS_BY_GROUP
        self.core_definitions_patcher = patch(
            "posthog.taxonomy.taxonomy.CORE_FILTER_DEFINITIONS_BY_GROUP", MOCK_CORE_FILTER_DEFINITIONS
        )
        self.mock_core_definitions = self.core_definitions_patcher.start()

    def tearDown(self):
        self.core_definitions_patcher.stop()
        super().tearDown()

    def _create_mock_response(self, results=None):
        """Helper to create a mock CachedTeamTaxonomyQueryResponse."""
        if results is None:
            results = []
        return CachedTeamTaxonomyQueryResponse(
            cache_key="test_key",
            is_cached=True,
            last_refresh=datetime.datetime(2023, 1, 1, 0, 0, 0),
            next_allowed_client_refresh=datetime.datetime(2023, 1, 1, 1, 0, 0),
            timezone="UTC",
            results=results,
        )

    def _create_taxonomy_items(self, events_with_counts):
        """Helper to create TeamTaxonomyItem list from event name and count pairs."""
        return [TeamTaxonomyItem(event=event, count=count) for event, count in events_with_counts]

    def _create_context_events(self, events_with_descriptions):
        """Helper to create MaxEventContext list from event name and description pairs."""
        return [
            MaxEventContext(id=str(i), name=event, description=description, type="event")
            for i, (event, description) in enumerate(events_with_descriptions, 1)
        ]

    def _get_event_names_from_xml(self, xml_string):
        """Helper to extract event names from XML result."""
        root = ET.fromstring(xml_string)
        event_names = []
        for event in root.findall("event"):
            name_elem = event.find("name")
            if name_elem is not None and name_elem.text is not None:
                event_names.append(name_elem.text)
        return event_names

    def _get_event_description(self, xml_string, event_name):
        """Helper to get description for a specific event from XML."""
        root = ET.fromstring(xml_string)
        event = root.find(f".//event[name='{event_name}']")
        if event is not None:
            description = event.find("description")
            return description.text if description is not None else None
        return None

    def _setup_mock_runner(self, mock_runner_class, results=None):
        """Helper to setup mock runner with given results."""
        mock_runner = Mock()
        mock_response = self._create_mock_response(results)
        mock_runner.run.return_value = mock_response
        mock_runner_class.return_value = mock_runner
        return mock_runner

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_basic(self, mock_runner_class):
        """Test basic functionality with core events and context events."""
        # Setup mock with taxonomy results
        taxonomy_items = self._create_taxonomy_items(
            [
                ("$pageview", 100),
                ("custom_event", 25),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        # Test data
        events_in_context = self._create_context_events(
            [
                ("custom_event", "A custom event"),
                ("another_event", "Another event"),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        # Verify the XML structure
        root = ET.fromstring(result)
        self.assertEqual(root.tag, "defined_events")

        # Should contain "All events" and the events from taxonomy and context
        event_names = self._get_event_names_from_xml(result)
        expected_events = ["All events", "$pageview", "custom_event", "another_event"]
        self.assertEqual(set(event_names), set(expected_events))

        # Verify descriptions are present
        descriptions = [
            event.find("description").text for event in root.findall("event") if event.find("description") is not None
        ]
        self.assertGreater(len(descriptions), 0)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_filters_low_count_events(self, mock_runner_class):
        """Test that events with count <= 3 are filtered out when there are more than 25 results."""
        # Create 30 results with some low count events
        taxonomy_items = self._create_taxonomy_items(
            [
                ("high_count_event", 100),
                ("low_count_event", 2),  # Should be filtered out
                ("medium_count_event", 10),
            ]
            * 10
        )  # Create 30 results total
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = []
        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should not contain the low count event
        self.assertNotIn("low_count_event", event_names)
        self.assertIn("high_count_event", event_names)
        self.assertIn("medium_count_event", event_names)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_keeps_low_count_events_when_few_results(self, mock_runner_class):
        """Test that low count events are kept when there are 25 or fewer results."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("high_count_event", 100),
                ("low_count_event", 2),  # Should be kept
                ("medium_count_event", 10),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = []
        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should contain the low count event when there are few results
        self.assertIn("low_count_event", event_names)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_skips_ignored_events(self, mock_runner_class):
        """Test that events marked as ignored_in_assistant are skipped."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("$autocapture", 50),  # This is ignored_in_assistant
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = []
        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should not contain ignored events that are not in the context
        self.assertNotIn("$autocapture", event_names)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_keeps_ignored_events_in_context(self, mock_runner_class):
        """Test that ignored events are kept if they're in the context."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("$pageview", 100),
                ("$autocapture", 50),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        # Add ignored event to context
        events_in_context = self._create_context_events(
            [
                ("$autocapture", "User interactions"),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should contain the ignored event because it's in context
        self.assertIn("$autocapture", event_names)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_uses_context_descriptions(self, mock_runner_class):
        """Test that context event descriptions are used when available."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("custom_event", 100),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = self._create_context_events(
            [
                ("custom_event", "Custom event description"),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        description = self._get_event_description(result, "custom_event")
        self.assertEqual(description, "Custom event description")

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_removes_line_breaks(self, mock_runner_class):
        """Test that line breaks are removed from descriptions."""
        self._setup_mock_runner(mock_runner_class, [])

        events_in_context = self._create_context_events(
            [
                ("test_event", "Line 1\nLine 2\nLine 3"),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        description = self._get_event_description(result, "test_event")
        self.assertEqual(description, "Line 1 Line 2 Line 3")

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_empty_context(self, mock_runner_class):
        """Test with empty events context."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("$pageview", 100),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = []
        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)
        self.assertEqual(set(event_names), {"All events", "$pageview"})

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_none_description(self, mock_runner_class):
        """Test handling of events with None description."""
        self._setup_mock_runner(mock_runner_class, [])

        events_in_context = self._create_context_events(
            [
                ("test_event", None),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        root = ET.fromstring(result)
        test_event = root.find(".//event[name='test_event']")
        description = test_event.find("description")

        # Should not have a description tag
        self.assertIsNone(description)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_empty_description(self, mock_runner_class):
        """Test handling of events with empty description."""
        self._setup_mock_runner(mock_runner_class, [])

        events_in_context = self._create_context_events(
            [
                ("test_event", ""),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        root = ET.fromstring(result)
        test_event = root.find(".//event[name='test_event']")
        description = test_event.find("description")
        # Empty string descriptions should not create a description tag
        self.assertIsNone(description)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_duplicate_events(self, mock_runner_class):
        """Test handling of duplicate events between taxonomy and context."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("duplicate_event", 100),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = self._create_context_events(
            [
                ("duplicate_event", "Context description"),
            ]
        )

        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should only appear once
        self.assertEqual(event_names.count("duplicate_event"), 1)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_non_cached_response(self, mock_runner_class):
        """Test handling when response is not a CachedTeamTaxonomyQueryResponse."""
        mock_runner = Mock()
        mock_runner.run.return_value = "not a cached response"
        mock_runner_class.return_value = mock_runner

        events_in_context = []

        with self.assertRaises(ValueError, msg="Failed to generate events prompt."):
            format_events_xml(events_in_context, self.team)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_uses_label_llm_when_available(self, mock_runner_class):
        """Test that label_llm is used when available in core definitions."""
        taxonomy_items = self._create_taxonomy_items(
            [
                ("$pageview", 100),
            ]
        )
        self._setup_mock_runner(mock_runner_class, taxonomy_items)

        events_in_context = []
        result = format_events_xml(events_in_context, self.team)

        description = self._get_event_description(result, "$pageview")

        # Should use label_llm if available, otherwise label
        self.assertIsNotNone(description)
        # The actual content depends on the core definitions, but it should contain the label
        if description is not None:
            self.assertIn("Pageview", description)

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_handles_events_without_names(self, mock_runner_class):
        """Test handling of context events without names."""
        self._setup_mock_runner(mock_runner_class, [])

        events_in_context = [
            MaxEventContext(id="1", name=None, description="No name event", type="event"),
            MaxEventContext(id="2", name="", description="Empty name event", type="event"),
        ]

        result = format_events_xml(events_in_context, self.team)

        event_names = self._get_event_names_from_xml(result)

        # Should only contain "All events" since context events have no names
        self.assertEqual(set(event_names), {"All events"})

    @patch("ee.hogai.utils.helpers.TeamTaxonomyQueryRunner")
    def test_format_events_xml_calls_runner_with_correct_parameters(self, mock_runner_class):
        """Test that TeamTaxonomyQueryRunner is called with correct parameters."""
        self._setup_mock_runner(mock_runner_class, [])

        events_in_context = []
        format_events_xml(events_in_context, self.team)

        # Verify TeamTaxonomyQueryRunner was called correctly
        mock_runner_class.assert_called_once_with(TeamTaxonomyQuery(), self.team)
        mock_runner_class.return_value.run.assert_called_once_with(
            ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS
        )
