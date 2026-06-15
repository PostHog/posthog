from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.flag_matching import FeatureFlagMatcher
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestCloseExposureFlagMatching(APIBaseTest, ClickhouseTestMixin):
    """Correctness proof for closing an experiment's exposure.

    Closing exposure narrows the flag to a static snapshot of the already-exposed
    cohort. The behaviour that matters: an already-exposed user keeps matching (and
    keeps their original variant), while a brand-new user no longer matches.
    """

    def _set_groups(self, flag: FeatureFlag, groups: list[dict]) -> None:
        flag.filters = {**flag.filters, "groups": groups}
        flag.save()

    def _match(self, flag: FeatureFlag, distinct_id: str):
        return FeatureFlagMatcher(
            team_id=self.team.id,
            project_id=self.team.project_id,
            feature_flags=[flag],
            distinct_id=distinct_id,
        ).get_match(flag)

    def test_exposed_user_keeps_matching_and_new_user_is_excluded(self):
        _create_person(team=self.team, distinct_ids=["exposed_user"])
        _create_person(team=self.team, distinct_ids=["new_user"])
        flush_persons_and_events()

        # Snapshot of the actually-exposed users (what close_exposure freezes).
        snapshot = Cohort.objects.create(team=self.team, is_static=True, name="exposure snapshot")
        snapshot.insert_users_by_list(["exposed_user"])

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="close-exposure-matching-flag",
            name="Close exposure matching flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Original variant on the open flag (100% catch-all that everyone matches).
        open_match = self._match(flag, "exposed_user")
        assert open_match.match is True
        assert open_match.variant in {"control", "test"}

        # Close exposure: AND the static-cohort condition into the group on the same flag.
        cohort_condition = {"key": "id", "type": "cohort", "value": snapshot.pk, "operator": "in"}
        self._set_groups(flag, [{"properties": [cohort_condition], "rollout_percentage": 100}])

        # The already-exposed user still matches and keeps the exact same variant —
        # the variant is a deterministic hash of flag key + distinct_id, unaffected by
        # the narrowed group properties.
        closed_match = self._match(flag, "exposed_user")
        assert closed_match.match is True
        assert closed_match.variant == open_match.variant

        # The brand-new user no longer matches — enrollment is closed.
        new_user_match = self._match(flag, "new_user")
        assert new_user_match.match is False
        assert new_user_match.variant is None
