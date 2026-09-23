from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.signal_queries import fetch_report_ids_for_search_terms

VIEWS_FETCH_BY_SEARCH = "products.signals.backend.views.fetch_report_ids_for_search_terms"


class TestReportIdsForSearchTerms(APIBaseTest):
    def test_query_compiles_against_clickhouse(self) -> None:
        # The evidence leg reads `content` and an aliased `source_id` out of the shared dedup
        # subquery, which exposes `metadata` as an argMax alias. If HogQL rejects either, every
        # search degrades to the report's own content and the evidence match silently never fires.
        assert fetch_report_ids_for_search_terms(self.team, ["web", "vitals"]) == set()

    def test_no_terms_skips_clickhouse(self) -> None:
        with patch("products.signals.backend.temporal.signal_queries.execute_hogql_query") as execute:
            assert fetch_report_ids_for_search_terms(self.team, []) == set()
        execute.assert_not_called()


class TestReportSearch(APIBaseTest):
    def _search(self, query: str) -> list[str]:
        with patch(VIEWS_FETCH_BY_SEARCH, return_value=set()):
            response = self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?search={query}")
        assert response.status_code == 200
        return [row["id"] for row in response.json()["results"]]

    def _report(self, title: str, summary: str = "") -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title=title, summary=summary
        )

    @parameterized.expand(
        [
            # An event name carries punctuation the report's prose does not, and vice versa.
            ("event name against prose", "$web_vitals", "Web Vitals are slow on mobile", ""),
            ("prose against event name", "web vitals", "$web_vitals p75 regressed", ""),
            # Independent terms: the caller's own wording, not the phrase the report is titled with.
            ("terms out of order", "Toronto registration", "Registration drops for users in Toronto", ""),
            # ...and one term may match the title while another matches the summary.
            ("terms across fields", "toronto signup", "Signup funnel regressed", "Only in Toronto"),
        ]
    )
    def test_search_finds_a_report_worded_differently(self, _name: str, query: str, title: str, summary: str) -> None:
        report = self._report(title, summary)
        assert self._search(query) == [str(report.id)]

    def test_every_term_still_has_to_match(self) -> None:
        # Independent terms widen how a term may match, not which reports match: a report missing
        # one of them is a different report, and returning it would hide the real duplicate.
        self._report("Registration drops for users in Toronto")
        assert self._search("toronto checkout") == []

    @parameterized.expand(
        [
            # A research pass rewrites the summary, so what an earlier pass found can live on only
            # in the work log. Without this a second scout files the report the first one noted.
            ("a word of the note text", "toronto", True),
            # A note is stored as a serialized object, so the names it is stored under sit in the
            # same column as the text. Matching those would return every researched report to a
            # caller who meant the word.
            ("the key the text is stored under", "note", False),
            ("the key beside it", "author", False),
        ]
    )
    def test_search_matches_the_text_of_a_work_log_note_only(self, _name: str, query: str, matches: bool) -> None:
        report = self._report("Signup funnel regressed")
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=NoteArtefact(note="Reproduced against the Toronto region.").model_dump_json(),
        )
        assert self._search(query) == ([str(report.id)] if matches else [])

    def test_search_finds_a_report_whose_evidence_alone_matches(self) -> None:
        # The identifier a caller searches for is often only in the evidence: an emitter's own
        # record id never reaches the title. ClickHouse holds that, so it answers alongside Postgres.
        report = self._report("Checkout errors climbing")
        with patch(VIEWS_FETCH_BY_SEARCH, return_value={str(report.id)}) as fetch:
            response = self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?search=order_1234")

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [str(report.id)]
        assert fetch.call_args.args[1] == ["order", "1234"]

    def test_search_degrades_when_the_evidence_lookup_fails(self) -> None:
        # The inbox searches on every keystroke, so a ClickHouse fault must narrow what search can
        # find rather than fail the list.
        report = self._report("Checkout errors climbing")
        with patch(VIEWS_FETCH_BY_SEARCH, side_effect=Exception("clickhouse unavailable")):
            response = self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?search=checkout")

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [str(report.id)]

    def test_a_search_of_only_punctuation_does_not_match_everything(self) -> None:
        self._report("Checkout errors climbing")
        assert self._search("%") == []

    def test_absent_search_does_not_touch_clickhouse(self) -> None:
        self._report("Checkout errors climbing")
        with patch(VIEWS_FETCH_BY_SEARCH) as fetch:
            response = self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?limit=10")

        assert response.status_code == 200
        fetch.assert_not_called()

    def test_rejects_a_search_longer_than_the_shared_cap(self) -> None:
        # Same cap every other searchable list applies, so one pasted blob cannot drive an
        # unbounded substring scan across the team's reports and their evidence.
        response = self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?search={'a' * 201}")
        assert response.status_code == 400
        assert "200 characters or fewer" in str(response.json())
