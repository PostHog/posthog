from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.db import InternalError
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.signals.backend.models import SignalReport, SignalScratchpad
from products.signals.backend.tasks import (
    REPORT_POINTER_MIN_AGE_DAYS,
    REPORT_POINTER_SWEEP_CURSOR_KEY,
    SCRATCHPAD_EXPIRY_GRACE_DAYS,
    ReportPointerSweep,
    expire_dangling_report_pointers,
    prune_expired_scratchpad_entries,
    prune_expired_scratchpad_entries_task,
    single_report_id,
)

ID_A = "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
ID_B = "6f1c2d3e-4b5a-4c6d-8e7f-9a0b1c2d3e4f"


class TestPruneExpiredScratchpadEntries(BaseTest):
    def test_prunes_only_entries_whose_expiry_is_past_the_grace(self) -> None:
        now = timezone.now()
        grace = timedelta(days=SCRATCHPAD_EXPIRY_GRACE_DAYS)
        with team_scope(self.team.id):
            SignalScratchpad.objects.create(team=self.team, key="durable", content="x", expires_at=None)
            SignalScratchpad.objects.create(team=self.team, key="live", content="x", expires_at=now + timedelta(days=1))
            SignalScratchpad.objects.create(
                team=self.team, key="within_grace", content="x", expires_at=now - timedelta(days=1)
            )
            SignalScratchpad.objects.create(
                team=self.team, key="past_grace", content="x", expires_at=now - grace - timedelta(days=1)
            )

        deleted = prune_expired_scratchpad_entries()

        assert deleted == 1
        survivors = set(SignalScratchpad.objects.unscoped().values_list("key", flat=True))
        assert survivors == {"durable", "live", "within_grace"}

    @parameterized.expand(
        [
            ("stale_connection", "cannot execute DELETE in a read-only transaction", True),
            ("other_internal_error", "deadlock detected", False),
        ]
    )
    def test_task_reports_only_errors_that_are_not_a_stale_connection(
        self, _name: str, message: str, is_stale: bool
    ) -> None:
        with (
            patch(
                "products.signals.backend.tasks.prune_expired_scratchpad_entries",
                side_effect=InternalError(message),
            ),
            patch("products.signals.backend.tasks.connections") as connections,
            patch("products.signals.backend.tasks.capture_exception") as capture,
        ):
            prune_expired_scratchpad_entries_task()
        assert connections.close_all.called == is_stale
        assert capture.called == (not is_stale)


class TestSingleReportId(SimpleTestCase):
    @parameterized.expand(
        [
            ("bare_id", f"report_id {ID_A}", ID_A),
            ("repeated_in_link_and_backticks", f"[r](/inbox/reports/{ID_A}) `{ID_A.upper()}`", ID_A),
            ("two_distinct_ids", f"report {ID_A}, merged from {ID_B}", None),
            ("no_id", "filed a report about slow dashboards", None),
        ]
    )
    def test_single_report_id(self, _name: str, content: str, expected: str | None) -> None:
        assert single_report_id(content) == expected


class TestExpireDanglingReportPointers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(REPORT_POINTER_SWEEP_CURSOR_KEY)
        self.old = timezone.now() - timedelta(days=REPORT_POINTER_MIN_AGE_DAYS + 1)

    def _report(self, status: str, team: Team | None = None) -> str:
        report = SignalReport.objects.create(team=team or self.team, status=status, title="t", summary="s")
        return str(report.id)

    def _pointer(self, key: str, content: str, *, updated_at: timedelta | None = None) -> None:
        with team_scope(self.team.id):
            SignalScratchpad.objects.create(team=self.team, key=key, content=content)
        SignalScratchpad.objects.unscoped().filter(team=self.team, key=key).update(
            updated_at=timezone.now() - updated_at if updated_at is not None else self.old
        )

    @parameterized.expand([("write_on", True), ("write_off", False)])
    def test_expires_only_old_single_id_pointers_to_missing_or_deleted_reports(self, _name: str, write: bool) -> None:
        other_team = Team.objects.create(organization=self.organization)
        dangling = {
            "report:missing": f"[r](/inbox/{ID_A}) `{ID_A}`",
            "report:deleted": self._report(SignalReport.Status.DELETED),
            "report:other_team": self._report(SignalReport.Status.READY, team=other_team),
        }
        kept = {
            "report:ready": self._report(SignalReport.Status.READY),
            "report:resolved": self._report(SignalReport.Status.RESOLVED),
            "report:closed": self._report(SignalReport.Status.CLOSED),
            "report:suppressed": self._report(SignalReport.Status.SUPPRESSED),
            "report:no_id": "filed about slow dashboards",
            "report:two_ids": f"{ID_A} then {ID_B}",
            "dedupe:missing": ID_A,
        }
        for key, content in {**dangling, **kept}.items():
            self._pointer(key, content)
        self._pointer("report:young", ID_B, updated_at=timedelta(days=REPORT_POINTER_MIN_AGE_DAYS - 1))
        before = {
            row.key: (row.content, row.updated_at) for row in SignalScratchpad.objects.unscoped().filter(team=self.team)
        }

        sweep = expire_dangling_report_pointers(write=write)

        assert sweep == ReportPointerSweep(scanned=9, matched=3, expired=3 if write else 0)
        rows = list(SignalScratchpad.objects.unscoped().filter(team=self.team))
        assert {row.key for row in rows if row.expires_at is not None} == (set(dangling) if write else set())
        assert {row.key: (row.content, row.updated_at) for row in rows} == before

    def test_capped_sweep_resumes_from_its_cursor_on_the_next_run(self) -> None:
        self._pointer("report:live", self._report(SignalReport.Status.READY))
        self._pointer("report:dangling", ID_A)

        first = expire_dangling_report_pointers(write=True, batch_size=1, max_batches=1)
        second = expire_dangling_report_pointers(write=True, batch_size=1, max_batches=1)

        assert (first.expired, second.expired) == (0, 1)
        expired = SignalScratchpad.objects.unscoped().filter(team=self.team, expires_at__isnull=False)
        assert list(expired.values_list("key", flat=True)) == ["report:dangling"]
