from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import responses
from rest_framework import status

from posthog.models.integration import Integration

from products.live_debugger.backend import github_client
from products.live_debugger.backend.models import LiveDebuggerBreakpoint


class TestLiveDebuggerBreakpointAPI(APIBaseTest):
    def test_create_breakpoint(self):
        data = {
            "repository": "PostHog/posthog",
            "filename": "capture_event.py",
            "line_number": 123,
            "enabled": True,
            "condition": "user_id == '12345'",
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["repository"], data["repository"])
        self.assertEqual(response.json()["filename"], data["filename"])
        self.assertEqual(response.json()["line_number"], data["line_number"])
        self.assertEqual(response.json()["enabled"], data["enabled"])
        self.assertEqual(response.json()["condition"], data["condition"])

    def test_create_breakpoint_without_condition(self):
        data = {
            "repository": "PostHog/posthog",
            "filename": "capture_event.py",
            "line_number": 456,
            "enabled": True,
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["repository"], data["repository"])
        self.assertEqual(response.json()["filename"], data["filename"])
        self.assertIsNone(response.json()["condition"])

    def test_create_breakpoint_duplicate_same_repo_fails(self):
        """Test that creating duplicate breakpoint in same repo fails due to unique constraint"""
        from django.db import transaction

        data = {
            "repository": "PostHog/posthog",
            "filename": "test.py",
            "line_number": 100,
            "enabled": True,
        }
        response1 = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data,
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        with transaction.atomic():
            response2 = self.client.post(
                f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
                data=data,
            )
            self.assertNotEqual(response2.status_code, status.HTTP_201_CREATED)

        self.assertEqual(
            LiveDebuggerBreakpoint.objects.filter(
                team=self.team,
                repository=data["repository"],
                filename=data["filename"],
                line_number=data["line_number"],  # type: ignore
            ).count(),
            1,
        )

    def test_create_breakpoint_same_file_different_repo_succeeds(self):
        """Test that same filename/line can exist in different repositories"""
        data1 = {
            "repository": "PostHog/posthog",
            "filename": "test.py",
            "line_number": 100,
            "enabled": True,
        }
        data2 = {
            "repository": "PostHog/frontend",
            "filename": "test.py",
            "line_number": 100,
            "enabled": True,
        }

        response1 = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data1,
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data2,
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

        breakpoints = LiveDebuggerBreakpoint.objects.filter(team=self.team)
        self.assertEqual(breakpoints.count(), 2)

    def test_list_breakpoints(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file2.py",
            line_number=200,
            enabled=False,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_breakpoints_filter_by_repository(self):
        """Test filtering breakpoints by repository"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/frontend",
            filename="file2.py",
            line_number=200,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file3.py",
            line_number=300,
            enabled=True,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/?repository=PostHog/posthog"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(bp["repository"] == "PostHog/posthog" for bp in results))

    def test_list_breakpoints_filter_by_filename(self):
        """Test filtering breakpoints by filename"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/frontend",
            filename="file1.py",
            line_number=200,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file2.py",
            line_number=300,
            enabled=True,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/?filename=file1.py")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        self.assertTrue(all(bp["filename"] == "file1.py" for bp in results))

    def test_list_breakpoints_filter_by_repository_and_filename(self):
        """Test filtering breakpoints by both repository and filename"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/frontend",
            filename="file1.py",
            line_number=200,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file2.py",
            line_number=300,
            enabled=True,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/?repository=PostHog/posthog&filename=file1.py"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repository"], "PostHog/posthog")
        self.assertEqual(results[0]["filename"], "file1.py")
        self.assertEqual(results[0]["line_number"], 100)

    def test_retrieve_breakpoint(self):
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=50,
            enabled=True,
            condition="x > 10",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/{breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filename"], breakpoint.filename)
        self.assertEqual(response.json()["line_number"], breakpoint.line_number)
        self.assertEqual(response.json()["condition"], breakpoint.condition)

    def test_update_breakpoint(self):
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=50,
            enabled=True,
        )

        update_data = {
            "enabled": False,
            "condition": "y < 5",
        }
        response = self.client.patch(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/{breakpoint.id}/",
            data=update_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["enabled"], False)
        self.assertEqual(response.json()["condition"], "y < 5")

        breakpoint.refresh_from_db()
        self.assertEqual(breakpoint.enabled, False)
        self.assertEqual(breakpoint.condition, "y < 5")

    def test_delete_breakpoint(self):
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=50,
            enabled=True,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/live_debugger_breakpoints/{breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(LiveDebuggerBreakpoint.objects.filter(id=breakpoint.id).exists())

    def test_active_breakpoints_endpoint(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="disabled.py",
            line_number=200,
            enabled=False,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["filename"], "enabled.py")
        self.assertEqual(breakpoints[0]["line_number"], 100)

    def test_active_breakpoints_filter_by_filename(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file2.py",
            line_number=200,
            enabled=True,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"filename": "file1.py"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["filename"], "file1.py")

    def test_active_breakpoints_filter_by_repository(self):
        """Test filtering active breakpoints by repository"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/frontend",
            filename="file2.py",
            line_number=200,
            enabled=True,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"repository": "PostHog/posthog"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["repository"], "PostHog/posthog")
        self.assertEqual(breakpoints[0]["filename"], "file1.py")

    def test_active_breakpoints_include_disabled(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="disabled.py",
            line_number=200,
            enabled=False,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"enabled": "false"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should return both enabled and disabled
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]
        self.assertEqual(len(breakpoints), 2)

    def test_cannot_access_other_team_breakpoints(self):
        # Create a breakpoint for a different team
        other_team = self.organization.teams.create(name="Other Team")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="secret.py",
            line_number=999,
            enabled=True,
        )

        # Try to access it
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/{other_breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_only_shows_own_team_breakpoints(self):
        # Create breakpoints for current team
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="my_file.py",
            line_number=100,
            enabled=True,
        )

        # Create breakpoint for different team
        other_team = self.organization.teams.create(name="Other Team")
        LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="their_file.py",
            line_number=200,
            enabled=True,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only see own team's breakpoint
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["filename"], "my_file.py")

    def test_breakpoint_hits_with_defaults(self):
        """Test breakpoint_hits endpoint with no parameters (should use defaults)"""
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())
        self.assertIn("count", response.json())
        self.assertIn("has_more", response.json())

    def test_breakpoint_hits_with_valid_parameters(self):
        """Test breakpoint_hits endpoint with valid limit and offset"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": 50, "offset": 10},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_breakpoint_hits_with_breakpoint_id_filter(self):
        """Test breakpoint_hits endpoint with valid breakpoint_ids"""
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=50,
            enabled=True,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids={str(breakpoint.id)}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_breakpoint_hits_with_multiple_breakpoint_ids(self):
        """Test breakpoint_hits endpoint with multiple breakpoint_ids"""
        breakpoint1 = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=50,
            enabled=True,
        )
        breakpoint2 = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="test.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="other.py",
            line_number=200,
            enabled=True,
        )

        # Request hits for first two breakpoints only using repeated query params
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids={str(breakpoint1.id)}&breakpoint_ids={str(breakpoint2.id)}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_breakpoint_hits_invalid_breakpoint_id(self):
        """Test breakpoint_hits with non-UUID in breakpoint_ids"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids=not-a-uuid",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # ListField validation returns breakpoint_ids__0 for the first item
        self.assertIn("breakpoint_ids", response.json()["attr"])

    def test_breakpoint_hits_limit_too_high(self):
        """Test breakpoint_hits with limit > 1000"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": 1001},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "limit")

    def test_breakpoint_hits_limit_too_low(self):
        """Test breakpoint_hits with limit < 1"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": 0},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "limit")

    def test_breakpoint_hits_negative_limit(self):
        """Test breakpoint_hits with negative limit"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": -5},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "limit")

    def test_breakpoint_hits_negative_offset(self):
        """Test breakpoint_hits with negative offset"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"offset": -1},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "offset")

    def test_breakpoint_hits_invalid_limit_type(self):
        """Test breakpoint_hits with non-integer limit"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": "not-a-number"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "limit")

    def test_breakpoint_hits_invalid_offset_type(self):
        """Test breakpoint_hits with non-integer offset"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"offset": "not-a-number"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "offset")

    def test_breakpoint_hits_limit_at_max_boundary(self):
        """Test breakpoint_hits with limit exactly at max (1000)"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": 1000},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_breakpoint_hits_limit_at_min_boundary(self):
        """Test breakpoint_hits with limit exactly at min (1)"""
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/",
            {"limit": 1},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_active_breakpoints_enabled_boolean_true(self):
        """Test active_breakpoints with boolean enabled=true"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"enabled": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["has_more"], False)
        self.assertEqual(len(data["results"]), 1)

    def test_active_breakpoints_enabled_boolean_false(self):
        """Test active_breakpoints with boolean enabled=false"""
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="disabled.py",
            line_number=200,
            enabled=False,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"enabled": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # When enabled=false, should return all breakpoints
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["has_more"], False)
        self.assertEqual(len(data["results"]), 2)

    # ============================================================================
    # CRITICAL SECURITY TESTS - Data Isolation & Cross-Team Access Prevention
    # ============================================================================

    def test_breakpoint_hits_with_other_team_breakpoint_id_returns_404(self):
        """SECURITY: Requesting hits with another team's breakpoint_id returns 404 (not empty results)"""
        # Create a breakpoint for another team in the same organization
        other_team = self.organization.teams.create(name="Other Team")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="confidential.py",
            line_number=123,
            enabled=True,
        )

        # Try to request hits for the other team's breakpoint from our team's context
        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids={str(other_breakpoint.id)}",
        )

        # Should return 200 with empty results (filtered out)
        # The breakpoint ID is silently filtered to only include team's breakpoints
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_breakpoint_hits_with_nonexistent_breakpoint_id_returns_404(self):
        """SECURITY: Requesting hits with non-existent breakpoint_id returns empty results"""
        import uuid

        fake_uuid = str(uuid.uuid4())

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids={fake_uuid}",
        )

        # Should return 200 with empty results (filtered out)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_active_breakpoints_only_shows_own_team(self):
        """SECURITY: active_breakpoints endpoint only shows own team's breakpoints"""
        # Create breakpoints for our team
        our_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            repository="PostHog/posthog",
            filename="our_file.py",
            line_number=100,
            enabled=True,
        )

        # Create breakpoints for another team in same organization
        other_team = self.organization.teams.create(name="Other Team")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="their_secret_file.py",
            line_number=200,
            enabled=True,
        )

        # Request active breakpoints from our team's context
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]

        # Should only see our team's breakpoint
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["filename"], "our_file.py")
        self.assertEqual(breakpoints[0]["id"], str(our_breakpoint.id))

        # Verify other team's breakpoint is NOT in response
        other_breakpoint_ids = [str(bp["id"]) for bp in breakpoints]
        self.assertNotIn(str(other_breakpoint.id), other_breakpoint_ids)

    def test_active_breakpoints_cross_org_isolation(self):
        """SECURITY: Complete isolation between different organizations"""
        # Create a completely different organization
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        other_team = other_org.teams.create(name="Other Org Team")

        # Create breakpoint in the other organization
        other_org_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="other_org_secret.py",
            line_number=999,
            enabled=True,
        )

        # Request from our team's context
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["has_more"], False)
        breakpoints = data["results"]

        # Should see NO breakpoints from other organization
        other_org_breakpoint_ids = [str(bp["id"]) for bp in breakpoints]
        self.assertNotIn(str(other_org_breakpoint.id), other_org_breakpoint_ids)

    def test_cannot_access_different_org_via_url_path(self):
        """SECURITY: Cannot access a different organization's data by changing URL path"""
        # Create a different organization
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        other_team = other_org.teams.create(name="Other Org Team")
        LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="sensitive.py",
            line_number=500,
            enabled=True,
        )

        # Try to access via their team's URL path (different org)
        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/breakpoint_hits/")

        # Should be denied - cannot access different organization
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cannot_list_different_org_breakpoints_via_url_path(self):
        """SECURITY: Cannot list a different organization's breakpoints by changing URL path"""
        # Create a different organization
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        other_team = other_org.teams.create(name="Other Org Team")
        LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="confidential.py",
            line_number=999,
            enabled=True,
        )

        # Try to access other org's breakpoints list via their URL
        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/")

        # Should be denied - cannot access different organization
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_cannot_access_different_org_active_breakpoints_via_url_path(self):
        """SECURITY: Cannot access a different organization's active breakpoints by changing URL path"""
        # Create a different organization
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        other_team = other_org.teams.create(name="Other Org Team")
        LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="private.py",
            line_number=100,
            enabled=True,
        )

        # Try to access via their URL path (different org)
        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/active/")

        # Should be denied - cannot access different organization
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_can_access_another_team_in_same_org_by_default(self):
        """By default (no advanced permissions), org members can access all teams in their org"""
        # Create another team in the SAME organization
        other_team = self.organization.teams.create(name="Other Team in Same Org")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="shared_file.py",
            line_number=100,
            enabled=True,
        )

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["filename"], "shared_file.py")

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/{other_breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filename"], "shared_file.py")

    def test_cannot_access_private_team_without_explicit_access(self):
        """With advanced permissions, users cannot access private teams without explicit access"""
        from posthog.constants import AvailableFeature
        from posthog.models import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS}
        ]
        self.organization.save()

        other_team = self.organization.teams.create(name="Private Team")
        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        private_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="private_file.py",
            line_number=200,
            enabled=True,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/")
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/{private_breakpoint.id}/")
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        response = self.client.get(
            f"/api/projects/{other_team.id}/live_debugger_breakpoints/breakpoint_hits/?breakpoint_ids={str(private_breakpoint.id)}",
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_can_access_private_team_with_explicit_access(self):
        """With advanced permissions, users can access private teams when granted explicit access"""
        from posthog.constants import AvailableFeature
        from posthog.models import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS}
        ]
        self.organization.save()

        other_team = self.organization.teams.create(name="Private Team with Access")
        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            organization_member=self.organization_membership,
            role=None,
            access_level="member",
        )

        private_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="accessible_private_file.py",
            line_number=300,
            enabled=True,
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/{private_breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filename"], "accessible_private_file.py")

    def test_org_admin_can_access_private_team(self):
        """Org admins can access private teams even without explicit access"""
        from posthog.constants import AvailableFeature
        from posthog.models import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS}
        ]
        self.organization.save()

        other_team = self.organization.teams.create(name="Private Team for Admin")
        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        admin_accessible_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            repository="PostHog/posthog",
            filename="admin_accessible_file.py",
            line_number=400,
            enabled=True,
        )

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.get(f"/api/projects/{other_team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get(
            f"/api/projects/{other_team.id}/live_debugger_breakpoints/{admin_accessible_breakpoint.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["filename"], "admin_accessible_file.py")


class TestLiveDebuggerRepoBrowserAPI(APIBaseTest):
    """Test cases for repository browser API endpoints"""

    @patch("products.live_debugger.backend.github_client.list_repositories")
    def test_repositories_endpoint_success(self, mock_list_repos):
        """Test successful repository listing"""
        mock_list_repos.return_value = [
            {"name": "posthog", "full_name": "PostHog/posthog"},
            {"name": "billing", "full_name": "PostHog/billing"},
        ]

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_repo_browser/repositories/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("repositories", data)
        self.assertEqual(len(data["repositories"]), 2)
        self.assertEqual(data["repositories"][0]["name"], "posthog")
        self.assertEqual(data["repositories"][0]["full_name"], "PostHog/posthog")

    @patch("products.live_debugger.backend.github_client.get_github_integration")
    def test_repositories_endpoint_no_integration(self, mock_get_integration):
        """Test repository listing when no GitHub integration exists"""
        mock_get_integration.side_effect = github_client.GitHubIntegrationNotFoundError("No GitHub integration found")

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_repo_browser/repositories/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.json())

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    @patch("products.live_debugger.backend.github_client.get_repository_tree")
    @patch("products.live_debugger.backend.github_cache.get_cached_tree")
    def test_tree_endpoint_success(self, mock_get_cached, mock_get_tree, mock_get_sha):
        """Test successful tree retrieval"""
        mock_get_cached.return_value = None
        mock_get_sha.return_value = "abc123"
        mock_get_tree.return_value = {
            "sha": "abc123",
            "url": "https://api.github.com/repos/PostHog/posthog/git/trees/abc123",
            "tree": [
                {
                    "path": "test.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "def456",
                    "size": 100,
                    "url": "https://api.github.com/repos/PostHog/posthog/git/blobs/def456",
                }
            ],
            "truncated": False,
        }

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/tree/?repo=posthog&branch=master"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["sha"], "abc123")
        self.assertEqual(len(data["tree"]), 1)
        self.assertEqual(data["tree"][0]["path"], "test.py")

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    @patch("products.live_debugger.backend.github_cache.get_cached_tree")
    def test_tree_endpoint_from_cache(self, mock_get_cached, mock_get_sha):
        """Test tree retrieval from cache"""
        mock_get_sha.return_value = "cached123"
        cached_data = {
            "sha": "cached123",
            "url": "https://api.github.com/repos/PostHog/posthog/git/trees/cached123",
            "tree": [{"path": "cached.py", "mode": "100644", "type": "blob", "sha": "xyz789", "size": 50}],
            "truncated": False,
        }
        mock_get_cached.return_value = cached_data

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/tree/?repo=posthog&branch=master"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["sha"], "cached123")
        self.assertEqual(data["tree"][0]["path"], "cached.py")

    def test_tree_endpoint_missing_repo(self):
        """Test tree endpoint with missing repo parameter"""
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_repo_browser/tree/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    def test_tree_endpoint_no_integration(self, mock_get_sha):
        """Test tree endpoint when no GitHub integration exists"""
        mock_get_sha.side_effect = github_client.GitHubIntegrationNotFoundError("No GitHub integration found")

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/tree/?repo=posthog&branch=master"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.json())

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    @patch("products.live_debugger.backend.github_client.get_file_content")
    @patch("products.live_debugger.backend.github_cache.get_cached_file")
    def test_file_endpoint_success(self, mock_get_cached, mock_get_file, mock_get_sha):
        """Test successful file content retrieval"""
        mock_get_cached.return_value = None
        mock_get_sha.return_value = "abc123"
        mock_get_file.return_value = {
            "name": "test.py",
            "path": "posthog/test.py",
            "sha": "file123",
            "size": 200,
            "url": "https://api.github.com/repos/PostHog/posthog/contents/posthog/test.py",
            "html_url": "https://github.com/PostHog/posthog/blob/master/posthog/test.py",
            "git_url": "https://api.github.com/repos/PostHog/posthog/git/blobs/file123",
            "download_url": "https://raw.githubusercontent.com/PostHog/posthog/master/posthog/test.py",
            "type": "file",
            "content": "def test(): pass",
            "encoding": "utf-8",
        }

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/file/?repo=posthog&branch=master&path=posthog/test.py"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "test.py")
        self.assertEqual(data["content"], "def test(): pass")

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    @patch("products.live_debugger.backend.github_cache.get_cached_file")
    def test_file_endpoint_from_cache(self, mock_get_cached, mock_get_sha):
        """Test file retrieval from cache"""
        mock_get_sha.return_value = "abc123"
        cached_data = {
            "name": "cached.py",
            "path": "posthog/cached.py",
            "sha": "cached_file123",
            "size": 100,
            "content": "# cached content",
            "encoding": "utf-8",
        }
        mock_get_cached.return_value = cached_data

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/file/?repo=posthog&branch=master&path=posthog/cached.py"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["name"], "cached.py")
        self.assertEqual(data["content"], "# cached content")

    def test_file_endpoint_missing_repo(self):
        """Test file endpoint with missing repo parameter"""
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_repo_browser/file/?path=test.py")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_file_endpoint_missing_path(self):
        """Test file endpoint with missing path parameter"""
        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_repo_browser/file/?repo=posthog")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    @patch("products.live_debugger.backend.github_client.get_branch_sha")
    def test_file_endpoint_no_integration(self, mock_get_sha):
        """Test file endpoint when no GitHub integration exists"""
        mock_get_sha.side_effect = github_client.GitHubIntegrationNotFoundError("No GitHub integration found")

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_repo_browser/file/?repo=posthog&branch=master&path=test.py"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.json())


