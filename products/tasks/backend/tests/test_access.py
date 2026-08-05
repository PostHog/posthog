from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.tasks.backend.access import has_tasks_access


class TestHasTasksAccess(SimpleTestCase):
    def setUp(self):
        self.user = MagicMock(distinct_id="user-distinct-id", id=1, organization=None)
        self.user.is_authenticated = True

        self.cache_store: dict[str, bool] = {}
        cache_patcher = patch("products.tasks.backend.access.cache")
        mock_cache = cache_patcher.start()
        mock_cache.get.side_effect = self.cache_store.get
        mock_cache.set.side_effect = lambda key, value, *_args, **_kwargs: self.cache_store.__setitem__(key, value)
        self.addCleanup(cache_patcher.stop)

        redemption_patcher = patch("products.tasks.backend.access.CodeInviteRedemption.objects")
        self.mock_redemption_objects = redemption_patcher.start()
        self.mock_redemption_objects.filter.return_value.exists.return_value = False
        self.addCleanup(redemption_patcher.stop)

    def test_flag_evaluation_error_does_not_deny_a_previously_granted_user(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.assertTrue(has_tasks_access(self.user))

        with patch("posthoganalytics.feature_enabled", return_value=None):
            self.assertTrue(has_tasks_access(self.user))

    def test_flag_evaluation_error_without_prior_grant_falls_back_to_invite_check(self):
        with patch("posthoganalytics.feature_enabled", return_value=None):
            self.assertFalse(has_tasks_access(self.user))
        self.mock_redemption_objects.filter.assert_called_with(user=self.user)

    def test_flag_explicitly_disabled_denies_even_with_a_stale_cached_grant(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.assertTrue(has_tasks_access(self.user))

        with patch("posthoganalytics.feature_enabled", return_value=False):
            self.assertFalse(has_tasks_access(self.user))
