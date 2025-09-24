from posthog.test.base import APIBaseTest

from rest_framework import status

from products.llm_analytics.backend.models import TraceReview


class TestTraceReviewViewSet(APIBaseTest):
    def test_mark_trace_as_reviewed(self):
        """Test marking a trace as reviewed"""
        trace_id = "test-trace-123"

        # Mark trace as reviewed
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["trace_id"], trace_id)
        self.assertEqual(response.json()["reviewed_by"]["id"], self.user.id)

        # Verify the review was created in the database
        review = TraceReview.objects.get(team=self.team, trace_id=trace_id)
        self.assertEqual(review.reviewed_by, self.user)
        self.assertEqual(review.trace_id, trace_id)

    def test_mark_trace_as_reviewed_duplicate(self):
        """Test that marking the same trace as reviewed twice returns conflict"""
        trace_id = "test-trace-123"

        # Mark trace as reviewed first time
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Try to mark the same trace as reviewed again
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already been reviewed", response.json()["detail"])

    def test_get_trace_review_by_trace_id(self):
        """Test getting review status for a specific trace"""
        trace_id = "test-trace-123"

        # First, mark trace as reviewed
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Get review status
        response = self.client.get(f"/api/environments/{self.team.id}/trace_reviews/by-trace/{trace_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["trace_id"], trace_id)
        self.assertEqual(response.json()["reviewed_by"]["id"], self.user.id)

    def test_get_trace_review_not_found(self):
        """Test getting review status for a trace that hasn't been reviewed"""
        trace_id = "non-existent-trace"

        response = self.client.get(f"/api/environments/{self.team.id}/trace_reviews/by-trace/{trace_id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.json()["detail"])

    def test_delete_trace_review(self):
        """Test removing review status from a trace"""
        trace_id = "test-trace-123"

        # First, mark trace as reviewed
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Remove review status
        response = self.client.delete(f"/api/environments/{self.team.id}/trace_reviews/by-trace/{trace_id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify the review was deleted
        self.assertFalse(TraceReview.objects.filter(team=self.team, trace_id=trace_id).exists())

    def test_delete_trace_review_not_found(self):
        """Test removing review status from a trace that hasn't been reviewed"""
        trace_id = "non-existent-trace"

        response = self.client.delete(f"/api/environments/{self.team.id}/trace_reviews/by-trace/{trace_id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("not found", response.json()["detail"])

    def test_trace_review_isolated_by_team(self):
        """Test that trace reviews are isolated by team"""
        trace_id = "test-trace-123"

        # Create another team and user
        from posthog.models import Organization, Team, User

        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_user(email="other@test.com", password="test123")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Mark trace as reviewed in first team
        response = self.client.post(f"/api/environments/{self.team.id}/trace_reviews/", data={"trace_id": trace_id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Try to get review from other team - should not find it
        self.client.force_authenticate(user=other_user)
        response = self.client.get(f"/api/environments/{other_team.id}/trace_reviews/by-trace/{trace_id}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
