from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_storage

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.version_history import reconstruct_flag_at_version

# The receivers under test are deliberately not imported here: they must be wired by
# the feature_flags AppConfig, so these tests also fail if that wiring is removed.


def _updated_entries(flag: FeatureFlag) -> list[ActivityLog]:
    # Flag creation logs a "created" entry via ModelActivityMixin; only "updated"
    # entries are the receiver's output.
    return list(ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(flag.pk), activity="updated"))


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
        # flag_deeply_nested -> grandparent -> parent -> edited forces the multi-hop
        # dependency traversal (get_all_cohort_dependencies' queue must expand parent,
        # then discover edited on a later iteration) -- the single-level parent case
        # above only does one hop.
        grandparent = self._create_cohort("grandparent", _cohort_filters(parent.pk))
        static_parent = self._create_cohort("static-parent", _cohort_filters(edited.pk), is_static=True)
        unrelated = self._create_cohort("unrelated", _person_filters("b@b.com"))

        flag_direct = self._create_flag("direct", edited.pk)
        flag_nested = self._create_flag("nested", parent.pk)
        flag_deeply_nested = self._create_flag("deeply-nested", grandparent.pk)
        # Static cohorts have materialized membership, so an upstream condition change
        # doesn't alter how flags referencing them evaluate.
        flag_behind_static = self._create_flag("behind-static", static_parent.pk)
        flag_unrelated = self._create_flag("unrelated", unrelated.pk)
        # FeatureFlag.objects already excludes soft-deleted rows, but the candidate
        # query relies on that exclusion to keep deleted flags out of local
        # evaluation's payload semantics -- pin it so a manager change can't
        # silently start bumping deleted flags' versions.
        flag_deleted = self._create_flag("deleted", edited.pk)
        FeatureFlag.objects_including_soft_deleted.filter(pk=flag_deleted.pk).update(deleted=True)
        # Legacy rows can have a NULL version; the bump must produce 1, not NULL.
        FeatureFlag.objects.filter(pk=flag_nested.pk).update(version=None)

        edited.filters = _person_filters("z@z.com")
        edited.save()

        flag_direct.refresh_from_db()
        flag_nested.refresh_from_db()
        flag_deeply_nested.refresh_from_db()
        flag_behind_static.refresh_from_db()
        flag_unrelated.refresh_from_db()
        flag_deleted.refresh_from_db()
        assert flag_direct.version == 2
        assert flag_nested.version == 1
        assert flag_deeply_nested.version == 2
        assert flag_behind_static.version == 1
        assert flag_unrelated.version == 1
        assert flag_deleted.version == 1

        # Every bump writes a flag-history entry whose version change matches the row —
        # version_history reconstruction breaks on versions with no (or a mismatched) entry.
        assert _updated_entries(flag_behind_static) == []
        assert _updated_entries(flag_unrelated) == []
        assert _updated_entries(flag_deleted) == []
        for flag, before, after in ((flag_direct, 1, 2), (flag_nested, None, 1)):
            (entry,) = _updated_entries(flag)
            detail = entry.detail
            assert detail is not None
            assert detail["changes"] == [
                {"type": "FeatureFlag", "action": "changed", "field": "version", "before": before, "after": after}
            ]
            assert detail["trigger"] == {
                "job_type": "cohort_conditions_updated",
                "job_id": str(edited.pk),
                "payload": {"cohort_id": edited.pk, "cohort_name": "edited"},
            }
            assert detail["name"] == flag.key
            # No request context in this test, so the entry is a system action.
            assert entry.user is None
            assert entry.is_system is True

    def test_flag_history_entry_attributes_the_cohort_editor(self):
        cohort = self._create_cohort("cohort", _person_filters("a@a.com"))
        flag = self._create_flag("flag", cohort.pk)
        # Middleware populates activity_storage with the request user; the receiver must
        # attribute the flag-history entry to whoever edited the cohort.
        activity_storage.set_user(self.user)
        self.addCleanup(activity_storage.clear_all)

        cohort.filters = _person_filters("z@z.com")
        cohort.save()

        (entry,) = _updated_entries(flag)
        assert entry.user == self.user
        assert entry.is_system is False

    def test_version_history_reconstructable_across_cohort_driven_bumps(self):
        cohort = self._create_cohort("cohort", _person_filters("a@a.com"))
        original_filters = {"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort.pk}]}]}
        flag = self._create_flag("flag", cohort.pk)

        cohort.filters = _person_filters("z@z.com")
        cohort.save()  # version 2, via the receiver

        flag.refresh_from_db()
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 50}]}
        flag.version = 3
        flag.save()  # version 3, via ModelActivityMixin like a regular edit

        # Version 2 exists only because of the cohort bump; without the receiver's
        # activity entry this raised VersionHistoryIncomplete.
        at_v2 = reconstruct_flag_at_version(flag, 2, self.team.pk)
        assert at_v2["version"] == 2
        assert at_v2["filters"] == original_filters
        assert at_v2["is_historical"] is True

        # Undoing the cohort-bump entry must only rewind `version`, never touch other fields.
        at_v1 = reconstruct_flag_at_version(flag, 1, self.team.pk)
        assert at_v1["version"] == 1
        assert at_v1["filters"] == original_filters

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
                # The finally-save in calculate_people_ch persists only recalculation
                # bookkeeping fields, none of which are cohort-definition fields.
                "recalculation_completion_save",
                {"last_calculation": timezone.now(), "errors_calculating": 0},
                ["last_calculation", "errors_calculating", "last_error_at", "cohort_type"],
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
        # Recalculation bookkeeping must not spam flag history either.
        assert _updated_entries(flag) == []
