from types import SimpleNamespace
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models import Team

from products.error_tracking.backend.facade.testing import create_issue
from products.signals.backend.error_tracking_reports import references_error_tracking_issue
from products.signals.backend.models import ArtefactAttribution, SignalReport
from products.signals.backend.report_merge import merge_reports, merge_survivor_ids
from products.signals.backend.temporal.signal_queries import fetch_live_report_ids_for_source_ids

VIEWS_FETCH = "products.signals.backend.views.fetch_live_report_ids_for_source_ids"
VIEWS_FETCH_BY_PRODUCT = "products.signals.backend.views.fetch_report_ids_for_source_products"
TICKET_ID = "019f9373-1e60-0000-3928-d8b21e6e8cb0"


@override_settings(SITE_URL="https://us.posthog.com")
class TestErrorTrackingIssueReferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("canonical", f"[error](https://us.posthog.com/project/2/error-tracking/{TICKET_ID})", True),
            ("legacy", f"[error](https://app.posthog.com/project/2/error_tracking/{TICKET_ID}?x=1#events)", True),
            ("relative", f"[error](/error-tracking/{TICKET_ID}/)", True),
            ("inline code", f"`https://us.posthog.com/project/2/error-tracking/{TICKET_ID}`", True),
            ("code block", f"```\n/error_tracking/{TICKET_ID}\n```", True),
            ("bare id", TICKET_ID, False),
            ("other project", f"https://us.posthog.com/project/3/error-tracking/{TICKET_ID}", False),
            ("other host", f"https://example.com/project/2/error-tracking/{TICKET_ID}", False),
            ("other product", f"https://us.posthog.com/project/2/insights/{TICKET_ID}", False),
            ("suffix", f"https://us.posthog.com/project/2/error-tracking/{TICKET_ID}a", False),
            ("nested url", f"https://example.com/?next=/project/2/error-tracking/{TICKET_ID}", False),
            ("userinfo", f"https://us.posthog.com@example.com/project/2/error-tracking/{TICKET_ID}", False),
            ("other scheme", f"javascript:https://us.posthog.com/project/2/error-tracking/{TICKET_ID}", False),
        ]
    )
    def test_accepts_only_exact_issue_urls(self, _name: str, text: str, expected: bool) -> None:
        assert references_error_tracking_issue(text, issue_id=UUID(TICKET_ID), team_id=2) is expected


class TestLiveReportIdsForSourceIds(APIBaseTest):
    def test_query_compiles_against_clickhouse(self) -> None:
        # Regression guard for the alias-collision class documented on
        # fetch_report_ids_for_source_ids: this query pushes the source_id filter into the shared
        # dedup subquery (which exposes `metadata` as an argMax alias) and then filters an aliased
        # `source_product` in an outer WHERE. If HogQL rejects either, the helper raises on every
        # call and the caller degrades to "no linked reports" for everyone, silently. Run it for
        # real against an empty ClickHouse: it must compile and return an empty map.
        assert fetch_live_report_ids_for_source_ids(self.team, [TICKET_ID]) == {}
        assert fetch_live_report_ids_for_source_ids(self.team, [TICKET_ID], "conversations") == {}

    def test_no_source_ids_skips_clickhouse(self) -> None:
        with patch("products.signals.backend.temporal.signal_queries.execute_hogql_query") as execute:
            assert fetch_live_report_ids_for_source_ids(self.team, []) == {}
        execute.assert_not_called()


