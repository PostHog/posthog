from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import APIBaseTest

from products.annotations.backend.facade import testing as annotations_testing
from products.annotations.backend.facade.enums import AnnotationScope
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.temporal.snapshot_activities import _load_annotations_section


def _snap_with_range(date_from: str | None, date_to: str | None) -> dict:
    qr: dict = {}
    if date_from is not None and date_to is not None:
        qr["resolved_date_range"] = {"date_from": date_from, "date_to": date_to}
    return {"insights": [{"id": 1, "query_results": qr}]}


@pytest.mark.django_db
class TestLoadAnnotationsSection(APIBaseTest):
    def _subscription_like(self, dashboard_id: int | None = None) -> Any:
        return SimpleNamespace(team=self.team, dashboard_id=dashboard_id)

    def test_returns_empty_string_when_no_date_window(self) -> None:
        result = _load_annotations_section(self._subscription_like(), [], [])
        assert result == ""

    def test_returns_empty_string_when_window_present_but_no_annotations(self) -> None:
        snapshots = [_snap_with_range("2025-04-01T00:00:00Z", "2025-04-15T00:00:00Z")]
        result = _load_annotations_section(self._subscription_like(), snapshots, [])
        assert result == ""

    def test_renders_annotations_for_insight_in_window(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Pageviews")
        annotations_testing.create_annotation(
            team_id=self.team.id,
            organization_id=self.organization.id,
            content="rolled out new home page flag",
            date_marker=datetime(2025, 4, 5, tzinfo=ZoneInfo("UTC")),
            scope=AnnotationScope.INSIGHT,
            insight_id=insight.id,
        )
        snapshots = [_snap_with_range("2025-04-01T00:00:00Z", "2025-04-15T00:00:00Z")]

        result = _load_annotations_section(self._subscription_like(), snapshots, [insight.id])

        assert "rolled out new home page flag" in result
        assert "Annotations during this period" in result