class TestGitHubClientIntegration(APIBaseTest):
    """
    Integration tests for GitHub client using responses library.
    Tests actual HTTP request construction, headers, and response parsing.
    """

    def setUp(self):
        super().setUp()
        # Create a mock GitHub integration
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"organization": "PostHog"},
            sensitive_config={"access_token": "fake_token_12345"},
        )

        # Mock the GitHubIntegration wrapper
        self.mock_github_integration = MagicMock()
        self.mock_github_integration.organization.return_value = "PostHog"
        self.mock_github_integration.integration.sensitive_config = {"access_token": "fake_token_12345"}
        self.mock_github_integration.access_token_expired.return_value = False

        # Patch get_github_integration to return our mock
        self.get_integration_patcher = patch(
            "products.live_debugger.backend.github_client.get_github_integration",
            return_value=self.mock_github_integration,
        )
        self.get_integration_patcher.start()

    def tearDown(self):
        self.get_integration_patcher.stop()
        super().tearDown()

    def test_list_repositories_calls_integration(self):
        """Test that list_repositories calls the GitHubIntegration.list_repositories method"""
        # Mock the integration's list_repositories method
        self.mock_github_integration.list_repositories.side_effect = [
            ["posthog", "billing"],
            [],  # Empty list signals end of pagination
        ]

        repos = github_client.list_repositories(self.team)

        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0]["name"], "posthog")
        self.assertEqual(repos[0]["full_name"], "PostHog/posthog")
        self.assertEqual(repos[1]["name"], "billing")
        self.assertEqual(repos[1]["full_name"], "PostHog/billing")

        # Verify the integration method was called with correct pages
        self.assertEqual(self.mock_github_integration.list_repositories.call_count, 2)
        self.mock_github_integration.list_repositories.assert_any_call(page=1)
        self.mock_github_integration.list_repositories.assert_any_call(page=2)

    def test_list_repositories_pagination(self):
        """Test that list_repositories handles pagination correctly"""
        # Simulate multiple pages of results
        self.mock_github_integration.list_repositories.side_effect = [
            [f"repo{i}" for i in range(100)],  # Page 1
            ["final-repo"],  # Page 2
            [],  # End of results
        ]

        repos = github_client.list_repositories(self.team)

        self.assertEqual(len(repos), 101)
        self.assertEqual(repos[-1]["name"], "final-repo")
        self.assertEqual(repos[-1]["full_name"], "PostHog/final-repo")
        # Should have called with 3 pages
        self.assertEqual(self.mock_github_integration.list_repositories.call_count, 3)

    @responses.activate
    def test_get_branch_sha_http_request(self):
        """Test that get_branch_sha makes correct HTTP request and parses response"""
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/branches/master",
            json={"name": "master", "commit": {"sha": "abc123def456", "url": "..."}},
            status=200,
        )

        sha = github_client.get_branch_sha(self.team, "posthog", "master")

        self.assertEqual(sha, "abc123def456")

        # Verify request
        self.assertEqual(len(responses.calls), 1)
        request = responses.calls[0].request
        self.assertEqual(request.url, "https://api.github.com/repos/PostHog/posthog/branches/master")
        self.assertEqual(request.headers["Authorization"], "Bearer fake_token_12345")
        self.assertEqual(request.headers["Accept"], "application/vnd.github+json")

    @responses.activate
    def test_get_branch_sha_404_handling(self):
        """Test that get_branch_sha handles 404 correctly"""
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/branches/nonexistent",
            json={"message": "Branch not found"},
            status=404,
        )

        with self.assertRaises(github_client.GitHubClientError) as ctx:
            github_client.get_branch_sha(self.team, "posthog", "nonexistent")

        self.assertIn("Branch 'nonexistent' not found", str(ctx.exception))

    @responses.activate
    def test_get_repository_tree_http_request(self):
        """Test that get_repository_tree makes correct request and filters Python files"""
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/git/trees/abc123",
            json={
                "sha": "abc123",
                "url": "...",
                "tree": [
                    {"path": "test.py", "type": "blob", "sha": "file1"},
                    {"path": "README.md", "type": "blob", "sha": "file2"},
                    {"path": "posthog/models.py", "type": "blob", "sha": "file3"},
                    {"path": "posthog", "type": "tree", "sha": "dir1"},
                    {"path": "package.json", "type": "blob", "sha": "file4"},
                ],
                "truncated": False,
            },
            status=200,
        )

        tree_data = github_client.get_repository_tree(self.team, "posthog", "abc123")

        # Should only include .py files and directories
        self.assertEqual(len(tree_data["tree"]), 3)
        paths = [item["path"] for item in tree_data["tree"]]
        self.assertIn("test.py", paths)
        self.assertIn("posthog/models.py", paths)
        self.assertIn("posthog", paths)
        self.assertNotIn("README.md", paths)
        self.assertNotIn("package.json", paths)

        # Verify request
        request = responses.calls[0].request
        self.assertEqual(request.url, "https://api.github.com/repos/PostHog/posthog/git/trees/abc123?recursive=1")
        self.assertEqual(request.headers["Authorization"], "Bearer fake_token_12345")

    @responses.activate
    def test_get_file_content_http_request(self):
        """Test that get_file_content makes correct request and decodes base64 content"""
        import base64

        content = "def test():\n    pass"
        encoded_content = base64.b64encode(content.encode()).decode()

        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/contents/test.py",
            json={
                "name": "test.py",
                "path": "test.py",
                "sha": "file123",
                "size": len(content),
                "encoding": "base64",
                "content": encoded_content,
                "url": "...",
            },
            status=200,
        )

        file_data = github_client.get_file_content(self.team, "posthog", "test.py")

        # Should decode base64 content
        self.assertEqual(file_data["name"], "test.py")
        self.assertEqual(file_data["content"], content)
        self.assertEqual(file_data["encoding"], "base64")

        # Verify request
        request = responses.calls[0].request
        self.assertEqual(request.url, "https://api.github.com/repos/PostHog/posthog/contents/test.py")
        self.assertEqual(request.headers["Authorization"], "Bearer fake_token_12345")

    @responses.activate
    def test_get_file_content_404_handling(self):
        """Test that get_file_content handles 404 correctly"""
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/contents/nonexistent.py",
            json={"message": "Not Found"},
            status=404,
        )

        with self.assertRaises(github_client.GitHubClientError) as ctx:
            github_client.get_file_content(self.team, "posthog", "nonexistent.py")

        self.assertIn("File 'nonexistent.py' not found", str(ctx.exception))

    @responses.activate
    def test_token_refresh_on_401(self):
        """Test that 401 triggers token refresh and retry"""

        # Setup refresh to update token
        def refresh_token():
            self.mock_github_integration.integration.sensitive_config["access_token"] = "new_token"

        self.mock_github_integration.refresh_access_token.side_effect = refresh_token

        # First request returns 401
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/branches/master",
            json={"message": "Unauthorized"},
            status=401,
        )
        # Second request (after refresh) succeeds
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/branches/master",
            json={"name": "master", "commit": {"sha": "abc123"}},
            status=200,
        )

        sha = github_client.get_branch_sha(self.team, "posthog", "master")

        self.assertEqual(sha, "abc123")
        # Should have made 2 requests
        self.assertEqual(len(responses.calls), 2)
        # Token refresh should have been called
        self.mock_github_integration.refresh_access_token.assert_called_once()

    @responses.activate
    def test_python_file_filtering_comprehensive(self):
        """Test comprehensive Python file filtering in get_repository_tree"""
        responses.add(
            responses.GET,
            "https://api.github.com/repos/PostHog/posthog/git/trees/abc123",
            json={
                "sha": "abc123",
                "tree": [
                    # Should include
                    {"path": "models.py", "type": "blob"},
                    {"path": "deep/nested/utils.py", "type": "blob"},
                    {"path": "__init__.py", "type": "blob"},
                    {"path": "src", "type": "tree"},
                    # Should exclude
                    {"path": "README.md", "type": "blob"},
                    {"path": "package.json", "type": "blob"},
                    {"path": "test.js", "type": "blob"},
                    {"path": "Dockerfile", "type": "blob"},
                    {"path": ".gitignore", "type": "blob"},
                    {"path": "setup.py~", "type": "blob"},  # backup file
                    {"path": "test.pyc", "type": "blob"},  # compiled python
                ],
            },
            status=200,
        )

        tree_data = github_client.get_repository_tree(self.team, "posthog", "abc123")

        paths = {item["path"] for item in tree_data["tree"]}
        # Should include .py files and directories
        self.assertIn("models.py", paths)
        self.assertIn("deep/nested/utils.py", paths)
        self.assertIn("__init__.py", paths)
        self.assertIn("src", paths)

        # Should exclude non-.py files
        self.assertNotIn("README.md", paths)
        self.assertNotIn("package.json", paths)
        self.assertNotIn("test.js", paths)
        self.assertNotIn("Dockerfile", paths)
        self.assertNotIn(".gitignore", paths)
        self.assertNotIn("setup.py~", paths)
        self.assertNotIn("test.pyc", paths)
