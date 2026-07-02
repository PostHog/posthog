from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team

from products.annotations.backend.models import Annotation
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.pulse.backend.generation.explain import (
    MAX_CANDIDATES_PER_KIND,
    CausalCandidate,
    collect_causal_candidates,
)


class TestCollectCausalCandidates(BaseTest):
    def _flag(self, key: str = "my-flag", changed_days_ago: float | None = None, **kwargs: Any) -> FeatureFlag:
        flag = FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, **kwargs)
        if changed_days_ago is not None:
            # updated_at is auto_now — a queryset update is the only way to backdate it.
            changed_at = timezone.now() - timedelta(days=changed_days_ago)
            FeatureFlag.objects.filter(id=flag.id).update(updated_at=changed_at, created_at=changed_at)
        return flag

    def _experiment(self, name: str = "Exp", **kwargs: Any) -> Experiment:
        flag = self._flag(key=f"flag-{name}", changed_days_ago=30)  # keep the linked flag out of period
        return Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag, name=name, **kwargs)

    def _of_kind(self, kind: str) -> list[CausalCandidate]:
        return [c for c in collect_causal_candidates(self.team, period_days=7) if c.kind == kind]

    def test_empty_team_returns_no_candidates(self) -> None:
        assert collect_causal_candidates(self.team, period_days=7) == []

    def test_flag_candidate_shape(self) -> None:
        flag = self._flag(key="checkout-v2", active=False)

        candidates = self._of_kind("flag")

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.ref == f"flag:{flag.id}"
        assert candidate.label == "checkout-v2"
        assert candidate.happened_at == f"{timezone.now():%Y-%m-%d}"
        assert "created" in candidate.detail
        assert "inactive" in candidate.detail

    @parameterized.expand(
        [
            ("changed_in_period", {"changed_days_ago": 3}, 1),
            ("changed_before_period", {"changed_days_ago": 8}, 0),
            ("deleted", {"deleted": True}, 0),
        ]
    )
    def test_flag_filtering(self, _name: str, overrides: dict[str, Any], expected_count: int) -> None:
        self._flag(**overrides)

        assert len(self._of_kind("flag")) == expected_count

    def test_flag_updated_in_period_notes_updated(self) -> None:
        flag = self._flag(changed_days_ago=10)
        FeatureFlag.objects.filter(id=flag.id).update(updated_at=timezone.now())

        candidates = self._of_kind("flag")

        assert len(candidates) == 1
        assert "updated" in candidates[0].detail
        assert "active" in candidates[0].detail

    @parameterized.expand(
        [
            ("launched_in_period", {"start_date": 2}, ["launched"]),
            ("stopped_in_period", {"start_date": 20, "end_date": 2}, ["stopped"]),
            ("launched_and_stopped_in_period", {"start_date": 5, "end_date": 1}, ["stopped", "launched"]),
            ("outside_period", {"start_date": 20}, []),
            ("never_started", {}, []),
            ("deleted", {"start_date": 2, "deleted": True}, []),
        ]
    )
    def test_experiment_boundary_events(self, _name: str, days_ago: dict[str, Any], expected_events: list[str]) -> None:
        deleted = days_ago.pop("deleted", False)
        dates = {field: timezone.now() - timedelta(days=value) for field, value in days_ago.items()}
        self._experiment(**dates, deleted=deleted)

        candidates = self._of_kind("experiment")

        assert [c.detail.split(" ")[1] for c in candidates] == expected_events

    def test_experiment_candidate_shape(self) -> None:
        started = timezone.now() - timedelta(days=2)
        experiment = self._experiment(name="Checkout experiment", start_date=started)

        candidates = self._of_kind("experiment")

        assert candidates == [
            CausalCandidate(
                kind="experiment",
                ref=f"experiment:{experiment.id}",
                label="Checkout experiment",
                happened_at=f"{started:%Y-%m-%d}",
                detail=f"Experiment launched on {started:%Y-%m-%d}.",
            )
        ]

    @parameterized.expand(
        [
            ("in_period", {}, 1),
            ("before_period", {"days_ago": 8}, 0),
            ("deleted", {"deleted": True}, 0),
            ("no_content", {"content": None}, 0),
        ]
    )
    def test_annotation_filtering(self, _name: str, overrides: dict[str, Any], expected_count: int) -> None:
        defaults: dict[str, Any] = {
            "team": self.team,
            "organization": self.organization,
            "content": "Shipped v2.3",
            "scope": Annotation.Scope.PROJECT,
            "date_marker": timezone.now() - timedelta(days=overrides.pop("days_ago", 1)),
        }
        defaults.update(overrides)
        annotation = Annotation.objects.create(**defaults)

        candidates = self._of_kind("annotation")

        assert len(candidates) == expected_count
        if expected_count:
            assert candidates[0].ref == f"annotation:{annotation.id}"
            assert candidates[0].label == "Shipped v2.3"

    def test_candidates_capped_per_kind_keeping_newest(self) -> None:
        for i in range(MAX_CANDIDATES_PER_KIND + 2):
            self._flag(key=f"flag-{i}", changed_days_ago=i / 24)

        candidates = self._of_kind("flag")

        assert len(candidates) == MAX_CANDIDATES_PER_KIND
        assert candidates[0].label == "flag-0"
        assert all(c.label != f"flag-{MAX_CANDIDATES_PER_KIND}" for c in candidates)

    def test_other_team_resources_excluded(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        FeatureFlag.objects.create(team=other_team, key="other-flag", created_by=self.user)
        Experiment.objects.create(
            team=other_team,
            created_by=self.user,
            feature_flag=FeatureFlag.objects.create(team=other_team, key="other-exp-flag", created_by=self.user),
            name="Other exp",
            start_date=timezone.now(),
        )

        assert collect_causal_candidates(self.team, period_days=7) == []
