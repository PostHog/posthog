from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

import posthog.hogql.query as hogql_query_module

from posthog.clickhouse.query_tagging import Product, get_query_tags
from posthog.constants import AvailableFeature
from posthog.models import EventProperty, Team, User
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.access_control.backend.models.access_control import AccessControl
from products.actions.backend.models.action import Action
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    EXPERIMENT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT_CUTOFF,
    EXPERIMENT_EXPOSURE_EVENT_FLAG,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_buckets import MAX_BUCKET_METRICS, MAX_BUCKET_SCAN_DAYS, MAX_BUCKET_SOURCES
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest

NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
EXPERIMENT_START = datetime(2025, 12, 20, tzinfo=UTC)

PURCHASE_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "11111111-1111-1111-1111-111111111111",
    "name": "Purchases",
    "source": {"kind": "EventsNode", "event": "purchase"},
}
SIGNUP_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "22222222-2222-2222-2222-222222222222",
    "name": "Signups",
    "source": {"kind": "EventsNode", "event": "signup"},
}
CHECKOUT_FUNNEL_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "funnel",
    "uuid": "33333333-3333-3333-3333-333333333333",
    "name": "Checkout funnel",
    "series": [{"kind": "EventsNode", "event": "cart viewed"}, {"kind": "EventsNode", "event": "purchase"}],
}
REPEATED_STEP_FUNNEL_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "funnel",
    "uuid": "44444444-4444-4444-4444-444444444444",
    "name": "Second upload",
    "series": [{"kind": "EventsNode", "event": "uploaded file"}, {"kind": "EventsNode", "event": "uploaded file"}],
}
SINGLE_STEP_FUNNEL_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "funnel",
    "uuid": "99999999-9999-9999-9999-999999999999",
    "name": "Purchase funnel",
    "series": [{"kind": "EventsNode", "event": "purchase"}],
}
RETENTION_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "retention",
    "uuid": "55555555-5555-5555-5555-555555555555",
    "name": "Weekly return",
    "start_event": {"kind": "EventsNode", "event": "signed up"},
    "completion_event": {"kind": "EventsNode", "event": "$pageview"},
    "retention_window_start": 1,
    "retention_window_end": 7,
    "retention_window_unit": "day",
    "start_handling": "first_seen",
}
DATA_WAREHOUSE_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "66666666-6666-6666-6666-666666666666",
    "name": "Stripe revenue",
    "source": {
        "kind": "ExperimentDataWarehouseNode",
        "table_name": "stripe_charges",
        "timestamp_field": "created_at",
        "data_warehouse_join_key": "customer_id",
        "events_join_key": "distinct_id",
    },
}
# No session in `_session` ever fires this event, so it never gets an EventProperty row linking
# it to `$session_id` — the shape of an event only ever captured from a backend SDK.
SERVER_SIDE_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "77777777-7777-7777-7777-777777777777",
    "name": "Server charges",
    "source": {"kind": "EventsNode", "event": "server charge"},
}
DATA_WAREHOUSE_STEP = {
    "kind": "ExperimentDataWarehouseNode",
    "table_name": "stripe_charges",
    "timestamp_field": "created_at",
    "data_warehouse_join_key": "customer_id",
    "events_join_key": "distinct_id",
}


def _funnel(uuid: str, name: str, series: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "ExperimentMetric", "metric_type": "funnel", "uuid": uuid, "name": name, "series": series}


CART = {"kind": "EventsNode", "event": "cart viewed"}
PURCHASE = {"kind": "EventsNode", "event": "purchase"}
SERVER_CHARGE = {"kind": "EventsNode", "event": "server charge"}


