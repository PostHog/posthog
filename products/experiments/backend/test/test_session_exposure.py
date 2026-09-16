import dataclasses
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast

from posthog.models import EventProperty

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT_CUTOFF,
    EXPERIMENT_EXPOSURE_EVENT_FLAG,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_linkage import (
    IN_SESSION_EXPOSURE_ACTIVATION_REASON,
    IN_SESSION_EXPOSURE_NO_EVENT_IN_SESSION_REASON,
    IN_SESSION_EXPOSURE_NOT_OBSERVED_YET_REASON,
    IN_SESSION_EXPOSURE_UNMATCHABLE_REASON,
    exposed_distinct_ids_select,
    exposed_persons_select,
    resolve_exposure_linkage,
    resolve_in_session_exposure_semantics,
)
from products.experiments.backend.session_exposure import resolve_session_exposure
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _string_constants(node: object) -> set[str]:
    # Every string literal in a HogQL expression tree, so a test can assert which key a condition
    # matches on without depending on the tree's shape.
    found: set[str] = set()

    def walk(current: object) -> None:
        if isinstance(current, ast.Constant):
            if isinstance(current.value, str):
                found.add(current.value)
            return
        if dataclasses.is_dataclass(current) and not isinstance(current, type):
            for field in dataclasses.fields(current):
                walk(getattr(current, field.name))
        elif isinstance(current, list | tuple):
            for item in current:
                walk(item)

    walk(node)
    return found


class TestSessionExposureTombstonedFlag(BaseTest):
    ORIGINAL_KEY = "checkout-cta"

    def _tombstoned_experiment(self) -> Experiment:
        # A flag cleaned up after its experiment stopped: soft-deleted, and its key renamed to free
        # the original. The experiment keeps serving its recordings tab, and historical exposure
        # events still carry the original key.
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=self.ORIGINAL_KEY,
            name=self.ORIGINAL_KEY,
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
        experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=self.user,
            # Before EXPERIMENT_EXPOSURE_EVENT_CUTOFF, so the default resolves to $feature_flag_called.
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            exposure_criteria={},
        )
        flag.deleted = True
        flag.key = flag.tombstoned_key()
        flag.save()
        return experiment

    def test_condition_matches_on_the_original_key_not_the_tombstone(self) -> None:
        experiment = self._tombstoned_experiment()
        # The default exposure event is session-linked here, so the condition filters on
        # $feature_flag rather than the stamped fallback.
        EventProperty.objects.get_or_create(
            team=self.team, project_id=self.team.project_id, event=DEFAULT_EXPOSURE_EVENT, property="$session_id"
        )

        exposure = resolve_session_exposure(self.team, experiment, event_names=frozenset())
        assert exposure.used_fallback is False

        constants = _string_constants(exposure.condition(["control", "test"]))
        assert self.ORIGINAL_KEY in constants
        assert not any(":deleted:" in value for value in constants)

    def test_stamped_fallback_uses_the_original_key_not_the_tombstone(self) -> None:
        experiment = self._tombstoned_experiment()
        # No $session_id trace for the default event, so it falls back to the stamped
        # $feature/<key> property, which must name the original key, not the renamed one.
        exposure = resolve_session_exposure(self.team, experiment, event_names=frozenset())

        assert exposure.used_fallback is True
        assert exposure.variant_property == f"$feature/{self.ORIGINAL_KEY}"
        assert ":deleted:" not in exposure.variant_property


