from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# The receivers under test are deliberately not imported here: they must be wired by
# the feature_flags AppConfig, so these tests also fail if that wiring is removed.


def _person_filters(email: str) -> dict:
    return {
        "properties": {
            "type": "OR",
            "values": [{"type": "OR", "values": [{"key": "email", "value": email, "type": "person"}]}],
        }
    }


def _cohort_filters(cohort_id: int) -> dict:
    return {
        "properties": {
            "type": "OR",
            "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_id, "type": "cohort"}]}],
        }
    }


class TestFlagVersionSync(BaseTest):
    def _create_cohort(self, name: str, filters: dict, **kwargs) -> Cohort:
        return Cohort.objects.create(team=self.team, name=name, filters=filters, **kwargs)

    def _create_flag(self, key: str, cohort_id: int) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            created_by=self.user,
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_id}]}]},
        )

    def test_cohort_condition_change_bumps_versions_of_flags_reaching_it(self):
        edited = self._create_cohort("edited", _person_filters("a@a.com"))
        parent = self._create_cohort("parent", _cohort_filters(edited.pk))
        static_parent = self._create_cohort("static-parent", _cohort_filters(edited.pk), is_static=True)
        unrelated = self._create_cohort("unrelated", _person_filters("b@b.com"))

        flag_direct = self._create_flag("direct", edited.pk)
        flag_nested = self._create_flag("nested", parent.pk)
        # Static cohorts have materialized membership, so an upstream condition change
        # doesn't alter how flags referencing them evaluate.
        flag_behind_static = self._create_flag("behind-static", static_parent.pk)
        flag_unrelated = self._create_flag("unrelated", unrelated.pk)
        # Legacy rows can have a NULL version; the bump must produce 1, not NULL.
        FeatureFlag.objects.filter(pk=flag_nested.pk).update(version=None)

        edited.filters = _person_filters("z@z.com")
        edited.save()

        flag_direct.refresh_from_db()
        flag_nested.refresh_from_db()
        flag_behind_static.refresh_from_db()
        flag_unrelated.refresh_from_db()
        assert flag_direct.version == 2
        assert flag_nested.version == 1
        assert flag_behind_static.version == 1
        assert flag_unrelated.version == 1

    def test_malformed_sibling_flag_does_not_block_save_or_bump(self):
        cohort = self._create_cohort("cohort", _person_filters("a@a.com"))
        healthy_flag = self._create_flag("healthy", cohort.pk)
        # get_cohort_ids raises on non-numeric cohort values; a sibling flag with
        # malformed filters must neither break the cohort save nor stop the bump.
        FeatureFlag.objects.create(
            team=self.team,
            key="malformed",
            created_by=self.user,
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": "not-a-number"}]}]},
        )

        cohort.filters = _person_filters("z@z.com")
        cohort.save()

        healthy_flag.refresh_from_db()
        assert healthy_flag.version == 2

    @parameterized.expand(
        [
            ("rename_only_full_save", {"name": "renamed"}, None),
            (
                "recalculation_enqueue_save",
                {"pending_version": 3, "is_calculating": True},
                ["pending_version", "is_calculating"],
            ),
            (
                # The finally-save in calculate_people_ch lists groups and cohort_type
                # in update_fields without changing their values.
                "recalculation_completion_save",
                {"last_calculation": timezone.now(), "errors_calculating": 0},
                ["last_calculation", "errors_calculating", "last_error_at", "cohort_type", "groups"],
            ),
            (
                # A condition field changed in memory but excluded from update_fields
                # is not persisted, so it must not bump either.
                "unpersisted_condition_change",
                {"filters": _person_filters("z@z.com")},
                ["name"],
            ),
            ("unchanged_conditions_full_save", {}, None),
        ]
    )
    def test_non_condition_cohort_saves_do_not_bump_flag_versions(self, _name: str, attrs: dict, update_fields):
        cohort = self._create_cohort("cohort", _person_filters("a@a.com"))
        flag = self._create_flag("flag", cohort.pk)

        for field, value in attrs.items():
            setattr(cohort, field, value)
        cohort.save(update_fields=update_fields) if update_fields is not None else cohort.save()

        flag.refresh_from_db()
        assert flag.version == 1
