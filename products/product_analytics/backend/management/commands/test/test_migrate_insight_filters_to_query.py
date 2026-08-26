from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.product_analytics.backend.models.insight import Insight

TREND_FILTERS = {"insight": "TRENDS", "events": [{"id": "$pageview", "type": "events", "order": 0}]}


class TestMigrateInsightFiltersToQuery(BaseTest):
    def _run(self, **kwargs) -> None:
        call_command("migrate_insight_filters_to_query", sleep_interval=0, **kwargs)

    @parameterized.expand(
        [
            ("trend", TREND_FILTERS, "TrendsQuery", ["$pageview"]),
            (
                "funnel",
                {
                    "insight": "FUNNELS",
                    "events": [
                        {"id": "$pageview", "type": "events", "order": 0},
                        {"id": "user signed up", "type": "events", "order": 1},
                    ],
                },
                "FunnelsQuery",
                ["$pageview", "user signed up"],
            ),
            # Migration 0545 required an `insight` key and skipped rows without one; the command must not.
            (
                "no_insight_key",
                {"events": [{"id": "$pageview", "type": "events", "order": 0}]},
                "TrendsQuery",
                ["$pageview"],
            ),
        ]
    )
    def test_converts_legacy_filters(self, _name, filters, expected_source_kind, expected_events):
        insight = Insight.objects.create(team=self.team, filters=filters)

        self._run(live=True)

        insight.refresh_from_db()
        assert insight.query is not None
        assert insight.query["kind"] == "InsightVizNode"
        assert insight.query["source"]["kind"] == expected_source_kind
        assert "migrated_at" in insight.filters
        # bulk_update skips the save() hook that derives metadata, so the command derives it. Without that,
        # a converted insight drops out of the `events` list filter and Max's insight search.
        assert insight.query_metadata is not None
        assert sorted(insight.query_metadata["events"]) == sorted(expected_events)

    def test_dry_run_by_default_writes_nothing(self):
        insight = Insight.objects.create(team=self.team, filters=TREND_FILTERS)

        self._run()

        insight.refresh_from_db()
        assert insight.query is None
        assert "migrated_at" not in insight.filters

    def test_converts_empty_shells_and_leaves_query_insights_untouched(self):
        shell = Insight.objects.create(team=self.team)
        existing_query = {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "series": []}}
        query_insight = Insight.objects.create(team=self.team, query=existing_query)

        self._run(live=True)

        shell.refresh_from_db()
        query_insight.refresh_from_db()
        # Shells must land on the same empty trends query they rendered as before, not on some real series.
        assert shell.query is not None
        assert shell.query["source"]["kind"] == "TrendsQuery"
        assert shell.query["source"]["series"] == []
        assert "migrated_at" in shell.filters
        assert query_insight.query == existing_query

    def test_conversion_error_skips_row_and_continues_across_batches(self):
        bad = Insight.objects.create(team=self.team, filters={"insight": "TRENDS", "events": 42})
        good = Insight.objects.create(team=self.team, filters=TREND_FILTERS)
        soft_deleted = Insight.objects.create(team=self.team, deleted=True, filters=TREND_FILTERS)

        self._run(live=True, batch_size=1)

        bad.refresh_from_db()
        good.refresh_from_db()
        soft_deleted.refresh_from_db()
        assert bad.query is None
        assert "migrated_at" not in bad.filters
        assert good.query is not None
        assert soft_deleted.query is not None
