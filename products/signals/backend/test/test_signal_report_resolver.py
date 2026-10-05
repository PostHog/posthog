from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.models import SignalReport

S = SignalReport.Status


class TestSignalReportResolver(SimpleTestCase):
    @parameterized.expand(
        [
            ("resolve_names_the_person", S.READY, None, S.RESOLVED, 42, 42),
            ("merged_pr_resolve_names_nobody", S.READY, 7, S.RESOLVED, None, None),
            ("restore_from_archive_keeps_the_resolver", S.SUPPRESSED, 7, S.RESOLVED, None, 7),
            ("resolve_from_archive_names_the_new_person", S.SUPPRESSED, 7, S.RESOLVED, 42, 42),
            ("archive_keeps_the_resolver", S.RESOLVED, 7, S.SUPPRESSED, None, 7),
            ("snooze_clears_the_resolver", S.RESOLVED, 7, S.POTENTIAL, None, None),
            ("reopen_clears_the_resolver", S.RESOLVED, 7, S.READY, None, None),
        ]
    )
    def test_transition_sets_resolver(
        self,
        _name: str,
        initial_status: SignalReport.Status,
        initial_resolver: int | None,
        target: SignalReport.Status,
        actor: int | None,
        expected_resolver: int | None,
    ) -> None:
        report = SignalReport(status=initial_status, resolved_by_id=initial_resolver)
        if initial_status == S.SUPPRESSED:
            report.status_before_suppression = S.RESOLVED

        report.transition_to(target, resolved_by_id=actor)

        assert report.resolved_by_id == expected_resolver
