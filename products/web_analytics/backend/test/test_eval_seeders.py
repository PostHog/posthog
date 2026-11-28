import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import DateRange, WebVitalsMetric, WebVitalsPathBreakdownQuery, WebVitalsPercentile

from posthog.models.utils import uuid7

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner
from products.web_analytics.evals.eval_mcp_web_questions import CASES, READY_PROMPT_SEEDERS
from products.web_analytics.evals.ready_prompts import READY_PROMPTS
from products.web_analytics.evals.seeders import (
    WEB_VITALS_TRAP_PATH,
    seed_ai_agent_traffic,
    seed_audience,
    seed_daily_visitors,
    seed_goal_conversions_by_channel,
    seed_highest_bounce_landing_page,
    seed_ready_compare_periods,
    seed_ready_top_pages,
    seed_ready_worst_bounce_landing_pages,
    seed_ready_yesterday_vs_last_week,
    seed_signup_conversion_rate,
    seed_signups_by_channel,
    seed_top_channel,
    seed_top_countries,
    seed_top_pages,
    seed_top_referrers,
    seed_traffic_change_drivers,
    seed_traffic_sources,
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
            for day in ("2025-01-21", "2025-01-27", "2025-01-28"):
                if day == "2025-01-21" and n % 2:
                    continue
                session_id = str(uuid7(f"{day}T09:00:00Z"))
                for path in ("/",) if n % 5 == 4 else ("/", "/pricing/"):
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
                            "$device_type": "Mobile" if n % 4 == 0 else "Desktop",
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
            (seed_unique_visitors, "About 25 unique visitors in the last 7 days (sessions 50, pageviews 90)."),
            (seed_top_pages, "Top 5 pages by visitors, in order: / (25 visitors), /pricing/ (20 visitors)."),
            (
                seed_highest_bounce_landing_page,
                "/ with a bounce rate of 20.0% (25 visitors). Only landing pages with at least 20 visitors qualify.",
            ),
            (
                seed_week_over_week,
                "Over the last 7 complete days visitors were 25 against 13 in the 7 days before (92.0%), pageviews 90 against 23 (291.0%). The window ends yesterday; today's partial day is left out.",
            ),
            (
                seed_top_channel,
                "Direct brought the most traffic. Top channels by visitors: Direct (13), Organic Search (12).",
            ),
            (seed_signups_by_channel, "Direct brought the most sign-ups: 6 'signed_up' conversions from 13 visitors."),
            (seed_top_countries, "Top countries by visitors: US (16), GB (9)."),
            (seed_top_referrers, "Top referring domains by visitors: $direct (13), google.com (12)."),
            (seed_signup_conversion_rate, "20.0% of visitors signed up: 5 of 25."),
            (
                seed_yesterday_vs_last_week,
                "Yesterday: 25 sessions against 13 on the same day last week (92.0%); average session duration 336s against 415s.",
            ),
            (
                seed_daily_visitors,
                "Daily unique visitors over the last 14 days, last day partial: 2025-01-21: 13, 2025-01-27: 25, 2025-01-28: 25.",
            ),
            (
                seed_weekly_digest,
                "Last 7 complete days (2025-01-22 to 2025-01-28): 25.0 visitors, Up 92% versus the 7 days before; 90.0 pageviews; bounce rate 20.0%. Top pages: /, /pricing/. Test accounts included.",
            ),
            (
                seed_ready_compare_periods,
                "This period 2025-01-22 to 2025-01-28 against the previous period 2025-01-15 to 2025-01-21, today left out: visitors 25 against 13 (92.0%); views 90 against 23 (291.0%); sessions 50 against 13 (285.0%); bounce rate 20.0% against 23.1% (-13.0%); session duration 336s against 415s (-19.0%).",
            ),
            (
                seed_ready_yesterday_vs_last_week,
                "Yesterday (2025-01-28) against the same weekday a week earlier (2025-01-21): sessions 25 against 13 (92.0%); visitors 25 against 13 (92.0%); session duration 336s against 415s (-19.0%).",
            ),
            (
                seed_ready_top_pages,
                "Top pages by visitors over the last 7 days, in order: / (25 visitors, 50 pageviews, 20.0% bounce rate), /pricing/ (20 visitors, 40 pageviews, 0.0% bounce rate).",
            ),
            (
                seed_ready_worst_bounce_landing_pages,
                "Landing pages with at least 20 visitors, worst bounce rate first: / (20.0% bounce rate, 25 visitors).",
            ),
            (
                seed_traffic_change_drivers,
                "Visitors went from 13 to 25 (92.0%), 2025-01-22 to 2025-01-28 against 2025-01-15 to 2025-01-21. Channels that moved most: Organic Search (0 to 12). Referring domains that moved most: google.com (0 to 12). Landing pages that moved most: / (13 to 25). Biggest driver: Organic Search or google.com or /.",
            ),
            (
                seed_traffic_sources,
                "Top channels by visitors: Direct (13, 52.0%), Organic Search (12, 48.0%). Top referring domains: $direct (13), google.com (12).",
            ),
            (
                seed_goal_conversions_by_channel,
                "Channels by 'signed_up' conversions over the last 7 days: Direct (6 conversions from 13 visitors, 23.1%), Organic Search (4 conversions from 12 visitors, 16.7%).",
            ),
            (
                seed_audience,
                "Top countries by visitors: US (16), GB (9). Device types: Desktop (18, 72.0%), Mobile (7, 28.0%).",
            ),
        ]
    )
    def test_oracle_seeders_answer_from_the_seeded_team(self, seeder, expected_answer: str) -> None:
        self._seed_traffic()

        with time_machine.travel(NOW, tick=False):
            result = seeder(self._context())

        assert result["oracle"]["answer"] == expected_answer
        assert result["oracle"]["tolerance"]

    def _seed_pageview(self, distinct_id: str, timestamp: str, referring_domain: str, path: str) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$session_id": str(uuid7(timestamp)),
                "$current_url": f"https://example.com{path}",
                "$pathname": path,
                "$referring_domain": referring_domain,
            },
        )

    def test_traffic_change_seed_names_the_source_of_new_visitors(self) -> None:
        self._seed_traffic()
        for n in range(10):
            self._seed_pageview(f"searcher_{n}", f"2025-01-27T10:0{n}:00Z", "google.com", "/blog/")
        flush_persons_and_events()

        with time_machine.travel(NOW, tick=False):
            answer = seed_traffic_change_drivers(self._context())["oracle"]["answer"]

        assert answer == (
            "Visitors went from 13 to 35 (169.0%), 2025-01-22 to 2025-01-28 against 2025-01-15 to 2025-01-21. "
            "Channels that moved most: Organic Search (0 to 22). Referring domains that moved most: google.com (0 to 22). "
            "Landing pages that moved most: / (13 to 25), /blog/ (0 to 10). Biggest driver: Organic Search or google.com."
        )

    def test_traffic_change_seed_credits_no_single_source_when_visitors_hold_flat(self) -> None:
        for n in range(10):
            self._seed_pageview(f"regular_{n}", f"2025-01-21T10:0{n}:00Z", "$direct" if n < 5 else "google.com", "/")
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=f"regular_{n}",
                timestamp=f"2025-01-28T10:0{n}:00Z",
                properties={
                    "$session_id": str(uuid7(f"2025-01-28T10:0{n}:00Z")),
                    "$current_url": "https://example.com/",
                    "$pathname": "/",
                    "$referring_domain": "google.com",
                },
            )
        flush_persons_and_events()

        with time_machine.travel(NOW, tick=False):
            answer = seed_traffic_change_drivers(self._context())["oracle"]["answer"]

        assert answer == (
            "Visitors went from 10 to 10 (0.0%), 2025-01-22 to 2025-01-28 against 2025-01-15 to 2025-01-21. "
            "Channels that moved most: Direct (5 to 0), Organic Search (5 to 10). "
            "Referring domains that moved most: $direct (5 to 0), google.com (5 to 10). "
            "Landing pages that moved most: none. No single source explains the change."
        )

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

    def test_ai_agent_traffic_seed_counts_ai_agents_apart_from_people_and_other_bots(self) -> None:
        _create_person(team_id=self.team.pk, distinct_ids=["early-gptbot"])
        # Inside the day seven days back, but more than seven times 24 hours before NOW.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="early-gptbot",
            timestamp="2025-01-22T06:00:00Z",
            properties={
                "$raw_user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"
            },
        )
        flush_persons_and_events()

        with time_machine.travel(NOW, tick=False):
            answer = seed_ai_agent_traffic(self._context())["oracle"]["answer"]

        assert answer == (
            "Pageviews over the last 7 days by traffic type: Regular 120 (59.7%), AI Agent 66 (32.8%), Bot 15 (7.5%). "
            "AI agents with the most pageviews: GPTBot (41), Claude (25)."
        )


class TestReadyPromptEvalCases(SimpleTestCase):
    def test_every_ready_prompt_is_asked_word_for_word_with_an_oracle(self) -> None:
        prompts = {prompt.name: prompt for prompt in READY_PROMPTS}
        assert len(prompts) == len(READY_PROMPTS)
        assert set(READY_PROMPT_SEEDERS) == set(prompts)

        ready_cases = {case.metadata["ready_prompt"]: case for case in CASES if "ready_prompt" in case.metadata}
        assert set(ready_cases) == set(READY_PROMPT_SEEDERS)
        for name, case in ready_cases.items():
            assert case.prompt.startswith(prompts[name].text), name
            assert case.expected == {"first_relevant_tool": {"tool": prompts[name].tools[0]}}, name
        assert ready_cases["web-analytics-goal-conversion-by-channel"].prompt.endswith("\n\ngoal: signed_up")
