import datetime
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import IntervalType

from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.emission import SCORER_DISTINCT_ID
from products.signals.backend.anomaly_scores.read import SeriesSummary, prior_rate, rank_series, rollup
from products.signals.backend.anomaly_scores.search import (
    MAX_INSIGHT_SERIES,
    SCORING_DISABLED_MESSAGE,
    SCORING_TURNED_OFF_MESSAGE,
)
from products.signals.backend.models import SignalTeamConfig

NOW = datetime.datetime(2026, 10, 23, 12, tzinfo=datetime.UTC)


def _day(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 10, day, tzinfo=datetime.UTC)


def _summary(
    key: str, *, scored: int, flagged: int, baseline_scored: int = 0, baseline_flagged: int = 0
) -> SeriesSummary:
    return SeriesSummary(
        insight_id=1,
        series_key=key,
        series_label=key,
        breakdown_value=None,
        interval=IntervalType.DAY,
        detector="zscore",
        detector_version="v1",
        profile="default-v1",
        newest_bucket=_day(22),
        scored_buckets=scored,
        flagged_buckets=flagged,
        baseline_scored_buckets=baseline_scored,
        baseline_flagged_buckets=baseline_flagged,
        scored_through=_day(22),
        flagged_points=(),
    )


class TestAnomalyRanking(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "more_evidence_beats_one_lucky_bucket",
                _summary("three_of_ten", scored=10, flagged=3),
                _summary("one_of_one", scored=1, flagged=1),
            ),
            (
                "quiet_baseline_beats_always_noisy",
                _summary("quiet_before", scored=10, flagged=3, baseline_scored=30, baseline_flagged=0),
                _summary("noisy_before", scored=10, flagged=3, baseline_scored=30, baseline_flagged=10),
            ),
            (
                "real_jump_beats_unchanged_noisy",
                _summary("jumped", scored=10, flagged=3, baseline_scored=30, baseline_flagged=0),
                _summary("unchanged", scored=10, flagged=5, baseline_scored=10, baseline_flagged=5),
            ),
        ]
    )
    def test_ranks_series_by_comparable_rates(
        self, _name: str, expected_first: SeriesSummary, other: SeriesSummary
    ) -> None:
        series = [other, expected_first]
        ranked = rank_series(series, prior=prior_rate(series), importance={})

        assert [summary.series_key for summary in ranked] == [expected_first.series_key, other.series_key]

    def test_rollup_sums_buckets_instead_of_averaging_rates(self) -> None:
        insight = rollup(
            [_summary("a", scored=1, flagged=1), _summary("b", scored=9, flagged=1), _summary("c", scored=5, flagged=0)]
        )

        assert (insight.series_count, insight.flagged_series, insight.scored_buckets, insight.flagged_buckets) == (
            3,
            2,
            15,
            2,
        )
        assert insight.anomaly_rate == 2 / 15


