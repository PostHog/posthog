from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.llm_analytics.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.llm_analytics.backend.models.score_definitions import ScoreDefinition, ScoreDefinitionVersion
from products.llm_analytics.backend.models.trace_reviews import TraceReview, TraceReviewScore


class TestTraceReviewsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feature_flag_patcher = patch(
            "products.llm_analytics.backend.api.trace_reviews.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.addCleanup(self.feature_flag_patcher.stop)

    def _endpoint(self) -> str:
        return f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/"

    def _create_definition(
        self,
        *,
        name: str = "Quality",
        kind: str = "categorical",
        config: dict | None = None,
        archived: bool = False,
    ) -> ScoreDefinition:
        definition = ScoreDefinition.objects.create(
            team=self.team,
            name=name,
            description="",
            kind=kind,
            archived=archived,
            created_by=self.user,
        )
        definition.create_new_version(
            config=config
            or {
                "options": [
                    {"key": "good", "label": "Good"},
                    {"key": "bad", "label": "Bad"},
                ]
            },
            created_by=self.user,
        )
        return definition

    def _current_version(self, definition: ScoreDefinition) -> ScoreDefinitionVersion:
        current_version = definition.current_version
        assert current_version is not None
        return current_version

    def _create_multi_select_definition(
        self,
        *,
        name: str = "Themes",
        minimum_selections: int | None = None,
        maximum_selections: int | None = None,
    ) -> ScoreDefinition:
        config: dict = {
            "options": [
                {"key": "helpful", "label": "Helpful"},
                {"key": "accurate", "label": "Accurate"},
                {"key": "complete", "label": "Complete"},
            ],
            "selection_mode": "multiple",
        }

        if minimum_selections is not None:
            config["min_selections"] = minimum_selections

        if maximum_selections is not None:
            config["max_selections"] = maximum_selections

        return self._create_definition(name=name, config=config)

    def _create_review(self, *, trace_id: str, comment: str | None = None) -> TraceReview:
        return TraceReview.objects.create(
            team=self.team,
            trace_id=trace_id,
            comment=comment,
            created_by=self.user,
            reviewed_by=self.user,
        )

    def _create_queue(self, *, name: str = "Support queue") -> ReviewQueue:
        return ReviewQueue.objects.create(team=self.team, name=name, created_by=self.user)

    def _create_queue_item(self, *, queue: ReviewQueue, trace_id: str = "trace_123") -> ReviewQueueItem:
        return ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id=trace_id, created_by=self.user)

    def test_returns_403_when_feature_flag_disabled(self):
        self.mock_feature_enabled.return_value = False

        response = self.client.get(self._endpoint())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_can_create_review_without_score_or_comment(self):
        response = self.client.post(self._endpoint(), {"trace_id": "trace_123"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = TraceReview.objects.get(trace_id="trace_123", team=self.team, deleted=False)
        self.assertEqual(review.created_by, self.user)
        self.assertEqual(review.reviewed_by, self.user)
        self.assertIsNone(review.comment)
        self.assertEqual(review.scores.count(), 0)

    def test_creating_review_soft_deletes_pending_queue_item_without_queue_context(self):
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_123")

        response = self.client.post(self._endpoint(), {"trace_id": "trace_123"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item.refresh_from_db()
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_creating_review_soft_deletes_matching_pending_queue_item_with_queue_context(self):
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_123")

        response = self.client.post(
            self._endpoint(),
            {"trace_id": "trace_123", "queue_id": str(queue.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item.refresh_from_db()
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_updating_review_soft_deletes_pending_queue_item_without_queue_context(self):
        review = self._create_review(trace_id="trace_123", comment="Before")
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_123")

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"comment": "After"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_updating_review_soft_deletes_matching_pending_queue_item_with_queue_context(self):
        review = self._create_review(trace_id="trace_123", comment="Before")
        queue = self._create_queue()
        item = self._create_queue_item(queue=queue, trace_id="trace_123")

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"comment": "After", "queue_id": str(queue.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertTrue(item.deleted)
        self.assertIsNotNone(item.deleted_at)

    def test_can_create_review_with_multiple_scores(self):
        themes = self._create_multi_select_definition(minimum_selections=1, maximum_selections=2)
        themes_version = self._current_version(themes)
        resolved = self._create_definition(
            name="Resolved",
            kind="boolean",
            config={"true_label": "Yes", "false_label": "No"},
        )
        confidence = self._create_definition(
            name="Confidence",
            kind="numeric",
            config={"min": 0, "max": 5, "step": 0.5},
        )

        response = self.client.post(
            self._endpoint(),
            {
                "trace_id": "trace_multi",
                "comment": "Needs a follow-up prompt tweak",
                "scores": [
                    {
                        "definition_id": str(themes.id),
                        "categorical_values": ["helpful", "accurate"],
                    },
                    {"definition_id": str(resolved.id), "boolean_value": True},
                    {"definition_id": str(confidence.id), "numeric_value": "4.500000"},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = TraceReview.objects.get(trace_id="trace_multi", team=self.team, deleted=False)
        self.assertEqual(review.comment, "Needs a follow-up prompt tweak")
        self.assertEqual(review.scores.count(), 3)

        themes_score = review.scores.get(definition=themes)
        resolved_score = review.scores.get(definition=resolved)
        confidence_score = review.scores.get(definition=confidence)

        self.assertEqual(themes_score.definition_version, themes_version.id)
        self.assertEqual(themes_score.definition_version_number, themes_version.version)
        self.assertEqual(themes_score.definition_config, themes_version.config)
        self.assertEqual(themes_score.categorical_values, ["helpful", "accurate"])
        self.assertEqual(resolved_score.boolean_value, True)
        self.assertEqual(str(confidence_score.numeric_value), "4.500000")

    def test_can_create_review_with_an_explicit_definition_version(self):
        definition = self._create_definition()
        original_version = self._current_version(definition)
        definition.create_new_version(
            config={
                "options": [
                    {"key": "pass", "label": "Pass"},
                    {"key": "fail", "label": "Fail"},
                ]
            },
            created_by=self.user,
        )
        definition.refresh_from_db(fields=["current_version"])

        response = self.client.post(
            self._endpoint(),
            {
                "trace_id": "trace_versioned",
                "scores": [
                    {
                        "definition_id": str(definition.id),
                        "definition_version_id": str(original_version.id),
                        "categorical_values": ["good"],
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = TraceReview.objects.get(trace_id="trace_versioned", team=self.team, deleted=False)
        self.assertEqual(review.scores.get().definition_version, original_version.id)

    @parameterized.expand(
        [
            (
                "unknown_definition",
                {
                    "trace_id": "trace_invalid",
                    "scores": [{"definition_id": "4dddeebb-3b21-4c15-8ad2-2024a3111111", "boolean_value": True}],
                },
                "definition_id",
            ),
            (
                "duplicate_definition",
                None,
                "definition_id",
            ),
            (
                "categorical_invalid_option",
                None,
                "categorical_values",
            ),
            (
                "categorical_single_rejects_multiple_values",
                None,
                "categorical_values",
            ),
            (
                "categorical_multiple_rejects_too_many_values",
                None,
                "categorical_values",
            ),
            (
                "numeric_out_of_range",
                None,
                "numeric_value",
            ),
            (
                "version_from_another_definition",
                None,
                "definition_version_id",
            ),
        ]
    )
    def test_score_validation(self, name: str, payload: dict | None, field: str):
        quality = self._create_definition()
        themes = self._create_multi_select_definition(maximum_selections=2)
        confidence = self._create_definition(
            name="Confidence",
            kind="numeric",
            config={"min": 0, "max": 5, "step": 0.5},
        )
        resolved = self._create_definition(
            name="Resolved",
            kind="boolean",
            config={"true_label": "Yes", "false_label": "No"},
        )
        resolved_version = self._current_version(resolved)

        if name == "duplicate_definition":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [
                    {"definition_id": str(quality.id), "categorical_values": ["good"]},
                    {"definition_id": str(quality.id), "categorical_values": ["bad"]},
                ],
            }
        elif name == "categorical_invalid_option":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [{"definition_id": str(quality.id), "categorical_values": ["excellent"]}],
            }
        elif name == "categorical_single_rejects_multiple_values":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [{"definition_id": str(quality.id), "categorical_values": ["good", "bad"]}],
            }
        elif name == "categorical_multiple_rejects_too_many_values":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [
                    {
                        "definition_id": str(themes.id),
                        "categorical_values": ["helpful", "accurate", "complete"],
                    }
                ],
            }
        elif name == "numeric_out_of_range":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [{"definition_id": str(confidence.id), "numeric_value": "5.100000"}],
            }
        elif name == "version_from_another_definition":
            payload = {
                "trace_id": "trace_invalid",
                "scores": [
                    {
                        "definition_id": str(quality.id),
                        "definition_version_id": str(resolved_version.id),
                        "categorical_values": ["good"],
                    }
                ],
            }

        response = self.client.post(self._endpoint(), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["type"], "validation_error")
        self.assertEqual(response.data["attr"], "scores")
        self.assertIn(field, str(response.data["detail"]))

    def test_duplicate_active_review_is_rejected(self):
        self._create_review(trace_id="trace_123")

        response = self.client.post(self._endpoint(), {"trace_id": "trace_123"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            self.validation_error_response(
                message="An active review already exists for this trace.",
                attr="trace_id",
            ),
        )

    def test_can_list_reviews_filtered_by_trace_id_in(self):
        self._create_review(trace_id="trace_a")
        self._create_review(trace_id="trace_b")
        self._create_review(trace_id="trace_c")

        response = self.client.get(self._endpoint(), {"trace_id__in": "trace_a,trace_c"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_trace_ids = {review["trace_id"] for review in response.data["results"]}
        self.assertEqual(returned_trace_ids, {"trace_a", "trace_c"})

    def test_can_list_reviews_filtered_by_definition_id(self):
        quality = self._create_definition()
        quality_version = self._current_version(quality)
        resolved = self._create_definition(
            name="Resolved",
            kind="boolean",
            config={"true_label": "Yes", "false_label": "No"},
        )
        resolved_version = self._current_version(resolved)

        reviewed_quality = self._create_review(trace_id="trace_quality")
        TraceReviewScore.objects.create(
            team=self.team,
            review=reviewed_quality,
            definition=quality,
            definition_version=quality_version.id,
            definition_version_number=quality_version.version,
            definition_config=quality_version.config,
            categorical_values=["good"],
            created_by=self.user,
        )

        reviewed_resolved = self._create_review(trace_id="trace_resolved")
        TraceReviewScore.objects.create(
            team=self.team,
            review=reviewed_resolved,
            definition=resolved,
            definition_version=resolved_version.id,
            definition_version_number=resolved_version.version,
            definition_config=resolved_version.config,
            boolean_value=True,
            created_by=self.user,
        )

        response = self.client.get(self._endpoint(), {"definition_id": str(quality.id)})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([review["trace_id"] for review in response.data["results"]], ["trace_quality"])

    def test_search_matches_trace_id_and_comment(self):
        self._create_review(trace_id="trace_hallucination", comment="Potential hallucination")
        self._create_review(trace_id="trace_other")

        response = self.client.get(self._endpoint(), {"search": "hallucination"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["trace_id"], "trace_hallucination")

    def test_patch_replaces_the_full_score_set(self):
        quality = self._create_definition()
        quality_version = self._current_version(quality)
        resolved = self._create_definition(
            name="Resolved",
            kind="boolean",
            config={"true_label": "Yes", "false_label": "No"},
        )
        resolved_version = self._current_version(resolved)
        review = self._create_review(trace_id="trace_patch", comment="Original")
        TraceReviewScore.objects.create(
            team=self.team,
            review=review,
            definition=quality,
            definition_version=quality_version.id,
            definition_version_number=quality_version.version,
            definition_config=quality_version.config,
            categorical_values=["good"],
            created_by=self.user,
        )
        TraceReviewScore.objects.create(
            team=self.team,
            review=review,
            definition=resolved,
            definition_version=resolved_version.id,
            definition_version_number=resolved_version.version,
            definition_config=resolved_version.config,
            boolean_value=True,
            created_by=self.user,
        )

        another_user = self._create_user("reviewer@example.com")
        self.client.force_login(another_user)

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {
                "comment": "Updated comment",
                "scores": [{"definition_id": str(resolved.id), "boolean_value": False}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.comment, "Updated comment")
        self.assertEqual(review.reviewed_by, another_user)
        self.assertEqual(review.scores.count(), 1)
        remaining_score = review.scores.get()
        self.assertEqual(remaining_score.definition, resolved)
        self.assertEqual(remaining_score.boolean_value, False)

    def test_patch_can_clear_all_scores_while_keeping_the_review(self):
        quality = self._create_definition()
        quality_version = self._current_version(quality)
        review = self._create_review(trace_id="trace_clear")
        TraceReviewScore.objects.create(
            team=self.team,
            review=review,
            definition=quality,
            definition_version=quality_version.id,
            definition_version_number=quality_version.version,
            definition_config=quality_version.config,
            categorical_values=["good"],
            created_by=self.user,
        )

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"scores": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.scores.count(), 0)

    def test_delete_soft_deletes_review_and_allows_recreate(self):
        review = self._create_review(trace_id="trace_soft_delete")

        response = self.client.delete(f"{self._endpoint()}{review.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        review.refresh_from_db()
        self.assertTrue(review.deleted)
        self.assertIsNotNone(review.deleted_at)

        list_response = self.client.get(self._endpoint())
        self.assertEqual(len(list_response.data["results"]), 0)

        recreate_response = self.client.post(self._endpoint(), {"trace_id": "trace_soft_delete"}, format="json")
        self.assertEqual(recreate_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TraceReview.objects.filter(team=self.team, trace_id="trace_soft_delete").count(), 2)
