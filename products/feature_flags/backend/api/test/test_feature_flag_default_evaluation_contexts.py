from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.feature_flags.backend.models.evaluation_context import (
    EvaluationContext,
    FeatureFlagEvaluationContext,
    TeamDefaultEvaluationContext,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagDefaultEnvironments(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_url = "/api/projects/@current/feature_flags/"

        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def _create_default_context(self, name: str) -> TeamDefaultEvaluationContext:
        ctx, _ = EvaluationContext.objects.get_or_create(name=name, team=self.team)
        default, _ = TeamDefaultEvaluationContext.objects.get_or_create(team=self.team, evaluation_context=ctx)
        return default

    def test_create_flag_without_default_contexts(self):
        self.team.default_evaluation_contexts_enabled = False
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag", "name": "Test Flag"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_default_contexts_enabled(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag-with-defaults", "name": "Test Flag with Defaults"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-with-defaults", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_explicit_tags_overrides(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit",
                "name": "Test Flag with Explicit Tags",
                "tags": ["custom-tag"],
                "evaluation_contexts": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit", team=self.team)
        eval_context_names = set(flag.flag_evaluation_contexts.values_list("evaluation_context__name", flat=True))
        self.assertEqual(eval_context_names, {"custom-tag"})

    def test_create_flag_with_explicit_tags_only(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit-only",
                "name": "Test Flag with Explicit Tags Only",
                "tags": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit-only", team=self.team)
        tag_names = set(flag.tagged_items.values_list("tag__name", flat=True))
        self.assertEqual(tag_names, {"custom-tag"})
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_empty_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-empty",
                "name": "Test Flag with Empty Eval Contexts",
                "evaluation_contexts": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-empty", team=self.team)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_update_flag_doesnt_apply_defaults(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        flag = FeatureFlag.objects.create(
            key="existing-flag",
            name="Existing Flag",
            team=self.team,
            created_by=self.user,
        )

        self._create_default_context("production")

        response = self.client.patch(
            f"/api/projects/@current/feature_flags/{flag.id}/",
            {"name": "Updated Name"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

    def test_create_flag_with_none_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-none-eval",
                "name": "Test Flag with None Eval Contexts",
                "evaluation_contexts": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_flag_with_explicit_evaluation_contexts(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        self._create_default_context("production")
        self._create_default_context("staging")

        response = self.client.post(
            self.feature_flag_url,
            {
                "key": "test-flag-explicit-eval",
                "name": "Test Flag with Explicit Eval Contexts",
                "tags": ["custom-tag", "production"],
                "evaluation_contexts": ["custom-tag"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-explicit-eval", team=self.team)
        eval_context_names = set(flag.flag_evaluation_contexts.values_list("evaluation_context__name", flat=True))
        self.assertEqual(eval_context_names, {"custom-tag"})

    def test_no_default_contexts_configured(self):
        self.team.default_evaluation_contexts_enabled = True
        self.team.save()

        response = self.client.post(
            self.feature_flag_url,
            {"key": "test-flag-no-defaults", "name": "Test Flag No Defaults"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="test-flag-no-defaults", team=self.team)
        self.assertEqual(flag.tagged_items.count(), 0)
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)


class TestEvaluationContextSuggestions(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = "/api/environments/@current/evaluation_context_suggestions/"
        self.get_url = "/api/environments/@current/default_evaluation_contexts/"

    def _create_context(self, name: str) -> EvaluationContext:
        ctx, _ = EvaluationContext.objects.get_or_create(name=name, team=self.team)
        return ctx

    def test_hide_context_removes_it_from_suggestions(self):
        self._create_context("production")
        self._create_context("staging")

        response = self.client.post(self.url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True, "name": "production", "hidden_from_suggestions": True})

        data = self.client.get(self.get_url).json()
        self.assertEqual(data["available_contexts"], ["staging"])
        self.assertEqual(data["hidden_contexts"], ["production"])

    def test_restore_hidden_context(self):
        ctx = self._create_context("production")
        ctx.hidden_from_suggestions = True
        ctx.save()

        response = self.client.delete(self.url + "?context_name=production")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True, "name": "production", "hidden_from_suggestions": False})

        ctx.refresh_from_db()
        self.assertFalse(ctx.hidden_from_suggestions)

        data = self.client.get(self.get_url).json()
        self.assertEqual(data["available_contexts"], ["production"])
        self.assertEqual(data["hidden_contexts"], [])

    def test_hiding_preserves_row_and_flag_links(self):
        ctx = self._create_context("production")
        flag = FeatureFlag.objects.create(key="my-flag", name="My Flag", team=self.team, created_by=self.user)
        link = FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        response = self.client.post(self.url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(EvaluationContext.objects.filter(id=ctx.id).exists())
        self.assertTrue(FeatureFlagEvaluationContext.objects.filter(id=link.id).exists())
        ctx.refresh_from_db()
        self.assertTrue(ctx.hidden_from_suggestions)

    def test_hide_normalizes_name(self):
        self._create_context("production")

        response = self.client.post(self.url, {"context_name": "  PRODUCTION  "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(EvaluationContext.objects.get(name="production", team=self.team).hidden_from_suggestions)

    def test_hide_nonexistent_context_returns_404(self):
        response = self.client.post(self.url, {"context_name": "ghost"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_hide_requires_context_name(self):
        response = self.client.post(self.url, {"context_name": "   "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_hide_context_from_another_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        EvaluationContext.objects.create(name="secret", team=other_team)

        response = self.client.post(self.url, {"context_name": "secret"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(EvaluationContext.objects.get(name="secret", team=other_team).hidden_from_suggestions)

    def test_hide_is_idempotent(self):
        self._create_context("production")

        with patch("posthog.api.team.report_user_action") as mock_report:
            self.client.post(self.url, {"context_name": "production"}, format="json")
            self.assertEqual(mock_report.call_count, 1)

            response = self.client.post(self.url, {"context_name": "production"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(mock_report.call_count, 1)

    def test_restore_is_idempotent(self):
        ctx = self._create_context("production")
        ctx.hidden_from_suggestions = True
        ctx.save()

        with patch("posthog.api.team.report_user_action") as mock_report:
            response = self.client.delete(self.url + "?context_name=production")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(mock_report.call_count, 1)

            response = self.client.delete(self.url + "?context_name=production")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(mock_report.call_count, 1)

    def test_member_cannot_write_evaluation_context_suggestions(self):
        self._create_context("production")
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        ctx = self._create_context("staging")
        ctx.hidden_from_suggestions = True
        ctx.save()
        response = self.client.delete(self.url + "?context_name=staging")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_read_default_evaluation_contexts(self):
        self._create_context("production")
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.get_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_adding_hidden_context_as_default_unhides_it(self):
        ctx = self._create_context("production")
        ctx.hidden_from_suggestions = True
        ctx.save()

        response = self.client.post(self.get_url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["created"])

        ctx.refresh_from_db()
        self.assertFalse(ctx.hidden_from_suggestions)

        data = self.client.get(self.get_url).json()
        self.assertIn("production", data["available_contexts"])
        self.assertNotIn("production", data["hidden_contexts"])

    def test_member_adding_hidden_context_as_default_does_not_unhide_it(self):
        ctx = self._create_context("production")
        ctx.hidden_from_suggestions = True
        ctx.save()

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.get_url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["created"])

        ctx.refresh_from_db()
        self.assertTrue(ctx.hidden_from_suggestions)

        data = self.client.get(self.get_url).json()
        self.assertNotIn("production", data["available_contexts"])
        self.assertIn("production", data["hidden_contexts"])

    def test_member_can_post_but_not_delete_default_evaluation_contexts(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.get_url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.delete(self.get_url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestEvaluationContextRootTeamScoping(APIBaseTest):
    """Flags persist contexts under the project root team, so contexts must be visible and
    manageable from any child environment of the same project — not just the root."""

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        # self.team is the project root (no parent_team); add a sibling child environment.
        self.child_env = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="child-env",
        )
        self.get_url = f"/api/environments/{self.child_env.id}/default_evaluation_contexts/"
        self.suggestions_url = f"/api/environments/{self.child_env.id}/evaluation_context_suggestions/"

    @parameterized.expand(
        [
            ("visible", False, "available_contexts"),
            ("hidden", True, "hidden_contexts"),
        ]
    )
    def test_root_team_context_visible_from_child_environment(self, _name, hidden, bucket):
        EvaluationContext.objects.create(name="production", team=self.team, hidden_from_suggestions=hidden)

        data = self.client.get(self.get_url).json()
        self.assertEqual(data[bucket], ["production"])

    def test_hide_and_restore_root_team_context_from_child_environment(self):
        ctx = EvaluationContext.objects.create(name="production", team=self.team)

        hide = self.client.post(self.suggestions_url, {"context_name": "production"}, format="json")
        self.assertEqual(hide.status_code, status.HTTP_200_OK)
        ctx.refresh_from_db()
        self.assertTrue(ctx.hidden_from_suggestions)

        restore = self.client.delete(self.suggestions_url + "?context_name=production")
        self.assertEqual(restore.status_code, status.HTTP_200_OK)
        ctx.refresh_from_db()
        self.assertFalse(ctx.hidden_from_suggestions)

    def test_adding_default_from_child_environment_persists_under_root_team(self):
        response = self.client.post(self.get_url, {"context_name": "production"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(EvaluationContext.objects.filter(name="production", team=self.team).exists())
        self.assertFalse(EvaluationContext.objects.filter(name="production", team=self.child_env).exists())
