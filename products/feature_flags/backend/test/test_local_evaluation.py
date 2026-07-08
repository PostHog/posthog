from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import DatabaseError
from django.test import override_settings

from parameterized import parameterized

from posthog.models.group_type_mapping import GROUP_TYPES_STALE_CACHE_KEY_PREFIX, GroupTypesUnavailable
from posthog.models.project import Project
from posthog.models.tag import Tag
from posthog.models.team.team import Team
from posthog.personhog_client.fake_client import get_active_fake
from posthog.test.persons import _seed_group_type_mapping_into_fake, create_group_type_mapping
from posthog.test.test_utils import create_group_type_mapping_without_created_at
from posthog.utils import safe_cache_delete

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.flags_cache import get_team_ids_with_recently_updated_flags
from products.feature_flags.backend.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    _extract_cohort_ids_from_filters,
    _get_flags_response_for_local_evaluation,
    _get_flags_response_for_local_evaluation_batch,
    _update_flag_definitions,
    clear_flag_definition_caches,
    flag_definitions_hypercache,
    update_flag_caches,
    update_flag_definitions_cache,
    verify_team_flag_definitions,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey


class TestLocalEvaluationCache(BaseTest):
    def setUp(self):
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.team = team
        self._create_examples(self.team)
        clear_flag_definition_caches(self.team)

    def _create_examples(self, team: Team):
        FeatureFlag.objects.all().delete()

        cohorts = []
        flags = []

        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )
        cohorts.append(cohort_valid_for_ff)

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                                {
                                    "key": "id",
                                    "value": cohort_valid_for_ff.pk,
                                    "type": "cohort",
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )
        cohorts.append(cohort2)

        ff1 = FeatureFlag.objects.create(
            team=self.team,
            key="alpha-feature",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
        )
        flags.append(ff1)

        ff2 = FeatureFlag.objects.create(
            team=self.team,
            key="alpha-feature-2",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [{"key": "id", "type": "cohort", "value": cohort_valid_for_ff.pk}],
                    }
                ],
            },
        )

        flags.append(ff2)

        return flags, cohorts

    def _assert_payload_valid_with_cohorts(self, response: dict | None):
        assert response is not None
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_generates_correct_local_evaluation_response(self):
        response = flag_definitions_hypercache.get_from_cache(self.team)
        assert response
        assert len(response.get("flags", [])) == 2
        assert response.get("group_type_mapping", {}) == {"0": "organization"}
        assert len(response.get("cohorts", {})) == 2

    def test_get_flags_cache_hot(self):
        update_flag_caches(self.team)
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cache_warm(self):
        update_flag_caches(self.team)
        clear_flag_definition_caches(self.team, kinds=["redis"])
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "s3"
        self._assert_payload_valid_with_cohorts(response)

    def test_get_flags_cold(self):
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"
        self._assert_payload_valid_with_cohorts(response)

        # second request should be cached in redis
        response, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        self._assert_payload_valid_with_cohorts(response)