@freeze_time(NOW)
class TestExperimentSessionBuckets(ClickhouseTestMixin, APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _create_experiment(
        self,
        metrics: Optional[list[dict[str, Any]]] = None,
        key: str = "checkout-cta",
        start_date: datetime = EXPERIMENT_START,
        exposure_criteria: Optional[dict[str, Any]] = None,
        team: Optional[Team] = None,
        created_by: Optional[User] = None,
    ) -> Experiment:
        team = team or self.team
        flag = FeatureFlag.objects.create(
            team=team,
            key=key,
            name=key,
            created_by=self.user,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
        )
        return Experiment.objects.create(
            team=team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=created_by or self.user,
            start_date=start_date,
            exposure_criteria=exposure_criteria or {},
            metrics=metrics or [],
        )

    def _session(
        self,
        *,
        variant: Optional[str] = "test",
        events: Optional[list[tuple[str, datetime]]] = None,
        at: datetime = datetime(2026, 1, 9, 10, 0, 0, tzinfo=UTC),
        with_recording: bool = True,
        flag_key: str = "checkout-cta",
        exposure_event: str = "$feature_flag_called",
        distinct_id: str = "user1",
        properties: Optional[dict[str, Any]] = None,
    ) -> str:
        """One session: a recording, an exposure event for `variant` (unless None), and events.

        `properties` is stamped on every event of the session, exposure included.
        """
        session_id = str(uuid7(unix_ms_time=int(at.timestamp() * 1000)))
        shared_properties = {"$session_id": session_id, **(properties or {})}
        if with_recording:
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=distinct_id,
                first_timestamp=at,
                last_timestamp=at + timedelta(minutes=30),
            )
        if variant is not None:
            _create_event(
                team=self.team,
                event=exposure_event,
                distinct_id=distinct_id,
                timestamp=at,
                properties={
                    **shared_properties,
                    "$feature_flag": flag_key,
                    "$feature_flag_response": variant,
                },
            )
        for event, timestamp in events or []:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=shared_properties,
            )
        # Ingestion records every (event, property) pair in Postgres, and the endpoint reads
        # those rows to decide whether an event can be matched to sessions at all — so events
        # captured with a $session_id here must leave the same trace they would in production.
        ingested = {event for event, _ in events or []}
        if variant is not None:
            ingested.add(exposure_event)
        for event_name in ingested:
            EventProperty.objects.get_or_create(
                team=self.team, project_id=self.team.project_id, event=event_name, property="$session_id"
            )
        return session_id

    def _post_bucket(self, experiment: Experiment, **body: Any) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}/session_buckets/",
            body,
            format="json",
        )

    def test_fired_any_is_an_or_across_metrics(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC, SIGNUP_METRIC])
        purchased = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        signed_up = self._session(events=[("signup", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        neither = self._session()
        flush_persons_and_events()

        response = self._post_bucket(
            experiment,
            bucket="fired_any",
            metric_uuids=[PURCHASE_METRIC["uuid"], SIGNUP_METRIC["uuid"]],
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        # The client-side path ANDs its filters, so a session firing only one of the two metrics
        # would be excluded there — this is the capability the endpoint exists for.
        assert set(data["session_ids"]) == {purchased, signed_up}
        assert neither not in data["session_ids"]
        assert data["truncated"] is False
        assert {metric["metric_uuid"] for metric in data["considered_metrics"]} == {
            PURCHASE_METRIC["uuid"],
            SIGNUP_METRIC["uuid"],
        }
        assert data["excluded_metrics"] == []
        assert data["used_exposure_fallback"] is False

    def test_no_metric_activity_returns_exposed_sessions_without_any_considered_metric(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC, SIGNUP_METRIC])
        quiet = self._session()
        self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        self._session(events=[("signup", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="no_metric_activity")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["session_ids"] == [quiet]

    def test_metric_events_without_exposure_stay_out_of_every_bucket(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        unexposed = self._session(variant=None, events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        fired = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])
        quiet = self._post_bucket(experiment, bucket="no_metric_activity")

        # Metric-only sessions don't surface anywhere in the experiment today; a bucket must not
        # be the place they start appearing.
        assert unexposed not in fired.json()["session_ids"]
        assert unexposed not in quiet.json()["session_ids"]

    @parameterized.expand(
        [
            # Firing an earlier series step still isn't completing.
            ("distinct_steps", CHECKOUT_FUNNEL_METRIC, ["cart viewed"], ["cart viewed", "purchase"]),
            # One event repeated as two steps ("the second upload"): completing means firing it as
            # many times as it appears, so a single occurrence is still a drop-off.
            ("repeated_step", REPEATED_STEP_FUNNEL_METRIC, ["uploaded file"], ["uploaded file", "uploaded file"]),
            # A single-step funnel is exposure → event; an unrelated event isn't the completion.
            ("single_step", SINGLE_STEP_FUNNEL_METRIC, ["cart viewed"], ["purchase"]),
        ]
    )
    def test_funnel_dropoff_returns_exposed_sessions_that_never_completed(
        self, _name: str, metric: dict[str, Any], partial_events: list[str], completing_events: list[str]
    ) -> None:
        experiment = self._create_experiment(metrics=[metric])
        exposed_only = self._session()
        partial = self._session(
            events=[
                (event, datetime(2026, 1, 9, 10, 5 + index, tzinfo=UTC)) for index, event in enumerate(partial_events)
            ]
        )
        completed = self._session(
            events=[
                (event, datetime(2026, 1, 9, 10, 5 + index, tzinfo=UTC))
                for index, event in enumerate(completing_events)
            ]
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="funnel_dropoff", metric_uuids=[metric["uuid"]])

        # The exposure is the funnel's first step, the same as in the experiment analysis, so
        # being exposed is entering the funnel; not completing is what puts a session here.
        assert response.status_code == status.HTTP_200_OK, response.json()
        session_ids = response.json()["session_ids"]
        assert set(session_ids) == {exposed_only, partial}
        assert completed not in session_ids

    @parameterized.expand(
        [
            # Without the check every exposed session comes back as "didn't finish", including
            # the ones whose purchase really did happen.
            (
                "server_side_completion",
                _funnel("a1111111-1111-1111-1111-111111111111", "Checkout", [CART, SERVER_CHARGE]),
                "captured server-side",
            ),
            # A data-warehouse completion is dropped from the metric's sources, so the positional
            # read would silently promote an inner step to the funnel's completion.
            (
                "data_warehouse_completion",
                _funnel("a4444444-4444-4444-4444-444444444444", "Charge last", [CART, PURCHASE, DATA_WAREHOUSE_STEP]),
                "data warehouse",
            ),
        ]
    )
    def test_funnel_dropoff_refuses_when_the_completion_step_cannot_be_matched(
        self, _name: str, metric: dict[str, Any], expected_reason: str
    ) -> None:
        experiment = self._create_experiment(metrics=[metric])
        self._session(
            events=[
                ("cart viewed", datetime(2026, 1, 9, 10, 5, tzinfo=UTC)),
                ("purchase", datetime(2026, 1, 9, 10, 7, tzinfo=UTC)),
            ]
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="funnel_dropoff", metric_uuids=[metric["uuid"]])

        # Drop-off counts the funnel's last step. When that step can't appear in a recording the
        # predicate answers a question nobody asked, and every exposed session lands in the
        # bucket with nothing on screen saying why.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert expected_reason in response.json()["detail"]

    def test_funnel_dropoff_completion_check_survives_an_action_step(self) -> None:
        action = Action.objects.create(team=self.team, name="Viewed cart", steps_json=[{"event": "cart viewed"}])
        metric = _funnel(
            "a7777777-7777-7777-7777-777777777777",
            "Checkout via action",
            [CART, {"kind": "ActionsNode", "id": action.pk}, SERVER_CHARGE],
        )
        experiment = self._create_experiment(metrics=[metric])
        self._session(events=[("cart viewed", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="funnel_dropoff", metric_uuids=[metric["uuid"]])

        # An action among the steps makes the metric's event names unresolvable as a whole, but the
        # completion step is still a concrete event. Looking names up per metric rather than per
        # source would leave the completion event out of the linkability read, and the completion
        # check would pass on a name it never asked about.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "captured server-side" in response.json()["detail"]

    @parameterized.expand(
        [
            # The funnel's entry is the exposure, so a first series step no recording can show
            # doesn't gate the question the way the completion does.
            (
                "server_side_first_step",
                _funnel("a2222222-2222-2222-2222-222222222222", "Charge then buy", [SERVER_CHARGE, PURCHASE]),
                [],
            ),
            (
                "server_side_middle_step",
                _funnel("a5555555-5555-5555-5555-555555555555", "Checkout", [CART, SERVER_CHARGE, PURCHASE]),
                ["cart viewed"],
            ),
            (
                "data_warehouse_first_step",
                _funnel("a3333333-3333-3333-3333-333333333333", "Charge first", [DATA_WAREHOUSE_STEP, CART, PURCHASE]),
                ["cart viewed"],
            ),
        ]
    )
    def test_funnel_dropoff_allows_unmatchable_steps_before_the_completion(
        self, _name: str, metric: dict[str, Any], dropped_events: list[str]
    ) -> None:
        experiment = self._create_experiment(metrics=[metric])
        dropped_off = self._session(
            events=[(event, datetime(2026, 1, 9, 10, 5, tzinfo=UTC)) for event in dropped_events]
        )
        completed = self._session(
            events=[
                *[(event, datetime(2026, 1, 9, 10, 5, tzinfo=UTC)) for event in dropped_events],
                ("purchase", datetime(2026, 1, 9, 10, 7, tzinfo=UTC)),
            ]
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="funnel_dropoff", metric_uuids=[metric["uuid"]])

        # Only the completion step is read, so steps before it that no recording can show cost
        # nothing. Refusing here would take drop-off away from funnels it answers correctly.
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["session_ids"] == [dropped_off]
        assert completed not in response.json()["session_ids"]

    @parameterized.expand(
        [
            ("retention", RETENTION_METRIC, "Retention metrics measure a return visit"),
            ("data_warehouse", DATA_WAREHOUSE_METRIC, "measured entirely in the data warehouse"),
            ("server_side", SERVER_SIDE_METRIC, "only ever been captured server-side"),
        ]
    )
    def test_unmatchable_metrics_are_reported_rather_than_returning_nothing(
        self, _name: str, metric: dict[str, Any], expected_reason: str
    ) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC, metric])
        purchased = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(
            experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"], metric["uuid"]]
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert data["session_ids"] == [purchased]
        assert [excluded["metric_uuid"] for excluded in data["excluded_metrics"]] == [metric["uuid"]]
        assert expected_reason in data["excluded_metrics"][0]["reason"]
        assert [considered["metric_uuid"] for considered in data["considered_metrics"]] == [PURCHASE_METRIC["uuid"]]

        # Asked for on its own it can only ever match zero sessions, so the endpoint refuses
        # instead of returning an empty list that reads as "no sessions did this".
        only_unmatchable = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[metric["uuid"]])
        assert only_unmatchable.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_metric_activity_never_evaluates_absence_against_a_server_side_metric(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC, SERVER_SIDE_METRIC])
        quiet = self._session()
        purchased = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="no_metric_activity")

        # A server-side metric's events never carry a session id, so counted naively it "fired
        # nothing" in every session — absence must be computed over the linkable metrics only,
        # with the server-side one reported out.
        data = response.json()
        assert data["session_ids"] == [quiet]
        assert purchased not in data["session_ids"]
        assert [excluded["metric_uuid"] for excluded in data["excluded_metrics"]] == [SERVER_SIDE_METRIC["uuid"]]

        # With no linkable metric left, every exposed session would trivially qualify — refuse
        # rather than confidently returning the whole population as "fired nothing".
        only_server_side = self._post_bucket(
            experiment, bucket="no_metric_activity", metric_uuids=[SERVER_SIDE_METRIC["uuid"]]
        )
        assert only_server_side.status_code == status.HTTP_400_BAD_REQUEST

    def test_backend_fired_exposure_falls_back_to_the_stamped_flag_property(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        # No session ever fires $feature_flag_called, so the default exposure event has no
        # EventProperty row — the shape of exposure evaluated in a backend SDK. Client events
        # still carry the stamped flag property.
        purchased = self._session(
            variant=None,
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
            properties={"$feature/checkout-cta": "test"},
        )
        quiet = self._session(
            variant=None,
            events=[("$pageview", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        fired = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])
        inactive = self._post_bucket(experiment, bucket="no_metric_activity")

        # Without the fallback the population is empty and every bucket returns nothing — on
        # exactly the experiments where the tab's list falls back and shows sessions.
        assert fired.status_code == status.HTTP_200_OK, fired.json()
        assert fired.json()["session_ids"] == [purchased]
        assert fired.json()["used_exposure_fallback"] is True
        assert inactive.json()["session_ids"] == [quiet]

    def test_server_side_custom_exposure_is_refused_rather_than_silently_empty(self) -> None:
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC],
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "server exposure",
                    "properties": [],
                }
            },
        )
        purchased = self._session(
            variant=None,
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # An exposure event no session can carry matches nothing, and an empty list reads as "no
        # session did this" instead of "this experiment can't be answered from recordings".
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "captured server-side" in response.json()["detail"]
        # The stamped flag property is on that session, so a fallback would have returned it.
        # Custom criteria carry semantics a flag-value filter can't stand in for: the population
        # must not widen to "the flag was active".
        assert purchased not in str(response.json())

    @parameterized.expand(
        [
            # (name, rollout flag enabled, experiment start offset from the cutoff, expected event)
            ("after_cutoff", True, 7, EXPERIMENT_EXPOSURE_EVENT),
            ("after_cutoff_flag_disabled", False, 7, "$feature_flag_called"),
            ("before_cutoff", True, -7, "$feature_flag_called"),
        ]
    )
    @freeze_time(EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=10))
    def test_bucket_population_reads_the_resolved_exposure_event(
        self, _name: str, flag_enabled: bool, start_offset_days: int, expected_event: str
    ) -> None:
        # setUp logged in under the class-level freeze, months before this test's frozen clock,
        # so that session has expired; log in again inside the window.
        self.client.force_login(self.user)
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC],
            start_date=EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=start_offset_days),
        )
        at = EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=8)
        purchase_at = at + timedelta(minutes=5)
        new_event_session = self._session(
            exposure_event=EXPERIMENT_EXPOSURE_EVENT, at=at, events=[("purchase", purchase_at)]
        )
        legacy_event_session = self._session(
            exposure_event="$feature_flag_called", at=at, distinct_id="user2", events=[("purchase", purchase_at)]
        )
        other_flag_session = self._session(
            exposure_event=EXPERIMENT_EXPOSURE_EVENT,
            flag_key="unrelated-flag",
            at=at,
            distinct_id="user3",
            events=[("purchase", purchase_at)],
        )
        flush_persons_and_events()

        # Only answer for the exposure-event flag; returning True for every flag would flip
        # unrelated HogQL query modifiers on and break the query under test.
        def fake_feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_enabled if flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG else False

        with patch("posthoganalytics.feature_enabled", side_effect=fake_feature_enabled):
            response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # The analysis queries resolve the default exposure event per experiment
        # (resolve_default_exposure_event), and the playlist ANDs these ids with an exposure
        # filter the frontend builds from the same resolved event. A bucket read off the other
        # event intersects two different populations once the two events stop being emitted
        # together.
        assert response.status_code == status.HTTP_200_OK, response.json()
        expected_session = new_event_session if expected_event == EXPERIMENT_EXPOSURE_EVENT else legacy_event_session
        assert response.json()["session_ids"] == [expected_session]
        # $experiment_exposure is emitted for every experiment, so matching it must still require
        # this experiment's flag key.
        assert other_flag_session not in response.json()["session_ids"]
        assert response.json()["used_exposure_fallback"] is False

    @freeze_time(EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=10))
    def test_rollout_exposure_event_captured_server_side_keeps_the_stamped_property_fallback(self) -> None:
        self.client.force_login(self.user)
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC],
            start_date=EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=7),
        )
        at = EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=8)
        purchased = self._session(
            variant=None,
            at=at,
            events=[("purchase", at + timedelta(minutes=5))],
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        def fake_feature_enabled(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG

        with patch("posthoganalytics.feature_enabled", side_effect=fake_feature_enabled):
            response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # Under the rollout $experiment_exposure is the default exposure, not a custom choice, so
        # exposure evaluated in a backend SDK must keep the stamped-property fallback rather than
        # being refused the way a custom event is.
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["session_ids"] == [purchased]
        assert response.json()["used_exposure_fallback"] is True

    @parameterized.expand([("custom_event",), ("action",)])
    def test_session_linkable_custom_exposure_defines_the_population(self, exposure_kind: str) -> None:
        if exposure_kind == "action":
            action = Action.objects.create(team=self.team, name="Checkout", steps_json=[{"event": "checkout started"}])
            exposure_config: dict[str, Any] = {"kind": "ActionsNode", "id": action.pk}
        else:
            exposure_config = {
                "kind": "ExperimentEventExposureConfig",
                "event": "checkout started",
                "properties": [],
            }
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC], exposure_criteria={"exposure_config": exposure_config}
        )
        exposed = self._session(
            variant=None,
            events=[
                ("checkout started", datetime(2026, 1, 9, 10, 4, tzinfo=UTC)),
                ("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC)),
            ],
            properties={"$feature/checkout-cta": "test"},
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # The refusal above must stay narrow. A custom event that sessions do carry is the normal
        # case, and an action has no single event name to look up at all, so it fails open.
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["session_ids"] == [exposed]
        assert response.json()["used_exposure_fallback"] is False

    def test_action_metrics_are_not_excluded_by_the_linkability_check(self) -> None:
        action = Action.objects.create(team=self.team, name="Purchased", steps_json=[{"event": "purchase"}])
        action_metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": "88888888-8888-8888-8888-888888888888",
            "name": "Purchased (action)",
            "source": {"kind": "ActionsNode", "id": action.pk},
        }
        experiment = self._create_experiment(metrics=[action_metric])
        purchased = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[action_metric["uuid"]])

        # An action has no single event name to look up, so linkability can't be decided for it —
        # it must fail open into the considered set, not read as "never seen with a session".
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["session_ids"] == [purchased]
        assert [metric["metric_uuid"] for metric in data["considered_metrics"]] == [action_metric["uuid"]]
        assert data["excluded_metrics"] == []

    def test_variant_facet_includes_multi_variant_sessions_under_each_arm(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        test_only = self._session(variant="test", events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        control_only = self._session(variant="control", events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        both = self._session(variant="test", events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="user1",
            timestamp=datetime(2026, 1, 9, 10, 6, tzinfo=UTC),
            properties={
                "$session_id": both,
                "$feature_flag": "checkout-cta",
                "$feature_flag_response": "control",
            },
        )
        flush_persons_and_events()

        by_variant = {
            variant: set(
                self._post_bucket(
                    experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]], variant=variant
                ).json()["session_ids"]
            )
            for variant in ("test", "control")
        }

        # A session that saw both arms is the multi-exposure bias signal, not an error — it stays
        # visible under each variant it saw rather than being dropped from both.
        assert by_variant["test"] == {test_only, both}
        assert by_variant["control"] == {control_only, both}

    def test_sessions_without_a_recording_are_left_out(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        recorded = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        unrecorded = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))], with_recording=False)
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # The cap is small, so ids the playlist can never render must not consume it.
        assert response.json()["session_ids"] == [recorded]
        assert unrecorded not in response.json()["session_ids"]

    def test_returns_most_recent_first_and_flags_truncation(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        older = self._session(
            at=datetime(2026, 1, 7, 10, 0, tzinfo=UTC),
            events=[("purchase", datetime(2026, 1, 7, 10, 5, tzinfo=UTC))],
        )
        newer = self._session(
            at=datetime(2026, 1, 9, 10, 0, tzinfo=UTC),
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]], limit=1)

        data = response.json()
        assert data["session_ids"] == [newer]
        assert older not in data["session_ids"]
        assert data["truncated"] is True

    def test_scan_window_is_clamped_to_the_recent_run_window(self) -> None:
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC], start_date=NOW - timedelta(days=MAX_BUCKET_SCAN_DAYS + 30)
        )
        too_old = self._session(
            at=NOW - timedelta(days=MAX_BUCKET_SCAN_DAYS + 5),
            events=[("purchase", NOW - timedelta(days=MAX_BUCKET_SCAN_DAYS + 5) + timedelta(minutes=5))],
        )
        recent = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        data = response.json()
        assert data["session_ids"] == [recent]
        assert too_old not in data["session_ids"]
        # The response says what it scanned, so the surface can state the omission rather than
        # implying the bucket is empty beyond the clamp.
        assert data["date_from"] == (NOW - timedelta(days=MAX_BUCKET_SCAN_DAYS)).isoformat().replace("+00:00", "Z")

    def test_test_account_filtering_follows_the_exposure_criteria(self) -> None:
        self.team.test_account_filters = [{"key": "$host", "value": "localhost", "operator": "is_not", "type": "event"}]
        self.team.save()
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC], exposure_criteria={"filterTestAccounts": True})
        internal = self._session(
            distinct_id="internal",
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
            properties={"$host": "localhost"},
        )
        real = self._session(
            distinct_id="customer",
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
            properties={"$host": "app.example.com"},
        )
        flush_persons_and_events()

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        data = response.json()
        assert data["filter_test_accounts"] is True
        assert real in data["session_ids"]
        assert internal not in data["session_ids"]

    def test_not_launched_experiment_is_rejected(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        experiment.start_date = None
        experiment.save()

        response = self._post_bucket(experiment, bucket="no_metric_activity")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_tags_its_clickhouse_queries_as_experiments(self) -> None:
        # Untagged queries lose their cost attribution in production, and the first scan runs
        # before anything else in the request has tagged — so this can't ride on another
        # product's tags the way the session-context endpoint does. Local dev raises on an
        # untagged query, but TEST mode doesn't, so the tag needs asserting here.
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        flush_persons_and_events()

        # Captured at the ClickHouse boundary rather than read afterwards: the replay
        # recording-existence lookup tags itself last, and tags don't outlive the request.
        tagged_products = []
        original = hogql_query_module.sync_execute

        def _capturing_sync_execute(*args: Any, **kwargs: Any) -> Any:
            tagged_products.append(get_query_tags().product)
            return original(*args, **kwargs)

        with patch.object(hogql_query_module, "sync_execute", side_effect=_capturing_sync_execute):
            assert self._post_bucket(experiment, bucket="fired_any").status_code == status.HTTP_200_OK

        # The scan is ours; the recording-existence lookup that follows is replay's own helper
        # and tags itself. Neither may run untagged.
        assert tagged_products[0] == Product.EXPERIMENTS
        assert None not in tagged_products

    def test_recordings_blocked_by_object_level_access_are_left_out(self) -> None:
        features = self.organization.available_product_features or []
        features.append({"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL})
        self.organization.available_product_features = features
        self.organization.save()
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        blocked_session = self._session(events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))])
        visible_session = self._session(
            distinct_id="user2", events=[("purchase", datetime(2026, 1, 9, 10, 6, tzinfo=UTC))]
        )
        flush_persons_and_events()
        blocked = SessionRecording.objects.create(team=self.team, session_id=blocked_session)
        AccessControl.objects.create(
            team=self.team, resource="session_recording", resource_id=str(blocked.id), access_level="none"
        )

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]])

        # Replay-product access is not access to every recording in it. Returning the id of a
        # recording the viewer is denied would leak which sessions the experiment touched.
        data = response.json()
        assert visible_session in data["session_ids"]
        assert blocked_session not in data["session_ids"]

    def test_denied_recordings_neither_consume_a_slot_nor_show_up_in_truncation(self) -> None:
        features = self.organization.available_product_features or []
        features.append({"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL})
        self.organization.available_product_features = features
        self.organization.save()
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        older_visible = self._session(
            at=datetime(2026, 1, 9, 9, 0, tzinfo=UTC), events=[("purchase", datetime(2026, 1, 9, 9, 5, tzinfo=UTC))]
        )
        newer_blocked = self._session(
            at=datetime(2026, 1, 9, 10, 0, tzinfo=UTC),
            distinct_id="user2",
            events=[("purchase", datetime(2026, 1, 9, 10, 5, tzinfo=UTC))],
        )
        flush_persons_and_events()
        blocked = SessionRecording.objects.create(team=self.team, session_id=newer_blocked)
        AccessControl.objects.create(
            team=self.team, resource="session_recording", resource_id=str(blocked.id), access_level="none"
        )

        response = self._post_bucket(experiment, bucket="fired_any", metric_uuids=[PURCHASE_METRIC["uuid"]], limit=1)

        # The denied recording is the most recent match, so cutting to the limit before the access
        # filter would spend the only slot on it and hand back nothing. And `truncated` would then
        # be the one bit that says a recording the viewer can't see matched this bucket.
        data = response.json()
        assert data["session_ids"] == [older_visible]
        assert newer_blocked not in data["session_ids"]
        assert data["truncated"] is False

    @parameterized.expand(
        [
            (
                "metric_count",
                [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": f"{index:08d}-0000-0000-0000-000000000000",
                        "name": f"Metric {index}",
                        "source": PURCHASE,
                    }
                    for index in range(MAX_BUCKET_METRICS + 1)
                ],
                f"more than the {MAX_BUCKET_METRICS}",
            ),
            (
                "source_count",
                [
                    _funnel(
                        "a6666666-6666-6666-6666-666666666666",
                        "Very long funnel",
                        [PURCHASE for _ in range(MAX_BUCKET_SOURCES + 1)],
                    )
                ],
                f"more than the {MAX_BUCKET_SOURCES}",
            ),
        ]
    )
    def test_refuses_a_metric_set_too_wide_to_scan(
        self, _name: str, metrics: list[dict[str, Any]], expected_reason: str
    ) -> None:
        experiment = self._create_experiment(metrics=metrics)
        # The metrics have to be matchable, or the linkability check refuses them first.
        EventProperty.objects.get_or_create(
            team=self.team, project_id=self.team.project_id, event="purchase", property="$session_id"
        )

        response = self._post_bucket(experiment, bucket="fired_any")

        # Metric and funnel-step counts are user-configurable with no server-side cap, so without
        # a ceiling one request can compile an arbitrarily wide query over the whole 30-day window.
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert expected_reason in response.json()["detail"]

    def test_team_isolation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC], key="other-team-flag", team=other_team)

        response = self._post_bucket(experiment, bucket="no_metric_activity")

        assert response.status_code == status.HTTP_404_NOT_FOUND
