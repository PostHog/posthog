import uuid
from datetime import UTC, date, datetime

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models import Team, User

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import BriefingStatus, ItemGroup, ItemReason, ItemSource, ItemState
from products.today.backend.logic import briefings
from products.today.backend.logic.fact_sheet import FactSheet, FactSheetItem
from products.today.backend.models import DailyBriefing

RESOLVED_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000001")
DISMISSED_REPORT = uuid.UUID("00000000-0000-4000-8000-000000000002")
RESOLVED_TICKET = uuid.UUID("00000000-0000-4000-8000-000000000003")
OPEN_TICKET = uuid.UUID("00000000-0000-4000-8000-000000000004")
SUPPRESSED_ISSUE = uuid.UUID("00000000-0000-4000-8000-000000000005")
RELEASED_ISSUE = uuid.UUID("00000000-0000-4000-8000-000000000006")


def _item(key: str, group: ItemGroup, source: ItemSource) -> FactSheetItem:
    return FactSheetItem(
        key=key,
        group=group,
        source=source,
        reason=ItemReason.WAITING_FOR_YOU,
        title=key,
        url="/project/1/inbox",
        rank=1,
        urgency=1,
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
        metrics=[
            signals.BriefingReportMetric(
                metric_id="affected-users",
                title="Affected users",
                kind="affected_users",
                role="primary",
                value=42.0,
                value_at=datetime(2026, 9, 30, 12, 0, tzinfo=UTC),
                series=[10.0, 20.0, 42.0],
                value_format="count",
                unit="users",
            )
        ],
    )


class TestBriefingItemStates(SimpleTestCase):
    def test_items_show_what_was_resolved_or_dismissed_since_the_briefing_was_written(self) -> None:
        items = [
            _item(f"report:{RESOLVED_REPORT}", ItemGroup.REPORT, ItemSource.SELF_DRIVING),
            _item(f"report:{DISMISSED_REPORT}", ItemGroup.REPORT, ItemSource.SELF_DRIVING),
            _item(f"ticket:{RESOLVED_TICKET}", ItemGroup.OTHER, ItemSource.SUPPORT),
            _item(f"ticket:{OPEN_TICKET}", ItemGroup.OTHER, ItemSource.SUPPORT),
            _item("ticket:not-a-uuid", ItemGroup.OTHER, ItemSource.SUPPORT),
            _item(f"issue:{SUPPRESSED_ISSUE}", ItemGroup.OTHER, ItemSource.ERROR_TRACKING),
            _item(f"issue:{RELEASED_ISSUE}", ItemGroup.OTHER, ItemSource.ERROR_TRACKING),
            _item("github_pr:example/app#7", ItemGroup.OTHER, ItemSource.GITHUB),
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
                ],
            ),
            patch.object(
                briefings.conversations,
                "ticket_statuses",
                return_value={RESOLVED_TICKET: "resolved", OPEN_TICKET: "open"},
            ) as ticket_statuses,
            patch.object(
                briefings.error_tracking,
                "issue_statuses",
                return_value={SUPPRESSED_ISSUE: "suppressed", RELEASED_ISSUE: "pending_release"},
            ),
            patch.object(
                briefings.signals,
                "open_report_counts",
                return_value=signals.OpenReportCounts(for_person=0, in_project=0),
            ),
        ):
            contract = briefings.to_contract(briefing, Team(id=1), User(id=1))

        assert {item.key: item.state for item in contract.items} == {
            f"report:{RESOLVED_REPORT}": ItemState.DONE,
            f"report:{DISMISSED_REPORT}": ItemState.DISMISSED,
            f"ticket:{RESOLVED_TICKET}": ItemState.DONE,
            f"ticket:{OPEN_TICKET}": ItemState.OPEN,
            "ticket:not-a-uuid": ItemState.OPEN,
            f"issue:{SUPPRESSED_ISSUE}": ItemState.DISMISSED,
            f"issue:{RELEASED_ISSUE}": ItemState.DONE,
            "github_pr:example/app#7": ItemState.OPEN,
        }
        assert ticket_statuses.call_args.kwargs["ticket_ids"] == [RESOLVED_TICKET, OPEN_TICKET]
        report = next(item.report for item in contract.items if item.key == f"report:{RESOLVED_REPORT}")
        assert report is not None
        assert (report.priority, report.pull_request_state, [m.value for m in report.metrics]) == (
            "P1",
            "merged",
            [42.0],
        )
        assert [item.report for item in contract.items if item.group != ItemGroup.REPORT] == [None] * 6