class TestUpdateFlagCachesGroupMappingGuards(BaseTest):
    def setUp(self):
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Guard project",
        )
        self.team = team
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="group-flag",
            filters={"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 100}]},
        )
        clear_flag_definition_caches(self.team)
        self._clear_stale()

    def tearDown(self):
        self._clear_stale()
        super().tearDown()

    def _clear_stale(self):
        safe_cache_delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.team.project_id}")

    def _cached_group_type_mapping(self) -> dict:
        response, _ = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        return (response or {}).get("group_type_mapping", {})

    @patch("posthog.storage.hypercache.HYPERCACHE_WRITE_SKIPPED_UNCHANGED_COUNTER")
    def test_unchanged_rebuild_skips_write(self, mock_skip_counter):
        # The signal path opts into skip_if_unchanged=True. A second rebuild with no flag
        # changes must skip the rewrite; dropping the kwarg silently reverts the
        # optimization and only this assertion would catch it.
        update_flag_caches(self.team)
        mock_skip_counter.labels.assert_not_called()

        update_flag_caches(self.team)

        mock_skip_counter.labels.assert_called_once_with(namespace="feature_flags", value="flags_with_cohorts.json")
        assert mock_skip_counter.labels.return_value.inc.call_count == 1

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_REBUILD_SKIPPED_COUNTER")
    def test_skips_write_on_group_types_unavailable(self, mock_skipped_counter):
        # Warm with the real fetch so a prior good entry exists
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}

        # Persons DB now unavailable with no recoverable last-known-good
        with patch(
            "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
            side_effect=GroupTypesUnavailable([self.team.project_id]),
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                update_flag_caches(self.team)
                mock_set.assert_not_called()

        mock_skipped_counter.labels.assert_called_once_with(namespace="feature_flags", reason="group_types_unavailable")
        # Prior good entry survives untouched
        assert self._cached_group_type_mapping() == {"0": "organization"}

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_skips_write_when_mapping_would_be_emptied(self, mock_emptied_counter):
        # Warm with the real fetch so the non-empty last-known-good stale exists
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}

        # Fetch now returns empty without erroring, while last-known-good is non-empty
        with patch(
            "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
            return_value={self.team.project_id: []},
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                update_flag_caches(self.team)
                mock_set.assert_not_called()

        mock_emptied_counter.labels.assert_called_once_with(namespace="feature_flags")
        assert self._cached_group_type_mapping() == {"0": "organization"}

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_refresh_path_skips_write_when_mapping_would_be_emptied(self, mock_emptied_counter):
        # The periodic refresh/warm path goes through update_cache, not update_flag_caches.
        # It must apply the same guard so a silent empty can't overwrite good data here either.
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}

        with patch(
            "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
            return_value={self.team.project_id: []},
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                assert _update_flag_definitions(self.team) is False
                mock_set.assert_not_called()

        mock_emptied_counter.labels.assert_called_once_with(namespace="feature_flags")
        assert self._cached_group_type_mapping() == {"0": "organization"}

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_single_project_empty_success_does_not_defeat_guard(self, mock_emptied_counter):
        # Layer interaction: the high-frequency single-project fetch shares the stale
        # key with the rebuild guard. A single-project empty-success must not clobber
        # that key, or a later rebuild would wave the empty mapping through.
        from posthog.models.group_type_mapping import GROUP_TYPES_CACHE_KEY_PREFIX, get_group_types_for_project

        # Warm with the real fetch so the non-empty last-known-good stale exists.
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}

        # A single-project fetch returns empty without erroring (the empty-but-not-
        # erroring upstream). It must not overwrite the populated stale fallback.
        safe_cache_delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}")
        with (
            patch("posthog.personhog_client.client.get_personhog_client", return_value=MagicMock()),
            patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog", return_value=[]),
        ):
            assert get_group_types_for_project(self.team.project_id) == []

        # Stale survived, so a subsequent empty-success rebuild still trips the guard.
        with patch(
            "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
            return_value={self.team.project_id: []},
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                update_flag_caches(self.team)
                mock_set.assert_not_called()

        mock_emptied_counter.labels.assert_called_once_with(namespace="feature_flags")
        assert self._cached_group_type_mapping() == {"0": "organization"}

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_writes_when_genuinely_empty(self, mock_emptied_counter):
        # A team that truly has no group types must still rebuild normally
        fake = get_active_fake()
        fake._group_type_mappings_by_project.pop(self.team.project_id, None)
        fake._group_type_mappings_by_team.pop(self.team.id, None)
        self._clear_stale()
        clear_flag_definition_caches(self.team)

        update_flag_caches(self.team)

        # Wrote an empty mapping (correct for this team) without tripping the guard
        assert self._cached_group_type_mapping() == {}
        mock_emptied_counter.labels.assert_not_called()

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_skips_write_when_stale_absent_but_primary_has_group_types(self, mock_emptied_counter):
        # TOCTOU / replica-lag: the stale key was deleted by a concurrent
        # invalidate_group_types_cache (or expired) while the group type still exists.
        # The guard must confirm against the primary, not wave the empty through.
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}

        # Simulate the concurrent invalidation deleting the last-known-good stale key.
        self._clear_stale()

        # Fetch returns empty without erroring, but the row still exists in the DB.
        with patch(
            "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
            return_value={self.team.project_id: []},
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                update_flag_caches(self.team)
                mock_set.assert_not_called()

        mock_emptied_counter.labels.assert_called_once_with(namespace="feature_flags")
        assert self._cached_group_type_mapping() == {"0": "organization"}

    @patch("products.feature_flags.backend.local_evaluation.HYPERCACHE_GROUP_MAPPING_EMPTIED_COUNTER")
    def test_fails_closed_when_confirmation_read_errors(self, mock_emptied_counter):
        # Stale absent and the authoritative confirmation read fails: the guard must
        # fail closed (block the empty write) rather than risk clobbering good data.
        update_flag_caches(self.team)
        assert self._cached_group_type_mapping() == {"0": "organization"}
        self._clear_stale()

        with (
            patch(
                "products.feature_flags.backend.local_evaluation.get_group_types_for_projects",
                return_value={self.team.project_id: []},
            ),
            patch(
                "posthog.models.group_type_mapping._fetch_group_types_for_project_direct",
                side_effect=DatabaseError("persons db down"),
            ),
        ):
            with patch.object(flag_definitions_hypercache, "set_cache_value") as mock_set:
                update_flag_caches(self.team)
                mock_set.assert_not_called()

        mock_emptied_counter.labels.assert_called_once_with(namespace="feature_flags")
        assert self._cached_group_type_mapping() == {"0": "organization"}


class TestLocalEvaluationSignals(BaseTest):
    @parameterized.expand(["create", "soft_delete", "delete"])
    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_experiment_change(self, action, mock_task):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="exp-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        if action == "create":
            mock_task.reset_mock()
            Experiment.objects.create(team=self.team, name="My experiment", feature_flag=flag)
        else:
            experiment = Experiment.objects.create(team=self.team, name="My experiment", feature_flag=flag)
            mock_task.reset_mock()
            if action == "soft_delete":
                experiment.deleted = True
                experiment.save()
            else:
                experiment.delete()

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_context_association_create(self, mock_task):
        """Creating a FeatureFlagEvaluationContext fires the cache update signal."""
        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        # Create the context first (this will fire a signal for EvaluationContext.post_save)
        ctx = EvaluationContext.objects.create(team=self.team, name="production")

        mock_task.reset_mock()

        # Creating the association should fire the signal
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_context_association_delete(self, mock_task):
        """Deleting a FeatureFlagEvaluationContext fires the cache update signal."""
        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        ctx = EvaluationContext.objects.create(team=self.team, name="production")
        eval_ctx = FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        mock_task.reset_mock()

        eval_ctx.delete()

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_not_fired_on_evaluation_context_create(self, mock_task):
        """Creating an EvaluationContext does NOT fire the cache update signal.

        New contexts can't be referenced by any flags yet, so invalidation is a no-op.
        """
        from products.feature_flags.backend.models.evaluation_context import EvaluationContext

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        mock_task.reset_mock()

        EvaluationContext.objects.create(team=self.team, name="production")

        mock_task.delay.assert_not_called()

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_evaluation_context_rename(self, mock_task):
        """Renaming an EvaluationContext fires the cache update signal.

        Flags referencing the context need to pick up the new name.
        """
        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        ctx = EvaluationContext.objects.create(team=self.team, name="production")
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        mock_task.reset_mock()

        ctx.name = "staging"
        ctx.save()

        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_tag_rename_does_not_fire_signal(self, mock_task):
        """Tag renames no longer affect evaluation contexts, so no cache invalidation needed."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        tag = Tag.objects.create(team=self.team, name="docs-page")

        mock_task.reset_mock()

        tag.name = "landing-page"
        tag.save()

        mock_task.delay.assert_not_called()


class TestSurveyFlagExclusion(BaseTest):
    """Tests for excluding survey-linked flags from local evaluation (GitHub issue #43631)."""

    def setUp(self):
        super().setUp()
        # Clear existing flags and caches to ensure test isolation
        FeatureFlag.objects.filter(team=self.team).delete()
        Survey.objects.filter(team=self.team).delete()
        clear_flag_definition_caches(self.team)

    @parameterized.expand(
        [
            ("targeting_flag", "targeting_flag"),
            ("internal_targeting_flag", "internal_targeting_flag"),
            ("internal_response_sampling_flag", "internal_response_sampling_flag"),
        ]
    )
    def test_survey_linked_flag_excluded_from_local_evaluation(self, _name: str, flag_field: str):
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"survey-{flag_field}-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            **{flag_field: survey_flag},
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]

        assert regular_flag.key in flag_keys
        assert survey_flag.key not in flag_keys

    def test_linked_flag_not_excluded_from_local_evaluation(self):
        """The linked_flag field is user-created and should NOT be excluded."""
        user_linked_flag = FeatureFlag.objects.create(
            team=self.team,
            key="user-linked-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            linked_flag=user_linked_flag,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]

        assert user_linked_flag.key in flag_keys

    def test_deleted_survey_does_not_affect_flag_exclusion(self):
        """Flags from deleted surveys should be included in local evaluation."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="was-survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

        survey.delete()

        response = _get_flags_response_for_local_evaluation(self.team)
        assert survey_flag.key in [f["key"] for f in response["flags"]]

    def test_survey_flags_excluded_from_api_response(self):
        """Verify the full API response excludes survey flags."""
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            internal_targeting_flag=survey_flag,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        assert response is not None
        flag_keys = [f["key"] for f in response["flags"]]

        assert regular_flag.key in flag_keys
        assert survey_flag.key not in flag_keys

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_flag_cache_invalidated_on_survey_change(self, mock_task):
        """Creating/deleting a survey should invalidate the flag cache."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        mock_task.reset_mock()

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        mock_task.delay.assert_called_with(self.team.id)

        mock_task.reset_mock()

        survey.delete()

        mock_task.delay.assert_called_with(self.team.id)

    @patch("products.feature_flags.backend.tasks.update_team_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_flag_cache_invalidated_on_survey_update(self, mock_task):
        """Updating a survey should invalidate the flag cache."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        mock_task.reset_mock()

        survey.name = "Updated Survey Name"
        survey.save()

        mock_task.delay.assert_called_with(self.team.id)

    def test_archived_survey_flag_still_excluded(self):
        """Flags from archived surveys should still be excluded from local evaluation."""
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="archived-survey-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=survey_flag,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

        # Archive the survey (not delete)
        survey.archived = True
        survey.save()

        # Flag should still be excluded since the survey still exists
        response = _get_flags_response_for_local_evaluation(self.team)
        assert survey_flag.key not in [f["key"] for f in response["flags"]]

    def test_survey_flag_reassignment_updates_exclusions(self):
        """When a survey changes which flags it uses, both old and new flags should update correctly."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=flag_a,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]
        assert flag_a.key not in flag_keys
        assert flag_b.key in flag_keys

        survey.targeting_flag = flag_b
        survey.save()

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]
        assert flag_a.key in flag_keys
        assert flag_b.key not in flag_keys

    def test_multiple_surveys_sharing_same_flag(self):
        """When multiple surveys use the same flag, it should be excluded once."""
        shared_flag = FeatureFlag.objects.create(
            team=self.team,
            key="shared-targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        for i in range(3):
            Survey.objects.create(
                team=self.team,
                name=f"Survey {i}",
                type="popover",
                targeting_flag=shared_flag,
            )

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]

        assert shared_flag.key not in flag_keys

    def test_survey_with_partial_flag_assignment(self):
        """Survey with some flags set and others None should only exclude the set flags."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="targeting-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="sampling-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        regular_flag = FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            targeting_flag=flag_a,
            internal_targeting_flag=None,
            internal_response_sampling_flag=flag_b,
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flag_keys = [f["key"] for f in response["flags"]]

        assert flag_a.key not in flag_keys
        assert flag_b.key not in flag_keys
        assert regular_flag.key in flag_keys


class TestExtractCohortIdsFromFilters(BaseTest):
    @parameterized.expand(
        [
            ("empty_filters", {}, set()),
            ("no_groups", {"multivariate": {}}, set()),
            ("empty_groups", {"groups": []}, set()),
            (
                "person_properties_only",
                {"groups": [{"properties": [{"type": "person", "key": "email", "value": "test@example.com"}]}]},
                set(),
            ),
            ("single_cohort", {"groups": [{"properties": [{"type": "cohort", "value": 123}]}]}, {123}),
            (
                "multiple_cohorts_same_group",
                {"groups": [{"properties": [{"type": "cohort", "value": 1}, {"type": "cohort", "value": 2}]}]},
                {1, 2},
            ),
            (
                "cohorts_across_groups",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 10}]},
                        {"properties": [{"type": "cohort", "value": 20}]},
                    ]
                },
                {10, 20},
            ),
            ("string_value_coerced", {"groups": [{"properties": [{"type": "cohort", "value": "456"}]}]}, {456}),
            ("invalid_string_skipped", {"groups": [{"properties": [{"type": "cohort", "value": "bad"}]}]}, set()),
            ("none_value_skipped", {"groups": [{"properties": [{"type": "cohort", "value": None}]}]}, set()),
            (
                "duplicates_collapsed",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 5}]},
                        {"properties": [{"type": "cohort", "value": 5}]},
                    ]
                },
                {5},
            ),
        ]
    )
    def test_extract_cohort_ids(self, _name: str, filters: dict, expected: set):
        assert _extract_cohort_ids_from_filters(filters) == expected


class TestLocalEvaluationBatch(BaseTest):
    def _create_team_with_project(self, name: str) -> Team:
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name=name,
        )
        return team

    def test_batch_empty_team_list(self):
        result = _get_flags_response_for_local_evaluation_batch([])
        assert result == {}

    @parameterized.expand(
        [
            # (is_remote_config, has_encrypted, should_include, description)
            (False, False, True, "regular_flag"),
            (False, True, False, "encrypted_but_not_remote_config"),
            (True, False, True, "unencrypted_remote_config"),
            (True, True, False, "encrypted_remote_config"),
            (None, False, True, "null_remote_config_unencrypted"),
            (None, True, False, "null_remote_config_encrypted"),
            (False, None, True, "regular_flag_null_encrypted"),
            (True, None, True, "remote_config_null_encrypted"),
            (None, None, True, "legacy_flag_both_null"),
        ]
    )
    def test_batch_filtering_matrix_for_encrypted_payloads(self, is_remote_config, has_encrypted, should_include, desc):
        """Mirrors test_filtering_matrix_for_teams_batch in test_flags_cache.py for the local evaluation batch path.

        Any flag with has_encrypted_payloads=True is excluded — these can only be
        accessed via /remote_config. The model invariant (clean() + serializer
        validation) guarantees True implies is_remote_configuration=True, but the
        filter is intentionally strict to defend against invariant violations.
        NULL has_encrypted_payloads is preserved (legacy flags pre-dating the field).
        """
        team = self._create_team_with_project(f"Team {desc}")
        FeatureFlag.objects.create(
            team=team,
            key=f"flag-{desc}",
            created_by=self.user,
            is_remote_configuration=is_remote_config,
            has_encrypted_payloads=has_encrypted,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team])
        flag_keys = {f["key"] for f in results[team.id]["flags"]}

        if should_include:
            assert f"flag-{desc}" in flag_keys, f"Expected flag-{desc} to be included"
        else:
            assert f"flag-{desc}" not in flag_keys, f"Expected flag-{desc} to be excluded"

    def test_batch_two_teams_flags_isolated(self):
        team_a = self._create_team_with_project("Team A")
        team_b = self._create_team_with_project("Team B")

        FeatureFlag.objects.create(
            team=team_a,
            key="flag-a",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        FeatureFlag.objects.create(
            team=team_b,
            key="flag-b",
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_a, team_b])

        assert team_a.id in results
        assert team_b.id in results

        keys_a = [f["key"] for f in results[team_a.id]["flags"]]
        keys_b = [f["key"] for f in results[team_b.id]["flags"]]

        assert keys_a == ["flag-a"]
        assert keys_b == ["flag-b"]

    def test_batch_team_with_no_flags(self):
        team_with_flags = self._create_team_with_project("Has Flags")
        team_without_flags = self._create_team_with_project("No Flags")

        FeatureFlag.objects.create(
            team=team_with_flags,
            key="some-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_with_flags, team_without_flags])

        assert len(results[team_with_flags.id]["flags"]) == 1
        assert results[team_without_flags.id]["flags"] == []
        assert "group_type_mapping" in results[team_without_flags.id]
        assert "cohorts" in results[team_without_flags.id]

    def test_batch_team_with_no_flags_includes_group_type_mapping(self):
        team = self._create_team_with_project("GTM Team")

        create_group_type_mapping_without_created_at(
            team=team, project_id=team.project_id, group_type="company", group_type_index=0
        )

        results = _get_flags_response_for_local_evaluation_batch([team])

        assert results[team.id]["flags"] == []
        assert results[team.id]["group_type_mapping"] == {"0": "company"}

    def test_batch_cohort_isolation_across_projects(self):
        team_a = self._create_team_with_project("Project A")
        team_b = self._create_team_with_project("Project B")

        cohort_a = Cohort.objects.create(
            team=team_a,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="cohort-a",
        )
        cohort_b = Cohort.objects.create(
            team=team_b,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
            name="cohort-b",
        )

        FeatureFlag.objects.create(
            team=team_a,
            key="flag-with-cohort-a",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.pk}]}]},
        )
        FeatureFlag.objects.create(
            team=team_b,
            key="flag-with-cohort-b",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_b.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team_a, team_b])

        cohort_ids_a = set(results[team_a.id]["cohorts"].keys())
        cohort_ids_b = set(results[team_b.id]["cohorts"].keys())

        assert str(cohort_a.pk) in cohort_ids_a
        assert str(cohort_b.pk) not in cohort_ids_a

        assert str(cohort_b.pk) in cohort_ids_b
        assert str(cohort_a.pk) not in cohort_ids_b

    def test_batch_only_loads_referenced_cohorts(self):
        """Cohorts not referenced by any flag filter should not appear in the response."""
        team = self._create_team_with_project("Selective Cohort Team")

        referenced_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="referenced-cohort",
        )
        unreferenced_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
            name="unreferenced-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": referenced_cohort.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team])

        assert str(referenced_cohort.pk) in results[team.id]["cohorts"]
        assert str(unreferenced_cohort.pk) not in results[team.id]["cohorts"]

    def test_batch_static_cohort_excluded(self):
        """Static cohorts cannot be locally evaluated and should not appear in the response."""
        team = self._create_team_with_project("Static Cohort Team")

        static_cohort = Cohort.objects.create(
            team=team,
            name="static-cohort",
            is_static=True,
        )
        dynamic_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="dynamic-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-both",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": static_cohort.pk},
                            {"key": "id", "type": "cohort", "value": dynamic_cohort.pk},
                        ]
                    }
                ]
            },
        )

        results = _get_flags_response_for_local_evaluation_batch([team])

        assert str(dynamic_cohort.pk) in results[team.id]["cohorts"]
        assert str(static_cohort.pk) not in results[team.id]["cohorts"]

    def test_batch_loads_nested_cohort_dependencies(self):
        """Cohorts referenced transitively through other cohorts should be loaded."""
        team = self._create_team_with_project("Nested Cohort Team")

        leaf_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="leaf-cohort",
        )
        parent_cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "OR", "values": [{"key": "id", "value": leaf_cohort.pk, "type": "cohort"}]},
                    ],
                }
            },
            name="parent-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="flag-with-nested-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": parent_cohort.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team])

        assert str(parent_cohort.pk) in results[team.id]["cohorts"]
        assert str(leaf_cohort.pk) in results[team.id]["cohorts"]

    def test_batch_loads_deeply_nested_cohort_chain(self):
        """Three-level cohort chain (grandparent -> parent -> leaf) exercises multiple iterations of the loading loop."""
        team = self._create_team_with_project("Deep Nesting Team")

        leaf = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="leaf",
        )
        parent = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": leaf.pk, "type": "cohort"}]}],
                }
            },
            name="parent",
        )
        grandparent = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": parent.pk, "type": "cohort"}]}],
                }
            },
            name="grandparent",
        )

        FeatureFlag.objects.create(
            team=team,
            key="deep-flag",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": grandparent.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team])
        cohort_ids = set(results[team.id]["cohorts"].keys())

        assert str(grandparent.pk) in cohort_ids
        assert str(parent.pk) in cohort_ids
        assert str(leaf.pk) in cohort_ids

    def test_batch_circular_cohort_references_terminate(self):
        """Circular cohort dependencies (A -> B -> A) should not cause an infinite loop."""
        team = self._create_team_with_project("Circular Cohort Team")

        cohort_a = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="cohort-a",
        )
        cohort_b = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_a.pk, "type": "cohort"}]}],
                }
            },
            name="cohort-b",
        )

        # Create the circular reference: A -> B -> A
        cohort_a.filters = {
            "properties": {
                "type": "OR",
                "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_b.pk, "type": "cohort"}]}],
            }
        }
        cohort_a.save()

        FeatureFlag.objects.create(
            team=team,
            key="circular-flag",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.pk}]}]},
        )

        results = _get_flags_response_for_local_evaluation_batch([team])
        cohort_ids = set(results[team.id]["cohorts"].keys())

        assert str(cohort_a.pk) in cohort_ids
        assert str(cohort_b.pk) in cohort_ids

    def test_batch_no_cohort_flags_skips_cohort_loading(self):
        """When no flags reference cohorts, the cohort query should be skipped entirely."""
        team = self._create_team_with_project("No Cohort Team")

        Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
            name="unused-cohort",
        )

        FeatureFlag.objects.create(
            team=team,
            key="simple-flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        with self.assertNumQueries(2):
            # Expected queries: survey flag IDs and flags (with evaluation
            # tags via ArrayAgg). Group type mappings are read from
            # personhog, not SQL. No cohort query should be issued.
            results = _get_flags_response_for_local_evaluation_batch([team])

        assert results[team.id]["cohorts"] == {}
        assert len(results[team.id]["flags"]) == 1

    def test_batch_deleted_cohort_handled_gracefully(self):
        team = self._create_team_with_project("Deleted Cohort Team")

        cohort = Cohort.objects.create(
            team=team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "x@x.com", "type": "person"}]}],
                }
            },
            name="soon-deleted",
        )
        cohort_id = cohort.pk

        FeatureFlag.objects.create(
            team=team,
            key="flag-ref-deleted-cohort",
            filters={"groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort_id}]}]},
        )

        # Soft-delete the cohort
        cohort.deleted = True
        cohort.save()

        results = _get_flags_response_for_local_evaluation_batch([team])

        flag_keys = [f["key"] for f in results[team.id]["flags"]]
        assert "flag-ref-deleted-cohort" in flag_keys
        assert str(cohort_id) not in results[team.id]["cohorts"]


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestFlagDefinitionsCache(BaseTest):
    """Tests for flag definitions HyperCache operations."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_cache_key_format_is_stable(self):
        """
        Changing the key format would orphan existing cached data,
        causing a cold cache on deploy.
        """
        key = flag_definitions_hypercache.get_cache_key(self.team)

        assert key == f"cache/teams/{self.team.id}/feature_flags/flags_with_cohorts.json"

    def test_update_flag_definitions_cache_accepts_team_id(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team.id)
        assert result is True

        data, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"
        assert data is not None
        assert len(data["flags"]) == 1

    def test_update_flag_definitions_cache_returns_false_for_nonexistent_team(self):
        result = update_flag_definitions_cache(999999)
        assert result is False

    def test_clear_flag_definition_caches(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        _, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "redis"

        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

        _, source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"

    def test_hypercache_config_is_properly_configured(self):
        config = FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG
        assert config.cache_name == "flag_definitions"
        assert config.hypercache == flag_definitions_hypercache
        assert config.update_fn == _update_flag_definitions
        # Grace-period skip prevents the verifier from flagging caches whose
        # underlying flags were just updated and whose async rebuild is still in flight.
        assert config.get_team_ids_to_skip_fix_fn == get_team_ids_with_recently_updated_flags

    def test_update_flag_definitions_cache_returns_false_on_failure(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with patch.object(flag_definitions_hypercache, "update_cache", return_value=False):
            result = update_flag_definitions_cache(self.team)

        assert result is False

    def test_update_flag_definitions_cache_passes_custom_ttl(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        with patch.object(flag_definitions_hypercache, "update_cache", return_value=True) as mock_update:
            update_flag_definitions_cache(self.team, ttl=3600)

        mock_update.assert_called_once_with(self.team, ttl=3600)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestVerifyFlagDefinitions(BaseTest):
    """Tests for flag definitions cache verification."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_verify_returns_miss_when_cache_empty(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = verify_team_flag_definitions(self.team)

        assert result["status"] == "miss"
        assert result["issue"] == "CACHE_MISS"

    def test_verify_returns_match_when_cache_matches(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        result = verify_team_flag_definitions(self.team)

        assert result["status"] == "match"
        assert result["issue"] == ""

    def test_verify_returns_mismatch_when_flag_key_renamed(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        flag.key = "modified-flag"
        flag.save()

        result = verify_team_flag_definitions(self.team, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "1 missing, 1 stale" in result["details"]
        missing_diffs = [d for d in result["diffs"] if d["type"] == "MISSING_IN_CACHE"]
        stale_diffs = [d for d in result["diffs"] if d["type"] == "STALE_IN_CACHE"]
        assert len(missing_diffs) == 1
        assert missing_diffs[0]["flag_key"] == "modified-flag"
        assert len(stale_diffs) == 1
        assert stale_diffs[0]["flag_key"] == "test-flag"

    def test_verify_returns_field_mismatch_when_flag_filters_changed(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flag_definitions_cache(self.team)

        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 50}]}
        flag.save()

        result = verify_team_flag_definitions(self.team, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "1 mismatched" in result["details"]
        field_mismatch_diffs = [d for d in result["diffs"] if d["type"] == "FIELD_MISMATCH"]
        assert len(field_mismatch_diffs) == 1
        assert field_mismatch_diffs[0]["flag_key"] == "test-flag"

    @parameterized.expand(
        [
            (
                "extra_key_in_cache_is_tolerated",
                lambda flag: flag.__setitem__("legacy_field_that_no_longer_exists", True),
                "match",
                None,
            ),
            (
                "missing_key_in_cache_still_flagged",
                lambda flag: flag.pop("filters"),
                "mismatch",
                "filters",
            ),
        ]
    )
    def test_verify_handles_key_drift_between_cache_and_db(
        self, _name, mutate_cached_flag, expected_status, expected_diff_field
    ):
        """The DB serialization is the source of truth: stale extras in the
        cache must be ignored (otherwise a benign serializer field removal
        rewrites every team's cache), but a key the DB has and the cache
        doesn't is a real divergence and must still be flagged."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flag_definitions_cache(self.team)

        cached_data, _source = flag_definitions_hypercache.get_from_cache_with_source(self.team)
        assert cached_data is not None
        assert len(cached_data["flags"]) == 1
        mutate_cached_flag(cached_data["flags"][0])
        flag_definitions_hypercache.set_cache_value(self.team, cached_data)

        result = verify_team_flag_definitions(self.team, verbose=True)

        assert result["status"] == expected_status
        if expected_diff_field is not None:
            field_mismatch_diffs = [d for d in result["diffs"] if d["type"] == "FIELD_MISMATCH"]
            assert len(field_mismatch_diffs) == 1
            assert field_mismatch_diffs[0]["flag_key"] == "test-flag"
            assert expected_diff_field in field_mismatch_diffs[0]["diff_fields"]

    def test_verify_returns_mismatch_when_cohort_changed(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            groups=[{"properties": [{"key": "email", "value": "test@example.com", "type": "person"}]}],
        )

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        update_flag_definitions_cache(self.team)

        cohort.groups = [{"properties": [{"key": "email", "value": "changed@example.com", "type": "person"}]}]
        cohort.save()

        result = verify_team_flag_definitions(self.team, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "cohorts mismatch" in result["details"]
        assert "diffs" in result
        cohorts_diff = [d for d in result["diffs"] if d.get("type") == "COHORTS_MISMATCH"]
        assert len(cohorts_diff) == 1

    def test_verify_returns_mismatch_when_group_type_mapping_changed(self):
        mapping = create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=0,
        )

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={
                "aggregation_group_type_index": 0,
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        update_flag_definitions_cache(self.team)

        mapping.group_type = "organization"
        _seed_group_type_mapping_into_fake(mapping)

        result = verify_team_flag_definitions(self.team, verbose=True)

        assert result["status"] == "mismatch"
        assert result["issue"] == "DATA_MISMATCH"
        assert "group_type_mapping mismatch" in result["details"]
        assert "diffs" in result
        mapping_diff = [d for d in result["diffs"] if d.get("type") == "GROUP_TYPE_MAPPING_MISMATCH"]
        assert len(mapping_diff) == 1


@override_settings(
    FLAGS_REDIS_URL="redis://test",
    CACHES={
        **settings.CACHES,
        "flags_dedicated": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "flags-definitions-test",
        },
    },
)
class TestFlagDefinitionsManagementCommands(BaseTest):
    """Tests for flag definitions cache management commands."""

    def setUp(self):
        super().setUp()
        clear_flag_definition_caches(self.team, kinds=["redis", "s3"])

    def test_verify_command_reports_results(self):
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("verify_flag_definitions_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        assert output.count("Verification Results") == 1

    def test_warm_command_processes_teams(self):
        from io import StringIO

        from django.core.management import call_command

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flag_definitions_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        assert "Successful: 1" in output


@override_settings(FLAGS_REDIS_URL=None)
class TestFlagDefinitionsCacheWithoutRedis(BaseTest):
    def test_update_flag_definitions_cache_returns_true_without_redis(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = update_flag_definitions_cache(self.team)
        assert result is True


class TestFlagDependencyChainTransformation(BaseTest):
    """`dependency_chain` transformation in the local evaluation payload.

    Ported from the removed Django-endpoint tests; exercises `_build_all_dependency_chains`
    via the response builder directly, now that the HTTP endpoint is served by Rust.
    """

    def setUp(self):
        super().setUp()
        FeatureFlag.objects.filter(team=self.team).delete()
        clear_flag_definition_caches(self.team)

    def _find_flag(self, flags: list[dict], key: str) -> dict:
        return next(flag for flag in flags if flag["key"] == key)

    def test_complex_chain(self):
        """Dependency transformation with a chain C -> B -> A (topologically sorted)."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-c",
            name="Flag C",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        flag_c_data = self._find_flag(flags, "flag-c")
        properties = flag_c_data["filters"]["groups"][0]["properties"]
        flag_property = next(prop for prop in properties if prop["type"] == "flag")
        # ID should be converted to key, with the full chain (topologically sorted)
        self.assertEqual(flag_property["key"], "flag-b")
        self.assertIn("dependency_chain", flag_property)
        self.assertEqual(flag_property["dependency_chain"], ["flag-a", "flag-b"])

        flag_b_data = self._find_flag(flags, "flag-b")
        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_property_b = next(prop for prop in properties_b if prop["type"] == "flag")
        self.assertEqual(flag_property_b["dependency_chain"], ["flag-a"])

    def test_circular_dependency(self):
        """A <-> B cycle yields empty dependency chains."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        flag_a.filters = {
            "groups": [
                {
                    "properties": [
                        {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                    ],
                    "rollout_percentage": 100,
                }
            ]
        }
        flag_a.save()

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]
        self.assertEqual(len(flags), 2)

        flag_a_data = self._find_flag(flags, "flag-a")
        flag_b_data = self._find_flag(flags, "flag-b")

        properties_a = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties_a = [prop for prop in properties_a if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_a), 1)
        self.assertEqual(flag_properties_a[0]["dependency_chain"], [])

        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_properties_b = [prop for prop in properties_b if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_b), 1)
        self.assertEqual(flag_properties_b[0]["dependency_chain"], [])

    def test_multiple_and_transitive_dependencies(self):
        """C depends on A and B; D depends on C (transitive chain A,B,C)."""
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        flag_c = FeatureFlag.objects.create(
            team=self.team,
            key="flag-c",
            name="Flag C",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-d",
            name="Flag D",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_c.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "country", "type": "person", "value": "US", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        flag_c_data = self._find_flag(flags, "flag-c")
        properties = flag_c_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 2)
        self.assertEqual({prop["key"] for prop in flag_properties}, {"flag-a", "flag-b"})
        for prop in flag_properties:
            self.assertIn("dependency_chain", prop)
            if prop["key"] == "flag-a":
                self.assertEqual(prop["dependency_chain"], ["flag-a"])
            elif prop["key"] == "flag-b":
                self.assertEqual(prop["dependency_chain"], ["flag-b"])

        flag_d_data = self._find_flag(flags, "flag-d")
        properties_d = flag_d_data["filters"]["groups"][0]["properties"]
        flag_properties_d = [prop for prop in properties_d if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_d), 1)
        self.assertEqual(flag_properties_d[0]["key"], "flag-c")
        self.assertEqual(flag_properties_d[0]["dependency_chain"], ["flag-a", "flag-b", "flag-c"])

    def test_self_dependency(self):
        """A flag referencing itself yields an empty dependency chain."""
        FeatureFlag.objects.create(
            team=self.team,
            key="self-flag",
            name="Self Flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "self-flag", "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        self_flag_data = self._find_flag(flags, "self-flag")
        properties = self_flag_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 1)
        self.assertEqual(flag_properties[0]["key"], "self-flag")
        self.assertEqual(flag_properties[0]["dependency_chain"], [])

    def test_self_referencing_circular_dependency(self):
        """A -> B where B references itself: both chains empty."""
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "flag-b", "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        flag_b_data = self._find_flag(flags, "flag-b")
        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_properties_b = [prop for prop in properties_b if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_b), 1)
        self.assertEqual(flag_properties_b[0]["key"], "flag-b")
        self.assertEqual(flag_properties_b[0]["dependency_chain"], [])

        flag_a_data = self._find_flag(flags, "flag-a")
        properties_a = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties_a = [prop for prop in properties_a if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_a), 1)
        self.assertEqual(flag_properties_a[0]["key"], "flag-b")
        self.assertEqual(flag_properties_a[0]["dependency_chain"], [])

    def test_missing_dependency(self):
        """A reference to a non-existent flag id keeps the id and yields an empty chain."""
        non_existent_flag_id = "999999"
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": non_existent_flag_id,
                                "type": "flag",
                                "value": True,
                                "operator": "flag_evaluates_to",
                            },
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        flag_a_data = self._find_flag(flags, "flag-a")
        properties = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 1)
        self.assertEqual(flag_properties[0]["key"], non_existent_flag_id)
        self.assertEqual(flag_properties[0]["dependency_chain"], [])

    def test_shared_dependencies(self):
        """Multiple flags depending on the same shared flag each get the same chain."""
        shared_flag = FeatureFlag.objects.create(
            team=self.team,
            key="shared-dependency",
            name="Shared Dependency",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        dependent_flags = []
        for i in range(5):
            flag = FeatureFlag.objects.create(
                team=self.team,
                key=f"dependent-flag-{i}",
                name=f"Dependent Flag {i}",
                filters={
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": str(shared_flag.id),
                                    "type": "flag",
                                    "value": True,
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            )
            dependent_flags.append(flag)

        response = _get_flags_response_for_local_evaluation(self.team)
        flags = response["flags"]

        for i, _flag in enumerate(dependent_flags):
            flag_data = self._find_flag(flags, f"dependent-flag-{i}")
            properties = flag_data["filters"]["groups"][0]["properties"]
            flag_properties = [prop for prop in properties if prop["type"] == "flag"]
            self.assertEqual(len(flag_properties), 1)
            self.assertEqual(flag_properties[0]["key"], "shared-dependency")
            self.assertEqual(flag_properties[0]["dependency_chain"], ["shared-dependency"])