class TestReportsSourceIdFilter(APIBaseTest):
    def _url(self, query: str) -> str:
        return f"/api/projects/{self.team.pk}/signals/reports/?{query}"

    def setUp(self) -> None:
        super().setUp()
        self.linked = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="linked to the ticket"
        )
        self.unlinked = SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY, title="unrelated")

    def test_filters_to_reports_the_source_record_contributed_to(self) -> None:
        with (
            patch(VIEWS_FETCH, return_value={TICKET_ID: [str(self.linked.id)]}) as fetch,
            patch(VIEWS_FETCH_BY_PRODUCT) as fetch_by_product,
        ):
            response = self.client.get(self._url(f"source_id={TICKET_ID}&source_product=conversations"))

        assert response.status_code == 200
        assert [r["id"] for r in response.json()["results"]] == [str(self.linked.id)]
        # A single source_product narrows the ClickHouse scan.
        assert fetch.call_args.args[1:] == ([TICKET_ID], "conversations")
        # ...and makes the wider source_product lookup redundant, so it must not also run.
        fetch_by_product.assert_not_called()

    @parameterized.expand(
        [
            ("no product at all", f"source_id={TICKET_ID}"),
            ("several products", f"source_id={TICKET_ID}&source_product=conversations,zendesk"),
        ]
    )
    def test_rejects_a_source_id_without_exactly_one_product(self, _name: str, query: str) -> None:
        # A source id is only unique within a product (emitters pass through the external system's own
        # id), so filtering without one would quietly mix products together.
        with patch(VIEWS_FETCH) as fetch:
            response = self.client.get(self._url(query))

        assert response.status_code == 400
        assert "source_product" in str(response.json())
        fetch.assert_not_called()

    def test_unknown_source_id_returns_nothing_rather_than_everything(self) -> None:
        with patch(VIEWS_FETCH, return_value={}), patch(VIEWS_FETCH_BY_PRODUCT):
            response = self.client.get(self._url("source_id=not-a-known-source&source_product=conversations"))

        assert response.json()["results"] == []

    def test_absent_filter_does_not_touch_clickhouse(self) -> None:
        with patch(VIEWS_FETCH) as fetch:
            response = self.client.get(self._url("limit=10"))

        assert response.status_code == 200
        fetch.assert_not_called()

    def test_error_tracking_filter_reuses_visible_reports_and_ignores_untrusted_report_ids(self) -> None:
        issue_id = create_issue(team_id=self.team.id, name="Example error")
        suppressed = SignalReport.objects.create(team=self.team, status=SignalReport.Status.SUPPRESSED)
        deleted = SignalReport.objects.create(team=self.team, status=SignalReport.Status.DELETED)
        with patch(
            "products.signals.backend.error_tracking_reports.execute_hogql_query",
            return_value=SimpleNamespace(
                results=[
                    [str(self.linked.id), str(issue_id), "error_tracking", "evidence"],
                    [str(suppressed.id), str(issue_id), "error_tracking", "evidence"],
                    [str(deleted.id), str(issue_id), "error_tracking", "evidence"],
                    ["invalid-report-id", str(issue_id), "error_tracking", "evidence"],
                ]
            ),
        ):
            response = self.client.get(self._url(f"error_tracking_issue_id={issue_id}"))

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [str(self.linked.id)]

    @parameterized.expand([("unknown", False), ("other team", True)])
    def test_unknown_error_tracking_issue_skips_evidence_query(self, _name: str, other_team: bool) -> None:
        issue_id = UUID(TICKET_ID)
        if other_team:
            team = Team.objects.create(organization=self.organization, name="Another project")
            issue_id = create_issue(team_id=team.id, name="Other project's error")
        with patch("products.signals.backend.error_tracking_reports.execute_hogql_query") as query:
            response = self.client.get(self._url(f"error_tracking_issue_id={issue_id}"))

        assert response.status_code == 200
        assert response.json()["results"] == []
        query.assert_not_called()

    def test_error_tracking_filter_returns_merge_survivor_before_signal_move(self) -> None:
        issue_id = create_issue(team_id=self.team.id, name="Example error")
        merge_reports(
            team=self.team,
            survivor=self.linked,
            source_ids=[str(self.unlinked.id)],
            attribution=ArtefactAttribution.from_user(self.user.id),
        )
        with patch(
            "products.signals.backend.error_tracking_reports.execute_hogql_query",
            return_value=SimpleNamespace(
                results=[[str(self.unlinked.id), str(issue_id), "error_tracking", "evidence"]]
            ),
        ):
            response = self.client.get(self._url(f"error_tracking_issue_id={issue_id}"))

        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [str(self.linked.id)]

    def test_merge_resolution_queries_each_shared_level_once(self) -> None:
        sources = SignalReport.objects.bulk_create(
            [SignalReport(team=self.team, status=SignalReport.Status.READY) for _ in range(20)]
        )
        for offset in (0, 10):
            merge_reports(
                team=self.team,
                survivor=self.unlinked,
                source_ids=[str(report.id) for report in sources[offset : offset + 10]],
                attribution=ArtefactAttribution.from_user(self.user.id),
            )
        merge_reports(
            team=self.team,
            survivor=self.linked,
            source_ids=[str(self.unlinked.id)],
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

        with self.assertNumQueries(5):
            survivors = merge_survivor_ids(team_id=self.team.id, report_ids=[str(report.id) for report in sources])

        assert survivors == {str(self.linked.id)}

    def test_rejects_malformed_error_tracking_issue_id(self) -> None:
        response = self.client.get(self._url("error_tracking_issue_id=invalid"))
        assert response.status_code == 400
        assert "error_tracking_issue_id" in str(response.json())
