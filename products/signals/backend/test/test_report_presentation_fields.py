from posthog.test.base import BaseTest

from products.signals.backend.models import ReportPresentationFields, SignalReport
from products.signals.backend.report_generation.research import ReportPresentationOutput
from products.signals.backend.serializers import SignalReportSerializer

LEDGER = {
    "verified": ["requires_db_property short-circuits on key presence"],
    "measured": ["88% of web flag evals carry email (project 2 only)"],
    "inferred": ["this explains ticket 67432"],
    "unverified": ["no incident confirmed in data"],
}

FULL_RECORD = ReportPresentationFields(
    headline="Users hit a dead end on expired checkout sessions.",
    impact="Around 40 checkouts a day end in an error page.",
    recommended_action="Ship the session-refresh fix.",
    cause="The session token is validated against a cache that never expires.",
    cause_location="rust/feature-flags/src/property_filter.rs:57-61",
    fix_size="2 files, ~1 day · rust + posthog-js",
    not_this="PR #4476 owns the remote-config half; this is the client cache half.",
    confidence=LEDGER,
)


class TestReportPresentationFields(BaseTest):
    def _report(self, status: SignalReport.Status = SignalReport.Status.IN_PROGRESS) -> SignalReport:
        return SignalReport.objects.create(team=self.team, status=status)

    def test_ready_transition_writes_the_whole_record(self) -> None:
        report = self._report()
        updated = report.transition_to(
            SignalReport.Status.READY,
            title="fix(checkout): handle expired sessions",
            summary="Users hit a dead end.\n\n## Problem\n...",
            presentation=FULL_RECORD,
        )
        report.save(update_fields=updated)
        report.refresh_from_db()
        assert report.headline == FULL_RECORD.headline
        assert report.impact == FULL_RECORD.impact
        assert report.recommended_action == FULL_RECORD.recommended_action
        assert report.cause == FULL_RECORD.cause
        assert report.cause_location == FULL_RECORD.cause_location
        assert report.fix_size == FULL_RECORD.fix_size
        assert report.not_this == FULL_RECORD.not_this
        assert report.confidence == LEDGER

    def test_rewrite_without_presentation_fields_withdraws_them(self) -> None:
        # A re-research whose output omits the fields (an older workflow replay, or an
        # agent that returned none) must not leave stale one-liners describing the
        # previous summary beside the new one.
        report = self._report()
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status.READY,
                title="t",
                summary="s",
                presentation=FULL_RECORD,
            )
        )
        report.save(update_fields=report.transition_to(SignalReport.Status.CANDIDATE))
        report.save(update_fields=report.transition_to(SignalReport.Status.IN_PROGRESS, signals_at_run_increment=1))
        report.save(update_fields=report.transition_to(SignalReport.Status.READY, title="t2", summary="s2"))
        report.refresh_from_db()
        for field in SignalReport.PRESENTATION_FIELD_NAMES:
            assert getattr(report, field) is None, field

    def test_update_authored_content_sets_changed_fields_and_noops_identical(self) -> None:
        report = self._report(SignalReport.Status.READY)
        report.title = "t"
        report.summary = "s"
        report.headline = "Same headline"
        report.save()

        assert report.update_authored_content(headline="Same headline") == []
        updated = report.update_authored_content(headline="New headline", cause="New cause", confidence=LEDGER)
        assert set(updated) == {"headline", "cause", "confidence", "updated_at"}
        report.save(update_fields=updated)
        report.refresh_from_db()
        assert report.headline == "New headline"
        assert report.cause == "New cause"
        assert report.confidence == LEDGER

    def test_serializer_exposes_the_record(self) -> None:
        report = self._report(SignalReport.Status.READY)
        report.headline = "One-line verdict"
        report.confidence = LEDGER
        report.save()
        data = SignalReportSerializer(report).data
        assert data["headline"] == "One-line verdict"
        assert data["confidence"] == LEDGER
        assert data["cause"] is None
        assert data["fix_size"] is None
        assert data["not_this"] is None


class TestPresentationOutputSchema(BaseTest):
    def _output(self, **overrides) -> ReportPresentationOutput:
        payload = {
            "title": "fix(checkout): handle expired sessions",
            "summary": "Users hit a dead end.",
            "headline": "Users hit a dead end on expired checkout sessions.",
            "impact": "Around 40 checkouts a day end in an error page.",
            "confidence": LEDGER,
            **overrides,
        }
        return ReportPresentationOutput.model_validate(payload)

    def test_ledger_entries_are_stripped_and_empties_dropped(self) -> None:
        output = self._output(
            confidence={"verified": ["  a claim  ", "", "   "], "measured": [], "inferred": [], "unverified": []}
        )
        assert output.confidence.verified == ["a claim"]

    def test_whitespace_only_optional_fields_normalize_to_none(self) -> None:
        output = self._output(cause="   ", fix_size="", not_this="\n", recommended_action=" ")
        assert output.cause is None
        assert output.fix_size is None
        assert output.not_this is None
        assert output.recommended_action is None

    def test_empty_verified_list_is_valid(self) -> None:
        # An empty verified list is the honest shape of a speculative report, never an error.
        output = self._output(
            confidence={"verified": [], "measured": [], "inferred": [], "unverified": ["could not check"]}
        )
        assert output.confidence.verified == []

    def test_confidence_ledger_is_required(self) -> None:
        try:
            ReportPresentationOutput.model_validate({"title": "t", "summary": "s", "headline": "h", "impact": "i"})
        except Exception:
            return
        raise AssertionError("confidence should be required on the presentation output")
