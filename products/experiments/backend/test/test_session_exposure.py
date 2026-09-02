import dataclasses
from datetime import UTC, datetime

from posthog.test.base import BaseTest

from posthog.hogql import ast

from posthog.models import EventProperty

from products.experiments.backend.hogql_queries.exposure_query_logic import DEFAULT_EXPOSURE_EVENT
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_exposure import resolve_session_exposure
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _string_constants(node: object) -> set[str]:
    """Every string literal in a HogQL expression tree, so a test can assert which key a condition
    matches on without depending on the tree's shape."""
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
        # $feature/<key> property — which must name the original key, not the renamed one.
        exposure = resolve_session_exposure(self.team, experiment, event_names=frozenset())

        assert exposure.used_fallback is True
        assert exposure.variant_property == f"$feature/{self.ORIGINAL_KEY}"
        assert ":deleted:" not in exposure.variant_property
