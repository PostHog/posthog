from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.llm_analytics.backend.models.trace_reviews import TraceReview


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
        self.assertIsNone(review.score_kind)
        self.assertIsNone(review.score_label)
        self.assertIsNone(review.score_numeric)
        self.assertIsNone(review.comment)

    @parameterized.expand(
        [
            ("good",),
            ("bad",),
        ]
    )
    def test_can_create_label_review(self, label: str):
        response = self.client.post(
            self._endpoint(),
            {"trace_id": "trace_label", "score_kind": "label", "score_label": label, "comment": "Looks good"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = TraceReview.objects.get(trace_id="trace_label", team=self.team, deleted=False)
        self.assertEqual(review.score_kind, "label")
        self.assertEqual(review.score_label, label)
        self.assertEqual(review.comment, "Looks good")

    def test_can_create_numeric_review(self):
        response = self.client.post(
            self._endpoint(),
            {"trace_id": "trace_numeric", "score_kind": "numeric", "score_numeric": "7.500"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = TraceReview.objects.get(trace_id="trace_numeric", team=self.team, deleted=False)
        self.assertEqual(review.score_kind, "numeric")
        self.assertEqual(str(review.score_numeric), "7.500")

    @parameterized.expand(
        [
            ("missing_label", {"trace_id": "trace_1", "score_kind": "label"}, "score_label"),
            ("missing_numeric", {"trace_id": "trace_1", "score_kind": "numeric"}, "score_numeric"),
            (
                "mixed_score_fields",
                {
                    "trace_id": "trace_1",
                    "score_kind": "label",
                    "score_label": "good",
                    "score_numeric": "1.000",
                },
                "score_numeric",
            ),
            ("score_without_kind", {"trace_id": "trace_1", "score_label": "good"}, "score_kind"),
        ]
    )
    def test_score_validation(self, _name: str, payload: dict, field: str):
        response = self.client.post(self._endpoint(), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(field, response.data)

    def test_duplicate_active_review_is_rejected(self):
        TraceReview.objects.create(team=self.team, trace_id="trace_123", created_by=self.user, reviewed_by=self.user)

        response = self.client.post(self._endpoint(), {"trace_id": "trace_123"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("trace_id", response.data)

    def test_can_list_reviews_filtered_by_trace_id(self):
        TraceReview.objects.create(team=self.team, trace_id="trace_a", created_by=self.user, reviewed_by=self.user)
        TraceReview.objects.create(team=self.team, trace_id="trace_b", created_by=self.user, reviewed_by=self.user)

        response = self.client.get(self._endpoint(), {"trace_id": "trace_b"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["trace_id"], "trace_b")

    def test_can_list_reviews_filtered_by_trace_id_in(self):
        TraceReview.objects.create(team=self.team, trace_id="trace_a", created_by=self.user, reviewed_by=self.user)
        TraceReview.objects.create(team=self.team, trace_id="trace_b", created_by=self.user, reviewed_by=self.user)
        TraceReview.objects.create(team=self.team, trace_id="trace_c", created_by=self.user, reviewed_by=self.user)

        response = self.client.get(self._endpoint(), {"trace_id__in": "trace_a,trace_c"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_trace_ids = {review["trace_id"] for review in response.data["results"]}
        self.assertEqual(returned_trace_ids, {"trace_a", "trace_c"})

    def test_search_matches_trace_id_and_comment(self):
        TraceReview.objects.create(
            team=self.team,
            trace_id="trace_hallucination",
            comment="Potential hallucination",
            created_by=self.user,
            reviewed_by=self.user,
        )
        TraceReview.objects.create(team=self.team, trace_id="trace_other", created_by=self.user, reviewed_by=self.user)

        response = self.client.get(self._endpoint(), {"search": "hallucination"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["trace_id"], "trace_hallucination")

    def test_patch_updates_reviewed_by(self):
        review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_update",
            comment="Original",
            created_by=self.user,
            reviewed_by=self.user,
        )
        another_user = self._create_user("reviewer@example.com")
        self.client.force_login(another_user)

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"comment": "Updated comment"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.comment, "Updated comment")
        self.assertEqual(review.reviewed_by, another_user)

    def test_patch_rejects_conflicting_score_fields(self):
        review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_invalid_patch",
            created_by=self.user,
            reviewed_by=self.user,
        )

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"score_kind": "label", "score_label": "good", "score_numeric": "1.000"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("score_numeric", response.data)

    def test_patch_can_clear_a_score_by_only_setting_score_kind_to_null(self):
        review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_clear_score",
            score_kind=TraceReview.ScoreKind.LABEL,
            score_label=TraceReview.ScoreLabel.GOOD,
            created_by=self.user,
            reviewed_by=self.user,
        )

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            {"score_kind": None},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertIsNone(review.score_kind)
        self.assertIsNone(review.score_label)
        self.assertIsNone(review.score_numeric)

    @parameterized.expand(
        [
            (
                "label_to_numeric",
                {
                    "score_kind": TraceReview.ScoreKind.NUMERIC,
                    "score_numeric": "4.250",
                },
                TraceReview.ScoreKind.NUMERIC,
                None,
                "4.250",
            ),
            (
                "numeric_to_label",
                {
                    "score_kind": TraceReview.ScoreKind.LABEL,
                    "score_label": TraceReview.ScoreLabel.BAD,
                },
                TraceReview.ScoreKind.LABEL,
                TraceReview.ScoreLabel.BAD,
                None,
            ),
        ]
    )
    def test_patch_can_switch_score_modes_without_clearing_the_previous_mode_explicitly(
        self,
        _name: str,
        payload: dict,
        expected_kind: str,
        expected_label: str | None,
        expected_numeric: str | None,
    ):
        review = TraceReview.objects.create(
            team=self.team,
            trace_id=f"trace_switch_{_name}",
            score_kind=TraceReview.ScoreKind.LABEL,
            score_label=TraceReview.ScoreLabel.GOOD,
            created_by=self.user,
            reviewed_by=self.user,
        )

        if _name == "numeric_to_label":
            review.score_kind = TraceReview.ScoreKind.NUMERIC
            review.score_label = None
            review.score_numeric = "2.000"
            review.save(update_fields=["score_kind", "score_label", "score_numeric"])

        response = self.client.patch(
            f"{self._endpoint()}{review.id}/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        review.refresh_from_db()
        self.assertEqual(review.score_kind, expected_kind)
        self.assertEqual(review.score_label, expected_label)
        self.assertEqual(str(review.score_numeric) if review.score_numeric is not None else None, expected_numeric)

    def test_delete_soft_deletes_review_and_allows_recreate(self):
        review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_soft_delete",
            created_by=self.user,
            reviewed_by=self.user,
        )

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