# The seam the recordings query's in_session refusal and the tab's scope control both read, so
# they can't drift on whether the scope is available or on the fallback caveat.
class TestResolveInSessionExposureSemantics(BaseTest):
    def _experiment(self, exposure_criteria: dict | None = None, start_date: datetime | None = None) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-cta",
            name="checkout-cta",
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
            team=self.team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=self.user,
            # The default is before EXPERIMENT_EXPOSURE_EVENT_CUTOFF, so the exposure event
            # resolves to $feature_flag_called.
            start_date=start_date or datetime(2026, 1, 1, tzinfo=UTC),
            exposure_criteria=exposure_criteria or {},
        )

    def _observe_event(self, event: str, *, session_linked: bool) -> None:
        # Taxonomy writes one row per (event, property) pair, so the `$browser` row is what marks an
        # event as observed at all. Without it the event reads as one nothing is known about yet,
        # which is a different verdict from one captured only server-side.
        EventProperty.objects.get_or_create(
            team=self.team, project_id=self.team.project_id, event=event, property="$browser"
        )
        if session_linked:
            EventProperty.objects.get_or_create(
                team=self.team, project_id=self.team.project_id, event=event, property="$session_id"
            )

    def test_available_when_the_exposure_event_is_session_linked(self) -> None:
        experiment = self._experiment()
        self._observe_event(DEFAULT_EXPOSURE_EVENT, session_linked=True)

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason is None
        assert semantics.session_exposure is not None
        assert semantics.session_exposure.is_seekable_evidence is True

    def test_unavailable_for_a_server_side_default_event(self) -> None:
        # The default event is observed but never with a session id, so the only evidence left is the
        # stamped flag property. That says the flag was active in the session, not that the person was
        # enrolled there, so this surface refuses it rather than listing sessions it can't seek in.
        experiment = self._experiment()
        self._observe_event(DEFAULT_EXPOSURE_EVENT, session_linked=False)

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason == IN_SESSION_EXPOSURE_NO_EVENT_IN_SESSION_REASON
        assert semantics.session_exposure is None

    @parameterized.expand([("session_linked", True, False), ("server_side_default_event", False, True)])
    def test_used_fallback_still_reports_the_stand_in_the_session_buckets_read(
        self, _name: str, session_linked: bool, expected_used_fallback: bool
    ) -> None:
        # The recordings list refuses the stand-in at the verdict, not at the seam. Dropping it from
        # the seam instead would silently change which sessions the buckets aggregate over.
        experiment = self._experiment()
        self._observe_event(DEFAULT_EXPOSURE_EVENT, session_linked=session_linked)

        exposure = resolve_session_exposure(self.team, experiment, event_names=frozenset())

        assert exposure.used_fallback is expected_used_fallback
        assert exposure.is_seekable_evidence is not expected_used_fallback

    @parameterized.expand(
        [
            ("default_exposure_event", None),
            (
                "custom_exposure_event",
                {
                    "exposure_config": {
                        "kind": "ExperimentEventExposureConfig",
                        "event": "backend_exposure",
                        "properties": [],
                    }
                },
            ),
        ]
    )
    def test_unavailable_as_not_observed_yet_for_an_exposure_event_with_no_taxonomy_rows(
        self, _name: str, exposure_criteria: dict | None
    ) -> None:
        # No taxonomy rows at all, so nothing is known about the event yet. The custom case also
        # pins the branch ordering: without it a day-0 experiment reads as permanently server-side.
        experiment = self._experiment(exposure_criteria)

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason == IN_SESSION_EXPOSURE_NOT_OBSERVED_YET_REASON
        assert semantics.session_exposure is None
        assert semantics.available is False

    def test_the_session_linked_path_reads_taxonomy_once(self) -> None:
        # The unseen-event read must stay on the rare branch, so the common path keeps its one query.
        experiment = self._experiment()
        self._observe_event(DEFAULT_EXPOSURE_EVENT, session_linked=True)

        with self.assertNumQueries(1):
            resolve_in_session_exposure_semantics(self.team, experiment)

    def test_condition_matches_the_rollout_default_event_at_the_cutoff(self) -> None:
        # The in-session narrowing reads the exposure event off this seam. If the seam kept the
        # legacy default, exposures arriving as $experiment_exposure would leave every rollout
        # experiment's in-session list empty.
        experiment = self._experiment(start_date=EXPERIMENT_EXPOSURE_EVENT_CUTOFF)
        EventProperty.objects.get_or_create(
            team=self.team, project_id=self.team.project_id, event=EXPERIMENT_EXPOSURE_EVENT, property="$session_id"
        )

        # Only answer for the rollout flag; a blanket True would flip unrelated rollouts on too.
        def rollout_only(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key == EXPERIMENT_EXPOSURE_EVENT_FLAG

        with patch("posthoganalytics.feature_enabled", side_effect=rollout_only):
            semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.session_exposure is not None
        assert semantics.session_exposure.is_seekable_evidence is True
        assert EXPERIMENT_EXPOSURE_EVENT in _string_constants(semantics.session_exposure.condition(["control"]))

    def test_unavailable_for_activation_criteria(self) -> None:
        experiment = self._experiment(
            exposure_criteria={
                "activation_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "task_completed",
                    "properties": [],
                }
            }
        )

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason == IN_SESSION_EXPOSURE_ACTIVATION_REASON
        assert semantics.session_exposure is None

    def test_unavailable_for_a_never_session_linked_custom_event(self) -> None:
        experiment = self._experiment(
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "backend_exposure",
                    "properties": [],
                }
            }
        )
        self._observe_event("backend_exposure", session_linked=False)

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason == IN_SESSION_EXPOSURE_UNMATCHABLE_REASON
        assert semantics.session_exposure is None


def _variant_filter(query: ast.SelectQuery) -> list[str]:
    # The population's WHERE is exactly `exposures.variant IN {variants}`; the constant carries
    # the accepted variant keys.
    assert isinstance(query.where, ast.CompareOperation)
    assert isinstance(query.where.right, ast.Constant)
    return list(query.where.right.value)


def _select_aliases(query: ast.SelectQuery) -> list[str]:
    return [column.alias for column in query.select if isinstance(column, ast.Alias)]


# The watch shelf groups this population by person and buckets each person by its variant column,
# so the projection and the multiple-variant opt-in are the seam it depends on; the recordings
# list depends on the two-column shape staying unchanged.
class TestExposedPopulationSelects(BaseTest):
    def _experiment(self) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-cta",
            name="checkout-cta",
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
            team=self.team,
            name="Checkout CTA copy",
            feature_flag=flag,
            created_by=self.user,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            exposure_criteria={},
        )

    def test_exposed_persons_select_projects_attribution_and_the_distinct_ids_select_does_not(self) -> None:
        experiment = self._experiment()
        linkage = resolve_exposure_linkage(self.team, experiment_id=experiment.pk, variant=None)

        persons = exposed_persons_select(linkage, include_multiple_variant=True)
        assert _select_aliases(persons) == ["distinct_id", "person_id", "variant", "first_exposure_time"]
        assert _variant_filter(persons) == ["control", "test", MULTIPLE_VARIANT_KEY]

        distinct_ids = exposed_distinct_ids_select(linkage)
        assert _select_aliases(distinct_ids) == ["distinct_id", "first_exposure_time"]
        assert _variant_filter(distinct_ids) == ["control", "test"]
