from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_search import report_search_terms
from products.signals.backend.temporal.signal_queries import fetch_report_ids_by_search_term

VIEWS_FETCH_BY_SEARCH = "products.signals.backend.views.fetch_report_ids_by_search_term"


class TestReportSearchTerms(SimpleTestCase):
    @parameterized.expand(
        [
            # An accented word is one word to the person who typed it. Splitting it leaves
            # single-letter fragments, and a fragment that short matches nearly every report.
            ("an accented word", "Müller", ["Müller"]),
            # The same word typed as a letter plus a combining accent, which without composing
            # splits into "Mu" and "ller", matching neither the report nor itself.
            ("an accent typed as a combining mark", "Mu\u0308ller", ["Müller"]),
            # Terms a reader can see are terms, whatever the script.
            ("a script without spaces between words", "東京 登録", ["東京", "登録"]),
            # The apostrophe separates, so a possessive or a contraction leaves one Latin letter
            # behind. Every term has to match, so keeping it excludes any report without that
            # letter: "can't" would stop finding a report titled "Cancel", which holds no "t".
            ("a possessive", "Toronto's registration", ["Toronto", "registration"]),
            ("a contraction", "can't", ["can"]),
            # A digit is a term the caller meant, and so is a script that writes a word in one
            # character, so neither is dropped.
            ("a single digit", "issue 5", ["issue", "5"]),
            ("a single character word", "東 registration", ["東", "registration"]),
            # The cap is part of the documented contract on the `search` parameter.
            ("more terms than the cap", "a1 b2 c3 d4 e5 f6 g7 h8 i9", ["a1", "b2", "c3", "d4", "e5", "f6", "g7", "h8"]),
        ]
    )
    def test_search_splits_into_the_terms_a_report_must_match(
        self, _name: str, search: str, expected: list[str]
    ) -> None:
        assert report_search_terms(search) == expected


class TestReportIdsForSearchTerms(APIBaseTest):
    def test_query_compiles_against_clickhouse(self) -> None:
        # The evidence leg reads `content` and an aliased `source_id` out of the shared dedup
        # subquery, which exposes `metadata` as an argMax alias. If HogQL rejects either, every
        # search degrades to the report's own content and the evidence match silently never fires.
        assert fetch_report_ids_by_search_term(self.team, ["web", "vitals"]) == {"web": set(), "vitals": set()}

    def test_no_terms_skips_clickhouse(self) -> None:
        with patch("products.signals.backend.temporal.signal_queries.execute_hogql_query") as execute:
            assert fetch_report_ids_by_search_term(self.team, []) == {}
        execute.assert_not_called()


class TestReportSearch(APIBaseTest):
    def _search(self, query: str, evidence: dict[str, set[str]] | None = None) -> list[str]:
        with patch(VIEWS_FETCH_BY_SEARCH, return_value=evidence or {}):
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
            # Each term needs its own note lookup. Building one for the whole query instead makes
            # every term match whichever term the note happens to hold.
            ("a word of the title and a word of the note", "signup toronto", True),
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

    @parameterized.expand(
        [
            # An object the search cannot parse. A jsonb cast of it raises, and the note lookup
            # runs against every report, so one such row turned every search into a 500.
            ("an object that does not parse", "{not json"),
            # A note written before the text was stored inside an object.
            ("plain text with no object around it", "a legacy note about the Toronto region"),
        ]
    )
    def test_a_note_the_search_cannot_read_drops_out_instead_of_failing_the_list(
        self, _name: str, content: str
    ) -> None:
        findable = self._report("Signup funnel regressed in Toronto")
        unreadable = self._report("Checkout errors climbing")
        SignalReportArtefact.objects.create(
            team=self.team,
            report=unreadable,
            type=SignalReportArtefact.ArtefactType.NOTE,
            content=content,
        )
        assert self._search("toronto") == [str(findable.id)]

    @parameterized.expand(
        [
            # The identifier a caller searches for is often only in the evidence: an emitter's own
            # record id never reaches the title.
            ("every term in the evidence", "order_1234", ["order", "1234"], True),
            # The caller writes one word it remembers of the report and one identifier it is
            # holding. Those sit in different stores, so combining the stores as whole
            # alternatives matches neither, and the caller files the duplicate it searched for.
            ("a term from each store", "checkout order1234", ["order1234"], True),
            # Combining the stores per term widens where a term may match, not which reports do.
            ("a term neither store holds", "checkout order1234 toronto", ["order1234"], False),
        ]
    )
    def test_search_combines_a_report_and_its_evidence_per_term(
        self, _name: str, query: str, evidence_terms: list[str], matches: bool
    ) -> None:
        report = self._report("Checkout errors climbing")
        evidence = {term: {str(report.id)} for term in evidence_terms}
        assert self._search(query, evidence) == ([str(report.id)] if matches else [])

    def test_the_evidence_lookup_receives_the_split_terms(self) -> None:
        # The lookup answers per term, so handing it the caller's raw string would make the
        # evidence leg search for a phrase no single signal contains.
        self._report("Checkout errors climbing")
        with patch(VIEWS_FETCH_BY_SEARCH, return_value={}) as fetch:
            self.client.get(f"/api/projects/{self.team.pk}/signals/reports/?search=order_1234")

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
