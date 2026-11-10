from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue

from products.annotations.backend.facade.api import create_project_annotation
from products.event_definitions.backend.models import EventDefinition
from products.notifications.backend.facade.api import NotificationType, TargetType
from products.product_analytics.backend.models.insight import Insight
from products.product_analytics.backend.temporal.health_checks.event_stopped import EventStoppedCheck

NOTIFY_PATH = "products.product_analytics.backend.temporal.health_checks.event_stopped.create_notification"


class TestEventStoppedDetect(BaseTest):
    def _definition(self, name: str, *, last_seen_days_ago: float, created_days_ago: float = 60, **extra: Any):
        now = timezone.now()
        return EventDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=name,
            created_at=now - timedelta(days=created_days_ago),
            last_seen_at=now - timedelta(days=last_seen_days_ago),
            **extra,
        )

    def _insight_reading(self, *events: str, deleted: bool = False) -> None:
        Insight.objects.create(
            team=self.team,
            deleted=deleted,
            query_metadata={"events": list(events), "updated_at": timezone.now().isoformat()},
        )

    @parameterized.expand(
        [
            ("stopped_and_used", "checkout_completed", {"last_seen_days_ago": 5}, True, True, True),
            ("still_arriving", "checkout_completed", {"last_seen_days_ago": 1}, True, True, False),
            ("quiet_for_over_a_month", "checkout_completed", {"last_seen_days_ago": 45}, True, True, False),
            (
                "too_new_to_judge",
                "checkout_completed",
                {"last_seen_days_ago": 5, "created_days_ago": 7},
                True,
                True,
                False,
            ),
            (
                "ingestion_stopped_by_customer",
                "checkout_completed",
                {"last_seen_days_ago": 5, "ingestion_stopped_at": timezone.now()},
                True,
                True,
                False,
            ),
            ("no_insight_reads_it", "checkout_completed", {"last_seen_days_ago": 5}, False, True, False),
            ("whole_project_silent", "checkout_completed", {"last_seen_days_ago": 5}, True, False, False),
            ("posthog_event_left_to_other_checks", "$pageview", {"last_seen_days_ago": 5}, True, True, False),
        ]
    )
    def test_detect(
        self,
        _name: str,
        event: str,
        definition: dict[str, Any],
        used_by_insight: bool,
        project_live: bool,
        expect_issue: bool,
    ) -> None:
        stopped = self._definition(event, **definition)
        if used_by_insight:
            self._insight_reading(event)
        self._insight_reading(event, deleted=True)
        if project_live:
            self._definition("still_firing", last_seen_days_ago=0)

        issues = EventStoppedCheck().detect([self.team.id])

        if not expect_issue:
            assert issues == {}
            return
        assert len(issues[self.team.id]) == 1
        result = issues[self.team.id][0]
        assert result.payload["event"] == event
        assert result.payload["event_definition_id"] == str(stopped.id)
        assert result.payload["insight_count"] == 1
        assert "annotation" not in result.payload
        assert result.hash_keys == ["event"]

    @parameterized.expand(
        [
            ("same_day", 5, "Released checkout v2"),
            ("a_week_earlier", 12, None),
        ]
    )
    def test_detect_attaches_an_annotation_near_the_last_event(
        self, _name: str, annotation_days_ago: int, expected_content: str | None
    ) -> None:
        self._definition("checkout_completed", last_seen_days_ago=5)
        self._definition("still_firing", last_seen_days_ago=0)
        self._insight_reading("checkout_completed")
        create_project_annotation(
            self.team.id,
            self.user.id,
            content="Released checkout v2",
            date_marker=timezone.now() - timedelta(days=annotation_days_ago),
        )

        payload = EventStoppedCheck().detect([self.team.id])[self.team.id][0].payload

        assert payload.get("annotation", {}).get("content") == expected_content


class TestEventStoppedNotification(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_event", ["checkout_completed"], "checkout_completed stopped arriving", "/data-management/events/1"),
            (
                "several_events",
                ["a", "b", "c", "d"],
                "4 events your insights use stopped arriving",
                "/data-management/events",
            ),
        ]
    )
    def test_on_issues_fired_sends_one_notification_per_team(
        self, _name: str, events: list[str], expected_title: str, expected_url: str
    ) -> None:
        issues = [
            HealthIssue(
                team_id=7,
                kind="event_stopped",
                severity="warning",
                payload={"event": event, "event_definition_id": "1", "insight_count": 2},
                unique_hash=event,
            )
            for event in events
        ]

        with patch(NOTIFY_PATH) as notify:
            EventStoppedCheck.on_issues_fired(issues)

        notify.assert_called_once()
        data = notify.call_args.args[0]
        assert data.notification_type == NotificationType.EVENT_STOPPED
        assert data.target_type == TargetType.TEAM
        assert data.target_id == "7"
        assert data.title == expected_title
        assert data.source_url == expected_url
