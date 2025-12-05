import uuid
from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.event.util import bulk_create_events

from products.live_debugger.backend.models import LiveDebuggerBreakpoint


class TestLiveDebuggerBreakpointModel(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        # Clean ClickHouse events table before each test
        from posthog.clickhouse.client import sync_execute

        sync_execute("TRUNCATE TABLE IF EXISTS sharded_events")

        self.breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="test.py",
            line_number=42,
            enabled=True,
        )

    def test_get_breakpoint_hits_returns_hits_for_team(self):
        """Test that get_breakpoint_hits returns breakpoint hits for the specified team"""
        breakpoint_id = str(self.breakpoint.id)

        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user123",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": breakpoint_id,
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "test_function", "line": 42, "file": "test.py"}],
                        "$locals_variables": {"x": 10, "y": 20},
                    },
                }
            ]
        )

        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        assert len(hits) == 1
        assert hits[0].id is not None  # UUID should be set
        assert hits[0].breakpoint_id == breakpoint_id
        assert hits[0].line_number == 42
        assert hits[0].filename == "test.py"
        assert hits[0].function_name == "test_function"
        assert hits[0].locals == {"x": 10, "y": 20}
        assert len(hits[0].stack_trace) == 1

    def test_get_breakpoint_hits_team_isolation(self):
        """Test that get_breakpoint_hits only returns hits for the specified team"""
        other_team = self.organization.teams.create(name="Other Team")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            filename="other.py",
            line_number=100,
            enabled=True,
        )

        # Create event for our team
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "my_func"}],
                        "$locals_variables": {},
                    },
                }
            ]
        )

        # Create event for other team
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": other_team.pk,
                    "distinct_id": "user2",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(other_breakpoint.id),
                        "$line_number": 100,
                        "$file_path": "other.py",
                        "$stack_trace": [{"function": "other_func"}],
                        "$locals_variables": {},
                    },
                }
            ]
        )

        # Query for our team
        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        # Should only return our team's hits
        assert len(hits) == 1
        assert hits[0].filename == "test.py"
        assert hits[0].function_name == "my_func"

        # Query for other team
        other_hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=other_team)

        # Should only return other team's hits
        assert len(other_hits) == 1
        assert other_hits[0].filename == "other.py"
        assert other_hits[0].function_name == "other_func"

    def test_get_breakpoint_hits_filter_by_breakpoint_id(self):
        """Test that get_breakpoint_hits filters by breakpoint_ids when provided"""
        breakpoint2 = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="other.py",
            line_number=100,
            enabled=True,
        )

        # Create events for two different breakpoints
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "func1"}],
                        "$locals_variables": {},
                    },
                },
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(breakpoint2.id),
                        "$line_number": 100,
                        "$file_path": "other.py",
                        "$stack_trace": [{"function": "func2"}],
                        "$locals_variables": {},
                    },
                },
            ]
        )

        # Query without filter - should return both
        all_hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)
        assert len(all_hits) == 2

        # Query with filter for first breakpoint (using list)
        filtered_hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team, breakpoint_ids=[self.breakpoint.id])
        assert len(filtered_hits) == 1
        assert filtered_hits[0].filename == "test.py"
        assert filtered_hits[0].function_name == "func1"

        # Query with filter for second breakpoint (using list)
        filtered_hits2 = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team, breakpoint_ids=[breakpoint2.id])
        assert len(filtered_hits2) == 1
        assert filtered_hits2[0].filename == "other.py"
        assert filtered_hits2[0].function_name == "func2"

    def test_get_breakpoint_hits_time_filter(self):
        """Test that get_breakpoint_hits only returns hits from the last hour"""
        now = datetime.now()

        # Create event from 30 minutes ago (should be included)
        with freeze_time(now - timedelta(minutes=30)):
            bulk_create_events(
                [
                    {
                        "uuid": str(uuid.uuid4()),
                        "event": "$data_breakpoint_hit",
                        "team_id": self.team.pk,
                        "distinct_id": "user1",
                        "timestamp": datetime.now(),
                        "properties": {
                            "$breakpoint_id": str(self.breakpoint.id),
                            "$line_number": 42,
                            "$file_path": "test.py",
                            "$stack_trace": [{"function": "recent_func"}],
                            "$locals_variables": {},
                        },
                    }
                ]
            )

        # Create event from 2 hours ago (should be excluded)
        with freeze_time(now - timedelta(hours=2)):
            bulk_create_events(
                [
                    {
                        "uuid": str(uuid.uuid4()),
                        "event": "$data_breakpoint_hit",
                        "team_id": self.team.pk,
                        "distinct_id": "user1",
                        "timestamp": datetime.now(),
                        "properties": {
                            "$breakpoint_id": str(self.breakpoint.id),
                            "$line_number": 42,
                            "$file_path": "test.py",
                            "$stack_trace": [{"function": "old_func"}],
                            "$locals_variables": {},
                        },
                    }
                ]
            )

        # Query should only return the recent event
        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        assert len(hits) == 1
        assert hits[0].function_name == "recent_func"

    def test_get_breakpoint_hits_pagination(self):
        """Test that get_breakpoint_hits respects limit and offset parameters"""
        # Create 5 events
        events = []
        for i in range(5):
            events.append(
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42 + i,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": f"func{i}"}],
                        "$locals_variables": {"index": i},
                    },
                }
            )
        bulk_create_events(events)

        # Test limit
        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team, limit=2)
        assert len(hits) == 2

        # Test offset
        hits_page2 = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team, limit=2, offset=2)
        assert len(hits_page2) == 2

        # Verify different results
        hit_functions = {hit.function_name for hit in hits}
        hit_functions_page2 = {hit.function_name for hit in hits_page2}
        assert hit_functions != hit_functions_page2

    def test_get_breakpoint_hits_empty_results(self):
        """Test that get_breakpoint_hits returns empty list when no hits exist"""
        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)
        assert hits == []

    def test_get_breakpoint_hits_handles_malformed_json(self):
        """Test that get_breakpoint_hits skips events with malformed JSON data"""
        # Create event with valid JSON
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "good_func"}],
                        "$locals_variables": {"x": 1},
                    },
                }
            ]
        )

        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        # Should return the valid event
        assert len(hits) == 1
        assert hits[0].function_name == "good_func"

    def test_get_breakpoint_hits_only_includes_breakpoint_hit_events(self):
        """Test that get_breakpoint_hits only returns $data_breakpoint_hit events"""
        # Create a regular event (not a breakpoint hit)
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$pageview",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {},
                }
            ]
        )

        # Create a breakpoint hit event
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": datetime.now(),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "test_func"}],
                        "$locals_variables": {},
                    },
                }
            ]
        )

        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        # Should only return the breakpoint hit event
        assert len(hits) == 1
        assert hits[0].function_name == "test_func"

    def test_get_breakpoint_hits_orders_by_timestamp_desc(self):
        """Test that get_breakpoint_hits returns hits ordered by timestamp descending"""
        now = datetime.now()

        # Create events at different times
        bulk_create_events(
            [
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": now - timedelta(minutes=30),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "old_func"}],
                        "$locals_variables": {},
                    },
                },
                {
                    "uuid": str(uuid.uuid4()),
                    "event": "$data_breakpoint_hit",
                    "team_id": self.team.pk,
                    "distinct_id": "user1",
                    "timestamp": now - timedelta(minutes=10),
                    "properties": {
                        "$breakpoint_id": str(self.breakpoint.id),
                        "$line_number": 42,
                        "$file_path": "test.py",
                        "$stack_trace": [{"function": "recent_func"}],
                        "$locals_variables": {},
                    },
                },
            ]
        )

        hits = LiveDebuggerBreakpoint.get_breakpoint_hits(team=self.team)

        # Should return most recent first
        assert len(hits) == 2
        assert hits[0].function_name == "recent_func"
        assert hits[1].function_name == "old_func"
