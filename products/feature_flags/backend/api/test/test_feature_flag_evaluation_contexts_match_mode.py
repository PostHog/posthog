from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagEvaluationContextsMatchMode(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_url = f"/api/projects/{self.team.id}/feature_flags/"

        # Gate the evaluation-contexts feature on by default; individual tests flip it off.
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def test_default_match_mode_is_any(self):
        response = self.client.post(
            self.feature_flag_url,
            {"key": "default-mode", "name": "Default mode"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_contexts_match_mode"], "any")
        flag = FeatureFlag.objects.get(key="default-mode", team=self.team)
        self.assertEqual(flag.evaluation_contexts_match_mode, "any")

    def test_create_flag_with_all_match_mode_when_gated(self):
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "all-mode",
                "name": "All mode",
                "evaluation_contexts": ["app", "docs"],
                "evaluation_contexts_match_mode": "all",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_contexts_match_mode"], "all")
        flag = FeatureFlag.objects.get(key="all-mode", team=self.team)
        self.assertEqual(flag.evaluation_contexts_match_mode, "all")

    def test_create_flag_with_all_match_mode_and_few_contexts(self):
        # "all" is accepted even with 0-1 contexts (harmless at runtime, avoids PATCH ordering issues).
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "all-mode-no-contexts",
                "name": "All mode no contexts",
                "evaluation_contexts_match_mode": "all",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="all-mode-no-contexts", team=self.team)
        self.assertEqual(flag.evaluation_contexts_match_mode, "all")

    def test_create_flag_with_invalid_match_mode_rejected(self):
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "bad-mode",
                "name": "Bad mode",
                "evaluation_contexts_match_mode": "sometimes",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_flag_match_mode_ignored_when_not_gated(self):
        self.mock_feature_enabled.return_value = False
        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "ungated-mode",
                "name": "Ungated mode",
                "evaluation_contexts_match_mode": "all",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="ungated-mode", team=self.team)
        # The mode write is gated; the column stays at its "any" default.
        self.assertEqual(flag.evaluation_contexts_match_mode, "any")
        # And the representation is scrubbed back to "any".
        self.assertEqual(response.json()["evaluation_contexts_match_mode"], "any")

    def test_update_match_mode_when_gated(self):
        flag = FeatureFlag.objects.create(team=self.team, key="update-mode", created_by=self.user)
        response = self.client.patch(
            f"{self.feature_flag_url}{flag.id}/",
            {"evaluation_contexts_match_mode": "all"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertEqual(flag.evaluation_contexts_match_mode, "all")

    def test_update_match_mode_ignored_when_not_gated(self):
        flag = FeatureFlag.objects.create(
            team=self.team, key="update-mode-ungated", created_by=self.user, evaluation_contexts_match_mode="any"
        )
        self.mock_feature_enabled.return_value = False
        response = self.client.patch(
            f"{self.feature_flag_url}{flag.id}/",
            {"evaluation_contexts_match_mode": "all"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertEqual(flag.evaluation_contexts_match_mode, "any")

    def test_match_mode_change_is_logged(self):
        flag = FeatureFlag.objects.create(team=self.team, key="logged-mode", created_by=self.user)
        self.client.patch(
            f"{self.feature_flag_url}{flag.id}/",
            {"evaluation_contexts_match_mode": "all"},
            format="json",
        )
        logs = ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(flag.id), activity="updated")
        mode_changes = [
            change
            for log in logs
            for change in (log.detail or {}).get("changes", [])
            if change.get("field") == "evaluation_contexts_match_mode"
        ]
        self.assertTrue(mode_changes, "Expected an activity log change for evaluation_contexts_match_mode")
        self.assertEqual(mode_changes[-1]["after"], "all")