@time_machine.travel(NOW, tick=False)
class TestAnomalySearchAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups", saved=True)
        flag = patch("products.signals.backend.presentation.anomalies.feature_enabled_or_false", return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        payload = patch(
            "products.signals.backend.anomaly_scores.search.read_payload",
            return_value={"enabled": True, "organization_ids": [str(self.organization.id)]},
        )
        self.payload = payload.start()
        self.addCleanup(payload.stop)

    def _score(
        self,
        bucket: datetime.datetime,
        *,
        score: float | None,
        flag: int | None,
        scored_at: datetime.datetime = NOW,
        series_key: str = "signups",
        interval: str = "day",
        insight: Insight | None = None,
        team: Team | None = None,
    ) -> None:
        _create_event(
            team=team or self.team,
            event="$anomaly_score",
            distinct_id=SCORER_DISTINCT_ID,
            timestamp=bucket,
            properties={
                "$anomaly_score": score,
                "$anomaly_flag": flag,
                "$anomaly_value": 10.0,
                "$anomaly_bucket_start": bucket.isoformat(),
                "$anomaly_interval": interval,
                "$anomaly_series_key": series_key,
                "$anomaly_source": "insight",
                "$anomaly_insight_id": (insight or self.insight).id,
                "$anomaly_series_label": series_key.title(),
                "$anomaly_breakdown_value": None,
                "$anomaly_detector": "zscore",
                "$anomaly_detector_version": "v1",
                "$anomaly_profile": "default-v1",
                "$anomaly_scored_at": scored_at.isoformat(),
                "$anomaly_details": '{"z": 3.1}',
            },
        )

    def _score_history(self) -> None:
        # Oct 19 was scored twice: the rescore unflagged it. Oct 20 is warm-up, Oct 21 was never scored.
        self._score(_day(19), score=0.99, flag=1, scored_at=_day(20))
        self._score(_day(19), score=0.40, flag=0, scored_at=_day(21))
        self._score(_day(20), score=None, flag=None)
        self._score(_day(22), score=0.98, flag=1)
        self._score(_day(22), score=0.10, flag=0, series_key="logins")
        # Any member can capture a row like this. The scorer never writes a `second` interval.
        self._score(_day(22), score=0.99, flag=1, series_key="forged", interval="second")

    def _get(self, endpoint: str, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/anomalies/{endpoint}/", params)

    def test_search_counts_the_latest_result_of_each_scored_bucket(self) -> None:
        self._score_history()

        response = self._get("search", date_from="2026-10-19")

        assert response.status_code == 200, response.json()
        body = response.json()
        assert (body["scoring_enabled"], body["insights_scored_in_range"], body["message"]) == (True, 1, None)
        assert len(body["series"]) == 1
        row = body["series"][0]
        assert {key: row[key] for key in ("series_key", "scored_buckets", "flagged_buckets", "expected_buckets")} == {
            "series_key": "signups",
            "scored_buckets": 2,
            "flagged_buckets": 1,
            "expected_buckets": 4,
        }
        assert (row["anomaly_rate"], row["coverage"], row["baseline_rate"]) == (0.5, 0.5, None)
        assert row["last_flagged_bucket"] == row["first_flagged_bucket"] == "2026-10-22T00:00:00+00:00"
        assert row["flagged_points"] == [{"bucket_start": "2026-10-22T00:00:00+00:00", "value": 10.0, "score": 0.98}]

    @parameterized.expand(
        [
            ("search_outside_the_payload", "search", False, SCORING_DISABLED_MESSAGE),
            ("insight_outside_the_payload", "insight", False, SCORING_DISABLED_MESSAGE),
            ("search_turned_off_in_settings", "search", True, SCORING_TURNED_OFF_MESSAGE),
            ("insight_turned_off_in_settings", "insight", True, SCORING_TURNED_OFF_MESSAGE),
        ]
    )
    def test_explains_an_empty_result_for_a_team_that_is_not_scored(
        self, _name: str, endpoint: str, turned_off: bool, message: str
    ) -> None:
        if turned_off:
            SignalTeamConfig.objects.create(team=self.team, anomaly_scoring_enabled=False)
        else:
            self.payload.return_value = {"enabled": True, "organization_ids": []}

        body = self._get(endpoint, insight_id=self.insight.id).json()

        assert (body["scoring_enabled"], body["message"]) == (False, message)

    def test_insight_returns_every_bucket_of_each_series_oldest_first(self) -> None:
        self._score_history()

        body = self._get("insight", insight_id=self.insight.id, date_from="2026-10-19").json()

        assert (body["series_count"], body["flagged_series"], body["scored_buckets"], body["flagged_buckets"]) == (
            2,
            1,
            3,
            1,
        )
        series = {row["series_key"]: row for row in body["series"]}
        assert [row["series_key"] for row in body["series"]] == ["signups", "logins"]
        assert [
            (bucket["bucket_start"][:10], bucket["scored"], bucket["score"], bucket["flag"])
            for bucket in series["signups"]["buckets"]
        ] == [
            ("2026-10-19", True, 0.40, False),
            ("2026-10-20", False, None, None),
            ("2026-10-21", False, None, None),
            ("2026-10-22", True, 0.98, True),
        ]
        assert series["signups"]["buckets"][-1]["details"] == {"z": 3.1}

    def test_insight_narrows_to_one_series_and_shows_warmup_on_request(self) -> None:
        self._score_history()

        body = self._get(
            "insight", insight_id=self.insight.id, date_from="2026-10-19", series_key="signups", include_warmup=True
        ).json()

        assert [row["series_key"] for row in body["series"]] == ["signups"]
        warmup = body["series"][0]["buckets"][1]
        assert (warmup["bucket_start"][:10], warmup["scored"], warmup["score"], warmup["value"]) == (
            "2026-10-20",
            True,
            None,
            10.0,
        )

    def test_insight_caps_series_at_the_scorer_maximum(self) -> None:
        for index in range(MAX_INSIGHT_SERIES + 1):
            self._score(_day(22), score=0.5, flag=0, series_key=f"series_{index}")

        body = self._get("insight", insight_id=self.insight.id, date_from="2026-10-19").json()

        assert (len(body["series"]), body["series_count"], body["truncated"]) == (
            MAX_INSIGHT_SERIES,
            MAX_INSIGHT_SERIES + 1,
            True,
        )

    def test_insight_returns_404_for_an_insight_the_user_cannot_read(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_insight = Insight.objects.create(team=other_team, name="Other", saved=True)
        self._score(_day(22), score=0.98, flag=1, insight=other_insight)

        assert self._get("insight", insight_id=other_insight.id).status_code == 404
        assert self._get("search", date_from="2026-10-19").json()["series"] == []

    @parameterized.expand([("search",), ("insight",)])
    def test_returns_404_when_the_flag_is_off(self, endpoint: str) -> None:
        self.flag.return_value = False

        assert self._get(endpoint, insight_id=self.insight.id).status_code == 404
