from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models import EventProperty, Team, User
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.actions.backend.models.action import Action
from products.experiments.backend import session_event_deltas
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_event_deltas import EXPERIMENT_BEHAVIOR_COMPARISON_FLAG
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest

NOW = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
EXPERIMENT_START = datetime(2026, 1, 1, tzinfo=UTC)
EXPOSED_AT = datetime(2026, 1, 9, 10, 0, 0, tzinfo=UTC)

PURCHASE_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "11111111-1111-1111-1111-111111111111",
    "name": "Purchases",
    "source": {"kind": "EventsNode", "event": "purchase"},
}
# No session in `_session` ever fires this event, so it never gets an EventProperty row linking it
# to `$session_id` — the shape of an event only ever captured from a backend SDK.
SERVER_SIDE_METRIC = {
    "kind": "ExperimentMetric",
    "metric_type": "mean",
    "uuid": "22222222-2222-2222-2222-222222222222",
    "name": "Server charges",
    "source": {"kind": "EventsNode", "event": "server charge"},
}


def rank_anything(test: Any) -> Any:
    """Drop the evidence floors for tests about which sessions, people and recordings are counted.

    Those fixtures are a handful of people by design, which the floors are built to reject —
    without this they'd assert on an empty shelf and pass whatever the counting did.
    """
    for constant, value in (
        ("CONFIDENCE_Z", 0.0),
        ("MIN_LOG_RATIO_LOWER_BOUND", 0.0),
        ("MIN_SUPPORT_PERSONS", 1),
        ("MIN_ARM_PERSONS", 1),
    ):
        test = patch.object(session_event_deltas, constant, value)(test)
    return test


