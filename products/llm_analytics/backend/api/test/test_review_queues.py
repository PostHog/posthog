from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import serializers, status

from products.llm_analytics.backend.api.review_queues import ReviewQueueItemCreateSerializer
from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.llm_analytics.backend.models.trace_reviews import TraceReview


class TestReviewQueuesApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.llm_analytics.backend.api.trace_reviews.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)

    def _queues_endpoint(self) -> str:
        return f"/api/environments/{self.team.id}/llm_analytics/review_queues/"

    def _queue_items_endpoint(self) -> str:
        return f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/"

    def _create_queue(self, *, name: str = "Support queue") -> ReviewQueue:
        return ReviewQueue.objects.create(team=self.team, name=name, created_by=self.user)

    def _create_queue_item(self, *, queue: ReviewQueue, trace_id: str = "trace_123") -> ReviewQueueItem:
        return ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id=trace_id, created_by=self.user)

    def _create_review(self, *, trace_id: str) -> TraceReview:
        return TraceReview.objects.create(
            team=self.team,
            trace_id=trace_id,
            created_by=self.user,
            reviewed_by=self.user,
        )

    def test_returns_403_when_feature_flag_disabled(self):
        self.mock_feature_enabled.return_value = False

        response = self.client.get(self._queues_endpoint())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_can_create_review_queue(self):
        response = self.client.post(self._queues_endpoint(), {"name": "Escalations"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        queue = ReviewQueue.objects.get(team=self.team, name="Escalations")
        self.assertEqual(queue.created_by, self.user)

    def test_duplicate_review_queue_name_is_rejected(self):
        self._create_queue(name="Escalations")

        response = self.client.post(self._queues_endpoint(), {"name": "Escalations"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="A queue with this name already exists.",
                attr="name",
            ),
        )

    def test_can_list_queues_filtered_by_search(self):
        self._create_queue(name="Support queue")
        self._create_queue(name="Bug bash")

        response = self.client.get(self._queues_endpoint(), {"search": "support"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([queue["name"] for queue in response.data["results"]], ["Support queue"])

    def test_soft_deleted_queue_is_excluded_from_active_list(self):
        active_queue = self._create_queue(name="Support queue")
        deleted_queue = self._create_queue(name="Bug bash")
        deleted_queue.soft_delete()

        response = self.client.get(self._queues_endpoint())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([queue["id"] for queue in response.data["results"]], [str(active_queue.id)])

    def test_can_add_pending_trace_to_queue(self):
        queue = self._create_queue()

        response = self.client.post(
            self._queue_items_endpoint(),
            {"queue_id": str(queue.id), "trace_id": "trace_pending"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = ReviewQueueItem.objects.get(team=self.team, trace_id="trace_pending")
        self.assertEqual(item.queue, queue)
        self.assertEqual(item.created_by, self.user)

    def test_cannot_add_reviewed_trace_to_queue(self):
        queue = self._create_queue()
        self._create_review(trace_id="trace_reviewed")

        response = self.client.post(
            self._queue_items_endpoint(),
            {"queue_id": str(queue.id), "trace_id": "trace_reviewed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="This trace is already reviewed and cannot be added to a queue.",
                attr="trace_id",
            ),
        )

    def test_save_rechecks_trace_review_created_after_validation(self):
        queue = self._create_queue()
        serializer = ReviewQueueItemCreateSerializer(
            data={"queue_id": str(queue.id), "trace_id": "trace_reviewed"},
            context={"request": SimpleNamespace(user=self.user), "team": self.team},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self._create_review(trace_id="trace_reviewed")

        with self.assertRaises(serializers.ValidationError) as exc:
            serializer.save()

        self.assertEqual(
            exc.exception.detail,
            {"trace_id": "This trace is already reviewed and cannot be added to a queue."},
        )
        self.assertFalse(
            ReviewQueueItem.objects.filter(team=self.team, trace_id="trace_reviewed", deleted=False).exists()
        )

    def test_cannot_add_pending_trace_to_another_queue(self):
        first_queue = self._create_queue(name="First queue")
        second_queue = self._create_queue(name="Second queue")
        self._create_queue_item(queue=first_queue, trace_id="trace_pending")

        response = self.client.post(
            self._queue_items_endpoint(),
            {"queue_id": str(second_queue.id), "trace_id": "trace_pending"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="This trace is already pending in another queue.",
                attr="trace_id",
            ),
        )

    def test_cannot_add_pending_trace_to_same_queue_twice(self):
        queue = self._create_queue()
        self._create_queue_item(queue=queue, trace_id="trace_pending")

        response = self.client.post(
            self._queue_items_endpoint(),
            {"queue_id": str(queue.id), "trace_id": "trace_pending"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="This trace is already pending in this queue.",
                attr="trace_id",
            ),
        )

    def test_can_move_pending_trace_to_another_queue(self):
        first_queue = self._create_queue(name="First queue")
        second_queue = self._create_queue(name="Second queue")
        item = self._create_queue_item(queue=first_queue, trace_id="trace_pending")

        response = self.client.patch(
            f"{self._queue_items_endpoint()}{item.id}/",
            {"queue_id": str(second_queue.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.queue, second_queue)

    def test_patch_queue_item_requires_queue_id(self):
        queue = self._create_queue(name="First queue")
        item = self._create_queue_item(queue=queue, trace_id="trace_pending")

        response = self.client.patch(
            f"{self._queue_items_endpoint()}{item.id}/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="This field is required.",
                code="required",
                attr="queue_id",
            ),
        )

    def test_can_list_queue_items_filtered_by_queue_id_and_trace_ids(self):
        queue = self._create_queue(name="Support queue")
        other_queue = self._create_queue(name="Bug bash")
        self._create_queue_item(queue=queue, trace_id="trace_a")
        self._create_queue_item(queue=queue, trace_id="trace_b")
        self._create_queue_item(queue=other_queue, trace_id="trace_c")

        response = self.client.get(
            self._queue_items_endpoint(),
            {"queue_id": str(queue.id), "trace_id__in": "trace_a,trace_b"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["trace_id"] for item in response.data["results"]], ["trace_a", "trace_b"])

    def test_soft_deleted_queue_item_is_excluded_from_active_list(self):
        queue = self._create_queue()
        active_item = self._create_queue_item(queue=queue, trace_id="trace_active")
        deleted_item = self._create_queue_item(queue=queue, trace_id="trace_deleted")
        deleted_item.soft_delete()

        response = self.client.get(self._queue_items_endpoint())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data["results"]], [str(active_item.id)])

    def test_delete_queue_item_soft_deletes_pending_assignment(self):
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_pending")

        response = self.client.delete(f"{self._queue_items_endpoint()}{item.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        item.refresh_from_db()
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_delete_queue_soft_deletes_queue_and_pending_assignments(self):
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_pending")

        response = self.client.delete(f"{self._queues_endpoint()}{queue.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        queue.refresh_from_db()
        item.refresh_from_db()
        self.assertTrue(queue.deleted)
        self.assertIsNotNone(queue.deleted_at)
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_can_reuse_soft_deleted_queue_name(self):
        queue = self._create_queue(name="Escalations")
        queue.soft_delete()

        response = self.client.post(self._queues_endpoint(), {"name": "Escalations"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_can_requeue_trace_after_soft_deleted_queue_item(self):
        queue = self._create_queue(name="First queue")
        other_queue = self._create_queue(name="Second queue")
        item = self._create_queue_item(queue=queue, trace_id="trace_pending")
        item.soft_delete()

        response = self.client.post(
            self._queue_items_endpoint(),
            {"queue_id": str(other_queue.id), "trace_id": "trace_pending"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
