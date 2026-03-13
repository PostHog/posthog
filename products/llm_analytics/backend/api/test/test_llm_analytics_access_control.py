import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.llm_analytics.backend.models.datasets import Dataset
from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey
from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.llm_analytics.backend.models.trace_reviews import TraceReview

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestLLMAnalyticsAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.llm_analytics.backend.api.score_definitions.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)
        self.trace_review_feature_flag_patcher = patch(
            "products.llm_analytics.backend.api.trace_reviews.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.trace_review_feature_flag_patcher.start()
        self.addCleanup(self.trace_review_feature_flag_patcher.stop)

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Evaluation",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Test prompt"},
            output_type="boolean",
            output_config={},
            created_by=self.user,
        )

        self.dataset = Dataset.objects.create(
            team=self.team,
            name="Test Dataset",
            created_by=self.user,
        )

        self.provider_key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Test Key",
            encrypted_config={"api_key": "sk-test123"},
            state=LLMProviderKey.State.OK,
            created_by=self.user,
        )

        self.trace_review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_123",
            created_by=self.user,
            reviewed_by=self.user,
        )
        self.review_queue = ReviewQueue.objects.create(
            team=self.team,
            name="Support queue",
            created_by=self.user,
        )
        self.review_queue_item = ReviewQueueItem.objects.create(
            team=self.team,
            queue=self.review_queue,
            trace_id="trace_pending",
            created_by=self.user,
        )

    def _set_access_level(self, user: User, resource: str = "llm_analytics", access_level: str = "viewer") -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    # -- Viewer can list/retrieve --

    @parameterized.expand(
        [
            ("evaluations", "evaluation"),
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_viewer_can_list(self, endpoint, _attr):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("evaluations", "evaluation"),
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_viewer_can_retrieve(self, endpoint, attr):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        obj = getattr(self, attr)
        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/{obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_score_definitions(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/score_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_trace_reviews(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_review_queues(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/review_queues/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_review_queue_items(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -- Viewer cannot create/update/delete --

    def test_viewer_cannot_create_evaluation(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "New Evaluation",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_dataset(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "New Dataset"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_evaluation(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{self.evaluation.id}/",
            {"name": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_provider_key(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_score_definition(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/score_definitions/",
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {"options": [{"key": "good", "label": "Good"}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/",
            {"trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
            {"comment": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/",
            {"name": "New queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
            {"name": "Renamed queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/",
            {"queue_id": str(self.review_queue.id), "trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        alternate_queue = ReviewQueue.objects.create(team=self.team, name="Bug bash", created_by=self.user)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
            {"queue_id": str(alternate_queue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Editor can create/update/delete --

    def test_editor_can_create_evaluation(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Editor Evaluation",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_create_dataset(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Editor Dataset"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_evaluation(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/evaluations/{self.evaluation.id}/",
            {"name": "Updated by editor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_provider_key(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_score_definition(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/score_definitions/",
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {"options": [{"key": "good", "label": "Good"}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_create_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/",
            {"trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
            {"comment": "Updated by editor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/",
            {"name": "Escalations"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
            {"name": "Renamed queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/",
            {"queue_id": str(self.review_queue.id), "trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        alternate_queue = ReviewQueue.objects.create(team=self.team, name="Bug bash", created_by=self.user)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
            {"queue_id": str(alternate_queue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # -- None access blocks everything --

    @parameterized.expand(
        [
            ("evaluations",),
            ("datasets",),
            ("llm_analytics/provider_keys",),
            ("llm_analytics/review_queues",),
            ("llm_analytics/review_queue_items",),
        ]
    )
    def test_none_access_blocks_list(self, endpoint):
        self._set_access_level(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Resource inheritance: setting llm_analytics cascades to child resources --

    @parameterized.expand(
        [
            ("evaluations", "evaluation"),
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_llm_analytics_viewer_can_list_child_resources(self, endpoint, _attr):
        self._set_access_level(self.viewer_user, resource="llm_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("evaluations", "evaluation"),
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_llm_analytics_none_blocks_child_resource_list(self, endpoint, _attr):
        self._set_access_level(self.no_access_user, resource="llm_analytics", access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Org admin has full access without explicit permissions --

    def test_org_admin_has_full_access(self):
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Admin Evaluation",
                "evaluation_type": "llm_judge",
                "evaluation_config": {"prompt": "prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