@freeze_time(NOW)
class TestExperimentSessionEventDeltas(ClickhouseTestMixin, APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self._people: set[str] = set()
        flag_patch = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag == EXPERIMENT_BEHAVIOR_COMPARISON_FLAG,
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)

    def _create_experiment(
        self,
        metrics: Optional[list[dict[str, Any]]] = None,
        key: str = "checkout-cta",
        variants: Optional[list[str]] = None,
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
                    "variants": [{"key": key, "rollout_percentage": 50} for key in variants or ["control", "test"]]
                }
            },
        )
        return Experiment.objects.create(
            team=team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=created_by or self.user,
            start_date=EXPERIMENT_START,
            exposure_criteria=exposure_criteria or {},
            metrics=metrics or [],
        )

    def _session(
        self,
        *,
        variants: Optional[list[str]] = None,
        events: Optional[list[str]] = None,
        at: datetime = EXPOSED_AT,
        flag_key: str = "checkout-cta",
        distinct_id: Optional[str] = None,
        properties: Optional[dict[str, Any]] = None,
        recorded: bool = True,
    ) -> str:
        """One session: an exposure event per entry in `variants`, then `events`.

        A distinct_id of its own unless one is passed, because the comparison counts people —
        reusing one across sessions is what the returning-person case is about, not the default.

        Recorded by default, since a card can only carry sessions replay kept; `recorded=False`
        is the sampled-out session that must never back a card.
        """
        distinct_id = distinct_id or f"person{len(self._people)}"
        if distinct_id not in self._people:
            # Without a person row every event resolves to a random person_id, which would put each
            # of a person's sessions in its own arm total.
            _create_person(team=self.team, distinct_ids=[distinct_id])
            self._people.add(distinct_id)

        session_id = str(uuid7(unix_ms_time=int(at.timestamp() * 1000)))
        shared_properties = {"$session_id": session_id, **(properties or {})}
        exposure_variants = variants if variants is not None else ["test"]
        for index, variant in enumerate(exposure_variants):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=distinct_id,
                timestamp=at + timedelta(seconds=index),
                properties={
                    **shared_properties,
                    "$feature_flag": flag_key,
                    "$feature_flag_response": variant,
                },
            )
        for index, event in enumerate(events or []):
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=at + timedelta(minutes=index + 1),
                properties=shared_properties,
            )
        if recorded:
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=distinct_id,
                first_timestamp=at,
                last_timestamp=at + timedelta(minutes=len(events or []) + 1),
                # The helper's convenience event would pollute the event counts the cards compare.
                ensure_analytics_event_in_session=False,
            )
        # Ingestion records every (event, property) pair in Postgres, and the endpoint reads those
        # rows to decide whether an event can back a recording at all — so events captured with a
        # $session_id here must leave the same trace they would in production, and an exposure event
        # this session never fired must leave none.
        for event_name in {*(events or []), *(["$feature_flag_called"] if exposure_variants else [])}:
            EventProperty.objects.get_or_create(
                team=self.team, project_id=self.team.project_id, event=event_name, property="$session_id"
            )
        return session_id

    def _arm(self, variant: str, sessions: list[list[str]]) -> None:
        """One person per session — the shape of an arm where nobody comes back."""
        for events in sessions:
            self._session(variants=[variant], events=events)

    def _post_deltas(self, experiment: Experiment, **body: Any) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}/session_event_deltas/",
            body,
            format="json",
        )

    def _cards(self, data: dict[str, Any], kind: Optional[str] = None) -> list[dict[str, Any]]:
        return [card for card in data["cards"] if kind is None or card["kind"] == kind]

    @patch.object(session_event_deltas, "MIN_ARM_PERSONS", 20)
    def test_cards_rank_by_separation_and_leave_out_what_the_arms_share(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        # The test variant sees pricing_faq far more and reaches checkout far less. `noise` differs
        # by a couple of people, which is nothing over thirty; `rare` happened once.
        self._arm("control", [["pricing_faq"], ["pricing_faq"]] + [["checkout_start", "noise"]] * 20 + [[]] * 8)
        self._arm("test", [["pricing_faq", "noise"]] * 22 + [["checkout_start"]] * 4 + [["rare"]] + [[]] * 3)
        flush_persons_and_events()

        response = self._post_deltas(experiment)

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        behavior = self._cards(data, "behavior")
        # Ranked on how far apart the arms are, not on which way — an event the test variant does
        # much *less* has to be able to earn a card on the arm that does it more.
        assert [(card["event"], card["variant"]) for card in behavior] == [
            ("pricing_faq", "test"),
            ("checkout_start", "control"),
        ]
        # A band, never a number: the experiment's own results state magnitudes, and a second one
        # computed from a different window and unit would read as a contradiction.
        assert behavior[0]["strength"] == "more"
        assert {"ratio", "baseline_rate", "target_rate"}.isdisjoint(behavior[0])
        # Every card is backed by actual recordings, most recent first.
        assert all(card["recording_count"] == len(card["session_ids"]) > 0 for card in behavior)
        # An event the arms share and one person's one-off get no card at all.
        assert {"noise", "rare"}.isdisjoint({card["event"] for card in behavior})
        assert data["too_early"] is False
        assert [(arm["key"], arm["persons"]) for arm in data["arms"]] == [("control", 30), ("test", 30)]

    @rank_anything
    def test_cards_carry_only_sessions_that_were_actually_recorded(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        recorded = self._session(variants=["test"], events=["pricing_faq"])
        self._session(variants=["test"], events=["pricing_faq"], recorded=False)
        self._session(variants=["control"], events=["checkout_start"], recorded=False)
        self._session(variants=["control"], events=[])
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        cards = {card["event"]: card for card in self._cards(data)}
        # Two test people did pricing_faq, but only one session was recorded — the card promises
        # exactly what the playlist can show.
        assert cards["pricing_faq"]["session_ids"] == [recorded]
        assert cards["pricing_faq"]["recording_count"] == 1
        # checkout_start only ever happened in an unrecorded session: no card, not an empty card.
        assert "checkout_start" not in cards

    @rank_anything
    def test_a_person_is_counted_once_and_read_from_their_first_exposed_session(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._session(variants=["control"], events=["pricing_faq"], distinct_id="comes_back", at=EXPOSED_AT)
        for index in range(3):
            self._session(
                variants=["control"],
                events=["checkout_start"],
                distinct_id="comes_back",
                at=EXPOSED_AT + timedelta(hours=index + 1),
            )
        self._session(variants=["test"], events=["checkout_start"], distinct_id="visits_once")
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # The comparison reads each person from their first covered session only — reading all four
        # would give this arm four times the chance to have done something. So checkout_start is a
        # difference on the *test* side, even though control's later sessions are full of it.
        checkout = next(card for card in self._cards(data, "behavior") if card["event"] == "checkout_start")
        assert checkout["variant"] == "test"
        # People counted once; the sessions total still says how much material sits behind the arm.
        assert [(arm["persons"], arm["sessions"]) for arm in data["arms"]] == [(1, 4), (1, 1)]

    @parameterized.expand(
        [
            # (name, multiple_variant_handling, expected people per arm, expected excluded)
            ("exclude", "exclude", [1, 1], 1),
            # First-seen puts the person in the arm they saw first, so nobody is set aside.
            ("first_seen", "first_seen", [1, 2], 0),
        ]
    )
    @rank_anything
    def test_a_person_who_saw_both_variants_is_split_the_way_the_analysis_splits_them(
        self, _name: str, handling: str, expected_arms: list[int], expected_multiple: int
    ) -> None:
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC], exposure_criteria={"multiple_variant_handling": handling}
        )
        self._session(variants=["control"], events=["pricing_faq"])
        self._session(variants=["test"], events=["pricing_faq"])
        self._session(variants=["test", "control"], events=["pricing_faq"])
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        assert [arm["persons"] for arm in data["arms"]] == expected_arms
        assert data["multiple_variant_persons"] == expected_multiple
        assert data["multiple_variant_handling"] == handling

    @rank_anything
    def test_one_vs_rest_puts_the_card_on_the_arm_that_stands_out(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC], variants=["control", "test", "other"])
        self._arm("control", [["dashboard_viewed"]] * 2)
        self._arm("test", [["dashboard_viewed"]] * 2)
        self._arm("other", [["dashboard_viewed", "tree_opened"]] * 2)
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        cards = self._cards(data, "behavior")
        # tree_opened is distinctive to `other` against the rest pooled; dashboard_viewed is
        # everywhere, so it is nobody's finding.
        assert [(card["event"], card["variant"]) for card in cards] == [("tree_opened", "other")]

    @rank_anything
    def test_metric_events_get_shortcut_cards_and_never_comparisons(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC, SERVER_SIDE_METRIC])
        self._arm("control", [["purchase", "pricing_faq"]] * 2)
        self._arm("test", [["pricing_faq"], []])
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # `purchase` is this experiment's primary metric: the results tab states what happened to
        # it, so here it only links to recordings of it happening, with no band and no claim.
        assert all(card["event"] != "purchase" for card in self._cards(data, "behavior"))
        metric_cards = self._cards(data, "metric")
        assert [(card["event"], card["variant"], card["strength"]) for card in metric_cards] == [
            ("purchase", "control", None)
        ]
        assert metric_cards[0]["metric_name"] == "Purchases"
        # The server-side metric can never back a recording, so it gets no card rather than an
        # empty one; it is still named for the caption.
        assert data["metric_events"] == ["purchase", "server charge"]

    @rank_anything
    def test_metric_cards_respect_the_metrics_property_filters(self) -> None:
        experiment = self._create_experiment(
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "33333333-3333-3333-3333-333333333333",
                    "name": "Enterprise purchases",
                    "source": {
                        "kind": "EventsNode",
                        "event": "purchase",
                        "properties": [{"key": "plan", "value": "enterprise", "operator": "exact", "type": "event"}],
                    },
                }
            ]
        )
        self._session(variants=["control"], events=[])
        matching = self._session(variants=["test"], events=["purchase"], properties={"plan": "enterprise"})
        self._session(variants=["test"], events=["purchase"], properties={"plan": "free"})
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # The card carries the metric's name, so a purchase outside the metric's filter on it would
        # be a mislabeled recording, not a shortcut to the metric happening.
        metric_cards = self._cards(data, "metric")
        assert [(card["event"], card["variant"]) for card in metric_cards] == [("purchase", "test")]
        assert metric_cards[0]["session_ids"] == [matching]
        assert metric_cards[0]["recording_count"] == 1

    @rank_anything
    def test_friction_events_land_on_their_own_shelf(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._arm("control", [["pricing_faq"]] * 2)
        self._arm("test", [["$exception"], ["$exception", "pricing_faq"]])
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        friction = self._cards(data, "friction")
        assert [(card["event"], card["variant"]) for card in friction] == [("$exception", "test")]

    def test_too_early_is_reported_rather_than_an_empty_shelf(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._session(variants=["control"], events=["pricing_faq"])
        self._session(variants=["test"], events=["checkout_start"])
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # Two people against a floor of fifty: an empty shelf here would read as "the variants
        # behaved identically", which two people cannot establish.
        assert data["too_early"] is True
        assert data["cards"] == []
        assert data["min_arm_persons"] == session_event_deltas.MIN_ARM_PERSONS

    @rank_anything
    @patch.object(session_event_deltas, "MAX_DELTA_SCAN_SESSIONS", 1)
    def test_reports_the_window_it_could_cover_rather_than_the_one_it_was_asked_for(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._session(variants=["control"], events=["pricing_faq"], at=EXPERIMENT_START + timedelta(hours=1))
        self._session(variants=["test"], events=["pricing_faq"], at=EXPOSED_AT)
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # Only the most recent session fits, so the experiment's own start date would claim eight
        # days of coverage that was never read — and the scan itself would read them for nothing.
        # What's left is that session's own day, plus the longest a session it began in could run.
        assert data["sessions_truncated"] is True
        assert datetime.fromisoformat(data["date_from"]) == EXPOSED_AT - timedelta(
            hours=session_event_deltas.MAX_SESSION_DURATION_HOURS
        )

    @rank_anything
    def test_default_exposure_falls_back_to_the_stamped_flag_property(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        # No exposure event carries a $session_id here, the shape of an experiment whose flag is
        # only ever evaluated server-side. The property posthog-js stamps on every client event has
        # to stand in, or the whole shelf compares nothing.
        recorded = self._session(variants=[], events=["pricing_faq"], properties={"$feature/checkout-cta": "test"})
        self._session(variants=[], events=["pricing_faq"], properties={"$feature/checkout-cta": "test"})
        self._session(variants=[], events=["checkout_start"], properties={"$feature/checkout-cta": "control"})
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        assert data["used_exposure_fallback"] is True
        assert [(arm["key"], arm["persons"]) for arm in data["arms"]] == [("control", 1), ("test", 2)]
        pricing_faq = next(card for card in self._cards(data, "behavior") if card["event"] == "pricing_faq")
        assert pricing_faq["variant"] == "test"
        assert recorded in pricing_faq["session_ids"]

    @rank_anything
    def test_fallback_comparison_is_clamped_to_its_own_tighter_window(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        # The stamped flag property rides on every client event, so on the fallback path there is
        # no event name for the scan to prune on and the window is the only thing bounding it. A
        # session inside the experiment's window but past the fallback clamp must fall out of the
        # comparison rather than be read.
        self._session(variants=[], events=["pricing_faq"], properties={"$feature/checkout-cta": "test"})
        self._session(variants=[], events=["checkout_start"], properties={"$feature/checkout-cta": "control"})
        self._session(
            variants=[],
            events=["old_event"],
            properties={"$feature/checkout-cta": "control"},
            at=NOW - timedelta(days=4),
        )
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        assert data["used_exposure_fallback"] is True
        assert datetime.fromisoformat(data["date_from"]) == NOW - timedelta(
            days=session_event_deltas.MAX_FALLBACK_DELTA_SCAN_DAYS
        )
        assert [(arm["key"], arm["persons"]) for arm in data["arms"]] == [("control", 1), ("test", 1)]
        assert all(card["event"] != "old_event" for card in data["cards"])

    @parameterized.expand([("exclude", "exclude"), ("first_seen", "first_seen")])
    @rank_anything
    def test_sharing_a_session_with_someone_elses_exposure_does_not_reattribute_a_person(
        self, _name: str, handling: str
    ) -> None:
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC], exposure_criteria={"multiple_variant_handling": handling}
        )
        # Server-side events can reuse a client session's $session_id under their own person, so a
        # covered session can hold a second person who was never exposed in it. That person's
        # (person, session) group carries no exposure rows at all, and the attribution must not
        # read it as "saw another variant" (exclude) or as "their earliest exposure" (first seen).
        shared = self._session(
            variants=["control"],
            events=["checkout_start"],
            distinct_id="owns_shared_session",
            at=EXPOSED_AT - timedelta(hours=1),
        )
        self._session(variants=["test"], events=["pricing_faq"], distinct_id="strays_into_it", at=EXPOSED_AT)
        _create_event(
            team=self.team,
            event="backend_ping",
            distinct_id="strays_into_it",
            timestamp=EXPOSED_AT - timedelta(minutes=30),
            properties={"$session_id": shared},
        )
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        assert [(arm["key"], arm["persons"]) for arm in data["arms"]] == [("control", 1), ("test", 1)]
        assert data["multiple_variant_persons"] == 0
        # The shared session started before their own, so an unconditioned "first covered session"
        # would read the strayer's behavior as backend_ping and lose pricing_faq — behavior comes
        # from the first session they were exposed in, and only exposed sessions count.
        assert sorted((card["event"], card["variant"]) for card in self._cards(data, "behavior")) == [
            ("checkout_start", "control"),
            ("pricing_faq", "test"),
        ]
        assert [(arm["key"], arm["sessions"]) for arm in data["arms"]] == [("control", 1), ("test", 1)]

    # The fixture produces exactly five (event x arm) rows: two totals, 'faq' in both arms, and
    # 'rare_event' in one. The cap can't tell "exactly at the ceiling" from "cut short" unless the
    # query fetches one row past it, so both sides of the boundary are pinned. Past the cap,
    # 'rare_event' sorts last and must vanish whole — a card built on a partial read would claim
    # one arm never did it — while the totals sort first, so the arms' counts survive any cut.
    @parameterized.expand(
        [
            ("exactly_at_cap", 5, False, [("rare_event", "test")]),
            ("past_cap", 4, True, []),
        ]
    )
    @rank_anything
    def test_event_row_cap_drops_whole_events_only_past_the_cap(
        self, _name: str, cap: int, truncated: bool, expected_cards: list[tuple[str, str]]
    ) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        self._session(variants=["control"], events=["faq"])
        self._session(variants=["test"], events=["faq", "rare_event"])
        flush_persons_and_events()

        with patch.object(session_event_deltas, "MAX_DELTA_EVENT_ROWS", cap):
            data = self._post_deltas(experiment).json()

        assert data["events_truncated"] is truncated
        assert [(card["event"], card["variant"]) for card in self._cards(data, "behavior")] == expected_cards
        assert [(arm["key"], arm["persons"]) for arm in data["arms"]] == [("control", 1), ("test", 1)]

    @rank_anything
    def test_an_action_based_exposure_still_backs_its_cards_with_recordings(self) -> None:
        action = Action.objects.create(
            team=self.team, name="Reached checkout", steps_json=[{"event": "checkout_viewed"}]
        )
        experiment = self._create_experiment(
            metrics=[PURCHASE_METRIC], exposure_criteria={"exposure_config": {"kind": "ActionsNode", "id": action.id}}
        )
        exposed = {"$feature/checkout-cta": "test"}
        recorded = self._session(variants=[], events=["checkout_viewed", "pricing_faq"], properties=exposed)
        self._session(variants=[], events=["checkout_viewed", "pricing_faq"], properties=exposed)
        self._session(variants=[], events=["checkout_viewed"], properties={"$feature/checkout-cta": "control"})
        flush_persons_and_events()

        data = self._post_deltas(experiment).json()

        # An action can match several events, so it resolves to no single event name. The query
        # that backs a card with recordings still has to reach the exposure rows carrying the
        # variant: without them every session reads as variant-less, every card is dropped as
        # unbacked, and the shelf says "no variant behaves differently" on an experiment it never
        # managed to compare.
        pricing_faq = next(card for card in self._cards(data, "behavior") if card["event"] == "pricing_faq")
        assert pricing_faq["variant"] == "test"
        assert recorded in pricing_faq["session_ids"]

    def test_server_side_exposure_event_is_refused_rather_than_silently_empty(self) -> None:
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
        self._session(variants=[], events=["purchase"], properties={"$feature/checkout-cta": "test"})
        flush_persons_and_events()

        response = self._post_deltas(experiment)

        # An exposure event no session can carry compares nothing, and an empty shelf reads as
        # "the variants behaved identically" rather than "this can't be answered from recordings".
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "captured server-side" in response.json()["detail"]

    @rank_anything
    def test_recordings_the_viewer_cannot_open_are_left_off_the_cards(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])
        denied = self._session(variants=["test"], events=["pricing_faq"])
        allowed = self._session(variants=["test"], events=["pricing_faq"])
        self._session(variants=["control"], events=[])
        # Object-level controls can only target a recording that has a Postgres row.
        SessionRecording.objects.create(team=self.team, session_id=denied)
        flush_persons_and_events()

        # Only that one recording is denied: the same check guards the experiment itself, and
        # failing it there would 500 the request rather than test anything.
        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_object",
            side_effect=lambda obj, *args, **kwargs: getattr(obj, "session_id", None) != denied,
        ):
            data = self._post_deltas(experiment).json()

        # A card hands its ids straight to the playlist, so leaving a denied recording on one would
        # tell the viewer its id, the variant it was in, and an event it contains.
        card = next(card for card in self._cards(data, "behavior") if card["event"] == "pricing_faq")
        assert card["session_ids"] == [allowed]
        assert card["recording_count"] == 1

    def test_requires_session_replay_access(self) -> None:
        experiment = self._create_experiment(metrics=[PURCHASE_METRIC])

        with patch(
            "posthog.rbac.user_access_control.UserAccessControl.check_access_level_for_resource", return_value=False
        ):
            response = self._post_deltas(experiment)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
