from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.team import Team

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


def _flag_dependency_filters(dependency_flag_id: int | str) -> dict:
    return {
        "groups": [
            {
                "properties": [
                    {"key": str(dependency_flag_id), "type": "flag", "operator": "flag_evaluates_to", "value": True}
                ]
            }
        ]
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

    def test_cohort_condition_change_cascades_through_flag_dependencies(self):
        cohort = self._create_cohort("cohort", _person_filters("a@a.com"))
        flag_using_cohort = self._create_flag("uses-cohort", cohort.pk)
        # The cohort bump is a bulk update, which fires no signals, so this path has to
        # expand flag dependents itself or these two never move.
        dependent = FeatureFlag.objects.create(
            team=self.team,
            key="dependent",
            created_by=self.user,
            filters=_flag_dependency_filters(flag_using_cohort.pk),
        )
        transitive = FeatureFlag.objects.create(
            team=self.team, key="transitive", created_by=self.user, filters=_flag_dependency_filters(dependent.pk)
        )

        cohort.filters = _person_filters("z@z.com")
        cohort.save()

        for flag in (flag_using_cohort, dependent, transitive):
            flag.refresh_from_db()
            assert flag.version == 2

        # Each flag's history names the source it actually reaches: only the flag with the
        # cohort condition names the cohort, and a flag further down the chain names the
        # flag it depends on rather than a cohort it has no reference to.
        (cohort_entry,) = _updated_entries(flag_using_cohort)
        assert cohort_entry.detail is not None
        assert cohort_entry.detail["trigger"] == {
            "job_type": "cohort_conditions_updated",
            "job_id": str(cohort.pk),
            "payload": {"cohort_id": cohort.pk, "cohort_name": "cohort"},
        }
        for flag in (dependent, transitive):
            (entry,) = _updated_entries(flag)
            assert entry.detail is not None
            assert entry.detail["trigger"] == {
                "job_type": "flag_dependency_updated",
                "job_id": str(flag_using_cohort.pk),
                "payload": {"flag_id": flag_using_cohort.pk, "flag_key": flag_using_cohort.key},
            }

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
        # Recalculation bookkeeping must not spam flag history either.
        assert _updated_entries(flag) == []


class TestFlagDependencyVersionSync(BaseTest):
    def _create_flag(self, key: str, filters: dict, **kwargs) -> FeatureFlag:
        return FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, filters=filters, **kwargs)

    def _create_chain(self) -> tuple[FeatureFlag, FeatureFlag, FeatureFlag]:
        base = self._create_flag("base", {"groups": [{"properties": [], "rollout_percentage": 100}]})
        dependent = self._create_flag("dependent", _flag_dependency_filters(base.pk))
        transitive = self._create_flag("transitive", _flag_dependency_filters(dependent.pk))
        return base, dependent, transitive

    def test_flag_definition_change_bumps_versions_of_flags_depending_on_it(self):
        base, dependent, transitive = self._create_chain()
        # dependent also depends on transitive, so the walk revisits an already-bumped
        # flag; validation rejects cycles but a direct write can still leave one behind.
        FeatureFlag.objects.filter(pk=dependent.pk).update(
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(base.pk), "type": "flag", "operator": "flag_evaluates_to", "value": True},
                            {"key": str(transitive.pk), "type": "flag", "operator": "flag_evaluates_to", "value": True},
                        ]
                    }
                ]
            }
        )
        inactive = self._create_flag("inactive", _flag_dependency_filters(base.pk), active=False)
        unrelated = self._create_flag("unrelated", {"groups": [{"properties": [], "rollout_percentage": 50}]})
        # A dependency key that isn't a flag id must be skipped, not crash the save.
        malformed = self._create_flag("malformed", _flag_dependency_filters("not-a-number"))
        deleted = self._create_flag("deleted", _flag_dependency_filters(base.pk))
        FeatureFlag.objects_including_soft_deleted.filter(pk=deleted.pk).update(deleted=True)
        # Legacy rows can have a NULL version; the bump must produce 1, not NULL.
        FeatureFlag.objects.filter(pk=transitive.pk).update(version=None)
        # Dependencies are validated project-wide, so a sibling team's flag is downstream
        # too — while another project's flag must never be touched.
        sibling_team = Team.objects.create(organization=self.organization, project=self.team.project, name="sibling")
        sibling_dependent = FeatureFlag.objects.create(
            team=sibling_team, key="sibling-dependent", created_by=self.user, filters=_flag_dependency_filters(base.pk)
        )
        other_project_team = Team.objects.create(organization=self.organization, name="other project")
        other_project_dependent = FeatureFlag.objects.create(
            team=other_project_team,
            key="other-project-dependent",
            created_by=self.user,
            filters=_flag_dependency_filters(base.pk),
        )

        base.filters = {"groups": [{"properties": [], "rollout_percentage": 25}]}
        base.save()

        for flag, expected_version in (
            (base, 1),  # bumped by whoever edits it, not by this receiver
            (dependent, 2),
            (transitive, 1),  # NULL -> 1
            (inactive, 2),  # local evaluation ships disabled flags so dependencies resolve
            (sibling_dependent, 2),
            (unrelated, 1),
            (malformed, 1),
            (deleted, 1),
            (other_project_dependent, 1),
        ):
            flag.refresh_from_db()
            assert flag.version == expected_version, flag.key
        assert _updated_entries(unrelated) == []
        assert _updated_entries(deleted) == []
        assert _updated_entries(other_project_dependent) == []

    @parameterized.expand(
        [
            ("filters", {"filters": {"groups": [{"properties": [], "rollout_percentage": 10}]}}, None, 2),
            ("active", {"active": False}, ["active"], 2),
            ("key", {"key": "renamed"}, ["key"], 2),
            ("name_only", {"name": "renamed"}, None, 1),
            ("analytics_bookkeeping_only", {"has_enriched_analytics": True}, ["has_enriched_analytics"], 1),
            # A definition field changed in memory but excluded from update_fields is not
            # persisted, so it must not bump either.
            (
                "unpersisted_definition_change",
                {"filters": {"groups": [{"properties": [], "rollout_percentage": 10}]}},
                ["name"],
                1,
            ),
            ("unchanged_full_save", {}, None, 1),
        ]
    )
    def test_only_definition_changes_bump_dependents(
        self, _name: str, attrs: dict, update_fields, expected_version: int
    ):
        base, dependent, _ = self._create_chain()

        for field, value in attrs.items():
            setattr(base, field, value)
        base.save(update_fields=update_fields) if update_fields is not None else base.save()

        dependent.refresh_from_db()
        assert dependent.version == expected_version
        if expected_version == 1:
            # Metadata edits must not churn SDK caches or spam dependents' flag history.
            assert _updated_entries(dependent) == []

    def test_editing_an_already_deleted_flag_does_not_bump_dependents(self):
        base, dependent, _ = self._create_chain()

        base.deleted = True
        base.save(update_fields=["deleted"])
        dependent.refresh_from_db()
        assert dependent.version == 2

        # Freeing the key for reuse renames the tombstone, which is in no payload either
        # way, so it must not bump a second time.
        base.key = "base-deleted-1"
        base.save(update_fields=["key"])

        dependent.refresh_from_db()
        assert dependent.version == 2
        assert len(_updated_entries(dependent)) == 1

    def test_restoring_a_soft_deleted_flag_bumps_its_dependents(self):
        base, dependent, _ = self._create_chain()

        base.deleted = True
        base.save(update_fields=["deleted"])
        dependent.refresh_from_db()
        assert dependent.version == 2

        # A restored base re-enters the local-evaluation payload, so its dependents are
        # stale again. Snapshotting through objects_including_soft_deleted is what makes
        # this read as deleted True -> False; the default manager hides the row, so the
        # snapshot would come back empty and the restore would bump nothing.
        base.deleted = False
        base.save(update_fields=["deleted"])

        dependent.refresh_from_db()
        assert dependent.version == 3
        # Both bumps are logged with contiguous versions, which is what
        # reconstruct_flag_at_version walks. ActivityLog has no default ordering.
        transitions = []
        for entry in _updated_entries(dependent):
            detail = entry.detail
            assert detail is not None
            change = detail["changes"][0]
            transitions.append((change["before"], change["after"]))
        assert sorted(transitions) == [(1, 2), (2, 3)]

    def test_sibling_flag_with_non_dict_filters_does_not_block_save_or_bump(self):
        base, dependent, _ = self._create_chain()
        # filters is a JSONField with no shape validation, so a row can hold a non-dict;
        # FeatureFlag.conditions calls .get() on it and raises. That must not abort the
        # save being made to an unrelated flag. The malformed-key case in the chain test
        # can't reach this: a bad key inside a well-shaped dict is caught further in.
        broken = self._create_flag("broken", _flag_dependency_filters(base.pk))
        FeatureFlag.objects.filter(pk=broken.pk).update(filters=[{"properties": []}, {"type": "flag"}])

        base.filters = {"groups": [{"properties": [], "rollout_percentage": 25}]}
        base.save()

        dependent.refresh_from_db()
        assert dependent.version == 2
        # The unparseable flag is skipped rather than bumped: its dependencies can't be
        # read, so it is not known to depend on anything.
        broken.refresh_from_db()
        assert broken.version == 1

    def test_dependency_driven_bump_is_attributed_and_reconstructable(self):
        base, dependent, _ = self._create_chain()
        original_filters = dependent.get_filters()
        activity_storage.set_user(self.user)
        self.addCleanup(activity_storage.clear_all)

        base.filters = {"groups": [{"properties": [], "rollout_percentage": 25}]}
        base.save()

        (entry,) = _updated_entries(dependent)
        assert entry.user == self.user
        detail = entry.detail
        assert detail is not None
        assert detail["name"] == dependent.key
        assert detail["changes"] == [
            {"type": "FeatureFlag", "action": "changed", "field": "version", "before": 1, "after": 2}
        ]
        assert detail["trigger"] == {
            "job_type": "flag_dependency_updated",
            "job_id": str(base.pk),
            "payload": {"flag_id": base.pk, "flag_key": base.key},
        }

        # Without the entry above this raises VersionHistoryIncomplete: version 2 exists
        # on the row with nothing in the activity log accounting for it.
        dependent.refresh_from_db()
        at_v1 = reconstruct_flag_at_version(dependent, 1, self.team.pk)
        assert at_v1["version"] == 1
        assert at_v1["filters"] == original_filters
        assert at_v1["is_historical"] is True
