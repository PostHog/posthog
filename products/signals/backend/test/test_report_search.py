import json
import datetime
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team

from products.signals.backend.models import SignalReport
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embedding_reader import REPORT_EMBEDDINGS_TABLE
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE_SUMMARY
from products.signals.backend.report_search import keyword_terms

SEARCH = "products.signals.backend.report_search"


def _vector(x: float, y: float) -> list[float]:
    return [x, y] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


class TestKeywordTerms(SimpleTestCase):
    @parameterized.expand(
        [
            ("strips_quotes_and_punctuation", '"Checkout" fails, again.', ["checkout", "fails", "again"]),
            ("keeps_identifiers_whole", "ai_ ingestion-lag", ["ai_", "ingestion-lag"]),
            ("drops_words_with_no_indexable_text", "is a db down", ["down"]),
            ("deduplicates_case_insensitively", "Error error ERROR", ["error"]),
            ("caps_the_term_count", " ".join(f"term{i}" for i in range(12)), [f"term{i}" for i in range(8)]),
        ]
    )
    def test_splits_a_query_into_indexable_terms(self, _name: str, query: str, expected: list[str]) -> None:
        assert keyword_terms(query) == expected


class TestReportSearchAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(f"TRUNCATE TABLE {REPORT_EMBEDDINGS_TABLE}", flush=False, team_id=self.team.pk)
        self.inserted_at = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).replace(microsecond=0)
        patch(f"{SEARCH}.feature_enabled_or_false", return_value=True).start()
        self.embed = patch(
            "posthog.api.embedding_worker.generate_embedding",
            return_value=EmbeddingResponse(_vector(1.0, 0.0), 1, False),
        ).start()
        self.addCleanup(patch.stopall)

    def _report(self, title: str, *, team: Team | None = None, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(
            team=team or self.team, title=title, summary=f"{title}. More detail follows.", status=status
        )

    def _embed(
        self, report: SignalReport, vector: list[float], *, hours: int = 0, deleted: bool = False, team_id: int = 0
    ) -> None:
        at = self.inserted_at + datetime.timedelta(hours=hours)
        sync_execute(
            f"""
            INSERT INTO {REPORT_EMBEDDINGS_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            [
                (
                    team_id or report.team_id,
                    "signals",
                    "report",
                    EMBEDDING_RENDERING_TITLE_SUMMARY,
                    str(report.id),
                    self.inserted_at,
                    at,
                    "a report",
                    json.dumps({"deleted": deleted}),
                    vector,
                    at,
                    0,
                    0,
                )
            ],
            flush=False,
            team_id=team_id or report.team_id,
        )

    def _search(self, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/reports/search/", params)

    def test_a_report_matched_by_both_sides_outranks_one_matched_by_either(self) -> None:
        semantic_only = self._report("Purchases stall after the payment step")
        self._embed(semantic_only, _vector(1.0, 0.0))
        both = self._report("Checkout button does nothing")
        self._embed(both, _vector(0.9, 0.2))
        # Older than the vector TTL, so it has no vector and can match on keywords only.
        keyword_only = self._report("Checkout page shows a blank modal")

        response = self._search(query="checkout")

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["semantic_available"] is True
        assert [(row["id"], row["match_kinds"]) for row in body["results"]] == [
            (str(both.id), ["keyword", "semantic"]),
            (str(semantic_only.id), ["semantic"]),
            (str(keyword_only.id), ["keyword"]),
        ] or [(row["id"], row["match_kinds"]) for row in body["results"]] == [
            (str(both.id), ["keyword", "semantic"]),
            (str(keyword_only.id), ["keyword"]),
            (str(semantic_only.id), ["semantic"]),
        ]

    def test_only_this_teams_live_reports_match(self) -> None:
        live = self._report("Checkout button does nothing")
        self._embed(live, _vector(0.9, 0.2))
        retracted = self._report("Unrelated title")
        self._embed(retracted, _vector(1.0, 0.0), hours=0)
        self._embed(retracted, _vector(1.0, 0.0), hours=1, deleted=True)
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        foreign = self._report("Checkout button does nothing", team=other_team)
        self._embed(foreign, _vector(1.0, 0.0))
        # A vector stored under this team that names another team's report must not leak it either.
        self._embed(foreign, _vector(1.0, 0.0), team_id=self.team.pk)

        response = self._search(query="checkout button")

        assert response.status_code == 200, response.json()
        assert [row["id"] for row in response.json()["results"]] == [str(live.id)]

    @parameterized.expand([("hybrid", 200), ("semantic", 503)])
    def test_a_failed_semantic_side_degrades_only_a_hybrid_search(self, mode: str, expected_status: int) -> None:
        report = self._report("Checkout button does nothing")
        self._embed(report, _vector(1.0, 0.0))
        self.embed.side_effect = RuntimeError("embedding worker down")

        response = self._search(query="checkout", search_mode=mode)

        assert response.status_code == expected_status
        if expected_status == 200:
            assert response.json()["semantic_available"] is False
            assert [row["match_kinds"] for row in response.json()["results"]] == [["keyword"]]

    def test_a_query_with_no_indexable_text_returns_semantic_matches_only(self) -> None:
        keyword_bait = self._report("Is it ok")
        semantic = self._report("Purchases stall after the payment step")
        self._embed(semantic, _vector(1.0, 0.0))

        response = self._search(query="is ok")

        assert response.status_code == 200, response.json()
        assert [(row["id"], row["match_kinds"]) for row in response.json()["results"]] == [
            (str(semantic.id), ["semantic"])
        ]
        assert str(keyword_bait.id) not in {row["id"] for row in response.json()["results"]}

    def test_a_status_filter_still_fills_the_page_when_the_nearest_reports_are_filtered_out(self) -> None:
        for index in range(3):
            dismissed = self._report(f"Dismissed {index}", status=SignalReport.Status.SUPPRESSED)
            self._embed(dismissed, _vector(1.0, 0.0))
        ready = [self._report(f"Ready {index}") for index in range(2)]
        for report in ready:
            self._embed(report, _vector(0.2, 1.0))

        # The dismissed reports fill every candidate slot, so the filter must apply before the vector read limit.
        with patch(f"{SEARCH}.CANDIDATES", 3):
            filtered = self._search(query="purchases stall", status="ready", limit=2)
        unfiltered = self._search(query="purchases stall", limit=3)

        assert filtered.status_code == 200, filtered.json()
        assert {row["id"] for row in filtered.json()["results"]} == {str(report.id) for report in ready}
        # Without a status filter, dismissed reports are searched too, so an agent sees what a person closed.
        assert {row["status"] for row in unfiltered.json()["results"]} == {SignalReport.Status.SUPPRESSED}

    def test_returns_404_when_the_flag_is_off(self) -> None:
        with patch(f"{SEARCH}.feature_enabled_or_false", return_value=False):
            assert self._search(query="checkout").status_code == 404
