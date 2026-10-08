import uuid
from datetime import UTC, date, datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models import Team, User

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import BriefingStatus, ItemGroup, ItemReason, ItemSource, ItemState
from products.today.backend.logic import briefings
from products.today.backend.logic.fact_sheet import FactSheet, FactSheetItem
from products.today.backend.models import DailyBriefing

RESOLVED_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000001")
DISMISSED_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000002")
OPEN_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000003")
MISSING_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000004")
DELETED_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000005")


def _item(report_id: uuid.UUID) -> FactSheetItem:
    return FactSheetItem(
        key=f"report:{report_id}",
        group=ItemGroup.REPORT,
        source=ItemSource.SELF_DRIVING,
        reason=ItemReason.WAITING_FOR_YOU,
        title=str(report_id),
        url="/project/1/inbox",
        rank=1,
        facts={},
    )


def _report_details(report_id: uuid.UUID, status: str) -> signals.BriefingReportDetails:
    return signals.BriefingReportDetails(
        report_id=str(report_id),
        status=status,
        priority="P1",
        summary="Checkout fails for some users",
        pull_request_state="merged",
        pull_request_url="https://github.com/example/app/pull/1",
        signal_count=12,
        updated_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
        metrics=[
            signals.ReportMetricSnapshot(
                metric_id="affected-users",
                title="Affected users",
                kind="affected_users",
                role="primary",
                value=42.0,
                series=[10.0, 20.0, 42.0],
                value_format="count",
                unit="users",
                query={"kind": "InsightVizNode"},
            )
        ],
        charts=[],
    )


class TestBriefingItemStates(SimpleTestCase):
    def test_items_show_what_was_resolved_or_dismissed_since_the_briefing_was_written(self) -> None:
        items = [
            _item(RESOLVED_REPORT),
            _item(DISMISSED_REPORT),
            _item(OPEN_REPORT),
            _item(MISSING_REPORT),
            _item(DELETED_REPORT),
        ]
        briefing = DailyBriefing(
            id=uuid.uuid4(),
            team_id=1,
            user_id=1,
            local_day=date(2026, 10, 1),
            status=BriefingStatus.READY,
            facts=FactSheet(items=items).model_dump(mode="json"),
            content={},
            created_at=datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
        )

        with (
            patch.object(
                briefings.signals,
                "report_details",
                return_value=[
                    _report_details(RESOLVED_REPORT, "resolved"),
                    _report_details(DISMISSED_REPORT, "suppressed"),
                    _report_details(OPEN_REPORT, "ready"),
                    _report_details(DELETED_REPORT, "deleted"),
                ],
            ),
            patch.object(
                briefings.signals,
                "open_report_counts",
                return_value=signals.OpenReportCounts(for_person=0, in_project=0),
            ),
        ):
            contract = briefings.to_contract(briefing, Team(id=1), User(id=1), metric_access=MagicMock())

        assert {item.key: item.state for item in contract.items} == {
            f"report:{RESOLVED_REPORT}": ItemState.DONE,
            f"report:{DISMISSED_REPORT}": ItemState.DISMISSED,
            f"report:{OPEN_REPORT}": ItemState.OPEN,
            f"report:{MISSING_REPORT}": ItemState.OPEN,
            f"report:{DELETED_REPORT}": ItemState.DISMISSED,
        }
        report = next(item.report for item in contract.items if item.key == f"report:{RESOLVED_REPORT}")
        assert report is not None
        assert (report.priority, report.pull_request_state, [(m.value, m.query) for m in report.metrics]) == (
            "P1",
            "merged",
            [(42.0, {"kind": "InsightVizNode"})],
        )
        reports_without_details = [item.key for item in contract.items if item.report is None]
        assert reports_without_details == [f"report:{MISSING_REPORT}", f"report:{DELETED_REPORT}"]
