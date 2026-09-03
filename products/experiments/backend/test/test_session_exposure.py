import dataclasses
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql import ast

from posthog.models import EventProperty

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT_CUTOFF,
    EXPERIMENT_EXPOSURE_EVENT_FLAG,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.replay_linkage import (
    IN_SESSION_EXPOSURE_ACTIVATION_REASON,
    IN_SESSION_EXPOSURE_UNMATCHABLE_REASON,
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

    def test_available_without_fallback_when_the_exposure_event_is_session_linked(self) -> None:
        experiment = self._experiment()
        EventProperty.objects.get_or_create(
            team=self.team, project_id=self.team.project_id, event=DEFAULT_EXPOSURE_EVENT, property="$session_id"
        )

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason is None
        assert semantics.session_exposure is not None
        assert semantics.uses_stamped_fallback is False

    def test_available_but_flags_the_stamped_fallback_for_a_server_side_default_event(self) -> None:
        # No EventProperty row marks the default event as ever session-linked, so evidence is the
        # stamped flag property. The scope still answers, but the copy must say the flag was active,
        # not that the exposure was captured, so the caveat has to reach the tab.
        experiment = self._experiment()

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason is None
        assert semantics.uses_stamped_fallback is True

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
        assert semantics.uses_stamped_fallback is False
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

        semantics = resolve_in_session_exposure_semantics(self.team, experiment)

        assert semantics.unavailable_reason == IN_SESSION_EXPOSURE_UNMATCHABLE_REASON
        assert semantics.session_exposure is None
