from posthog.models.person import Person
from posthog.test.base import BaseTest
from products.feature_flags.backend.models.feature_flag import FeatureFlag, FeatureFlagHashKeyOverride
from products.feature_flags.backend.tasks import cleanup_stale_hash_key_overrides_task

class TestCleanupStaleHashKeyOverrides(BaseTest):
    def test_cleanup_stale_hash_key_overrides(self):
        # Create an active flag and a deleted flag
        active_flag = FeatureFlag.objects.create(team=self.team, key="active-flag", created_by=self.user)
        deleted_flag = FeatureFlag.objects.create(
            team=self.team, key="deleted-flag", deleted=True, created_by=self.user
        )

        person = Person.objects.create(team=self.team, distinct_ids=["user1"])

        # Override for active flag
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=person, feature_flag_key="active-flag", hash_key="override-1"
        )

        # Override for deleted flag
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=person, feature_flag_key="deleted-flag", hash_key="override-2"
        )

        # Override for a flag that never existed
        FeatureFlagHashKeyOverride.objects.create(
            team=self.team, person=person, feature_flag_key="non-existent-flag", hash_key="override-3"
        )

        self.assertEqual(FeatureFlagHashKeyOverride.objects.filter(team=self.team).count(), 3)

        # Run cleanup
        cleanup_stale_hash_key_overrides_task()

        # Verify only the active flag override remains
        overrides = FeatureFlagHashKeyOverride.objects.filter(team=self.team)
        self.assertEqual(overrides.count(), 1)
        self.assertEqual(overrides.first().feature_flag_key, "active-flag")
