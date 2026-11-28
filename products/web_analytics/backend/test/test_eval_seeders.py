import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, WebVitalsMetric, WebVitalsPathBreakdownQuery, WebVitalsPercentile

from posthog.models.utils import uuid7

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner
from products.web_analytics.evals.seeders import (
    WEB_VITALS_TRAP_PATH,
    seed_daily_visitors,
    seed_highest_bounce_landing_page,
    seed_signup_conversion_rate,
    seed_signups_by_channel,
    seed_top_channel,
    seed_top_countries,
    seed_top_pages,
    seed_top_referrers,
    seed_unique_visitors,
    seed_web_vitals,
    seed_week_over_week,
    seed_weekly_digest,
    seed_yesterday_vs_last_week,
)

NOW = "2025-01-29T12:00:00Z"


class TestWebAnalyticsEvalSeeders(ClickhouseTestMixin, APIBaseTest):
    def _context(self) -> CustomPromptSandboxContext:
        return CustomPromptSandboxContext(team_id=self.team.pk, user_id=self.user.pk)

    def _seed_traffic(self) -> None:
        for n in range(25):
            distinct_id = f"visitor_{n}"
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            for day in ("2025-01-20", "2025-01-27", "2025-01-28"):
                session_id = str(uuid7(f"{day}T09:00:00Z"))
                for path in ("/", "/pricing/"):
                    _create_event(
                        team=self.team,
                        event="$pageview",
                        distinct_id=distinct_id,
                        timestamp=f"{day}T09:0{n % 10}:00Z",
                        properties={
                            "$session_id": session_id,
                            "$current_url": f"https://example.com{path}",
                            "$pathname": path,
                            "$referring_domain": "google.com" if n % 2 else "$direct",
                            "$geoip_country_code": "US" if n % 3 else "GB",
                        },
                    )
                if n % 5 == 0:
                    _create_event(
                        team=self.team,
                        event="signed_up",
                        distinct_id=distinct_id,
                        timestamp=f"{day}T09:30:00Z",
                        properties={"$session_id": session_id},
                    )
        flush_persons_and_events()

    @parameterized.expand(
        [
            (seed_unique_visitors, "unique visitors"),
            (seed_top_pages, "/pricing/"),
            (seed_highest_bounce_landing_page, "bounce rate"),
            (seed_week_over_week, "today's partial day is left out"),
            (seed_top_channel, "brought the most traffic"),
            (seed_signups_by_channel, "sign-ups"),
            (seed_top_countries, "US"),
            (seed_top_referrers, "google.com"),
            (seed_signup_conversion_rate, "signed up"),
            (seed_yesterday_vs_last_week, "same day last week"),
            (seed_daily_visitors, "2025-01-28"),
            (seed_weekly_digest, "2025-01-22 to 2025-01-28"),
        ]
    )
    def test_oracle_seeders_answer_from_the_seeded_team(self, seeder, expected_fragment: str) -> None:
        self._seed_traffic()

        with time_machine.travel(NOW, tick=False):
            result = seeder(self._context())

        assert expected_fragment in result["oracle"]["answer"], result["oracle"]["answer"]
        assert result["oracle"]["tolerance"]

    def test_web_vitals_seed_ranks_busy_slow_pages_above_the_one_sample_trap(self) -> None:
        with time_machine.travel(NOW, tick=False):
            seed_web_vitals(self._context())
            self.team.refresh_from_db()
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from="-7d"),
                metric=WebVitalsMetric.LCP,
                percentile=WebVitalsPercentile.P75,
                thresholds=[2500, 4000],
                properties=[],
                doPathCleaning=True,
            )
            unfloored = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query).calculate().results[0]
            floored = (
                WebVitalsPathBreakdownQueryRunner(team=self.team, query=query.model_copy(update={"minSamples": 10}))
                .calculate()
                .results[0]
            )

        assert [(item.path, item.count) for item in unfloored.poor][:3] == [
            (WEB_VITALS_TRAP_PATH, 1),
            ("/account/billing/", 30),
            ("/files/<id>/", 50),
        ]
        assert [(item.path, item.count) for item in floored.poor] == [("/account/billing/", 30), ("/files/<id>/", 50)]
        assert [item.path for item in floored.needs_improvements] == ["/pricing/"]
        assert [item.path for item in floored.good] == ["/"]
