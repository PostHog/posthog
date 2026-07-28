from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.signal_queries import fetch_live_report_ids_for_source_ids

VIEWS_FETCH = "products.signals.backend.views.fetch_live_report_ids_for_source_ids"
VIEWS_FETCH_BY_PRODUCT = "products.signals.backend.views.fetch_report_ids_for_source_products"
TICKET_ID = "019f9373-1e60-0000-3928-d8b21e6e8cb0"


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
