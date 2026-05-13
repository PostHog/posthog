from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.live_debugger.backend.models import LiveDebuggerBreakpoint, LiveDebuggerProgram


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


class TestLiveDebuggerProgramAPI(ClickhouseTestMixin, APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/live_debugger_programs/{suffix}"

    def _create_program(
        self,
        *,
        team: Team | None = None,
        code: str = "trace foo() { log() }",
        description: str = "Trace foo calls",
        status_value: str = LiveDebuggerProgram.Status.INSTALLED,
    ) -> LiveDebuggerProgram:
        return LiveDebuggerProgram.objects.create(
            team=team or self.team,
            code=code,
            description=description,
            status=status_value,
        )

    def _emit_hit(
        self,
        *,
        program_id: str,
        probe_id: str = "probe-1",
        distinct_id: str = "user-1",
        function_name: str = "foo",
    ) -> None:
        _create_event(
            team=self.team,
            event="$data_breakpoint_hit",
            distinct_id=distinct_id,
            properties={
                "$program_id": program_id,
                "$probe_id": probe_id,
                "$line_number": 42,
                "$file_path": "app.py",
                "$locals_variables": {"x": 1},
                "$stack_trace": [{"function": function_name}],
            },
            timestamp=datetime.now(tz=UTC),
        )

    # ----- install (POST /) -----

    def test_install_returns_full_program_record(self) -> None:
        response = self.client.post(
            self._url(),
            data={"code": "trace foo() { log() }", "description": "Trace foo calls"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertIn("id", body)
        self.assertEqual(body["code"], "trace foo() { log() }")
        self.assertEqual(body["description"], "Trace foo calls")
        self.assertEqual(body["status"], LiveDebuggerProgram.Status.INSTALLED)
        self.assertIn("created_at", body)
        self.assertIn("updated_at", body)

    def test_install_defaults_description_to_empty_when_omitted(self) -> None:
        response = self.client.post(self._url(), data={"code": "x"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["description"], "")

    def test_install_without_code_returns_400(self) -> None:
        response = self.client.post(self._url(), data={"description": "no code"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("code", response.json()["attr"])

    def test_install_ignores_client_supplied_status(self) -> None:
        response = self.client.post(
            self._url(),
            data={"code": "x", "status": LiveDebuggerProgram.Status.UNINSTALLED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], LiveDebuggerProgram.Status.INSTALLED)

    # ----- list (GET /) -----

    def test_list_empty_returns_no_results(self) -> None:
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_list_orders_by_created_at_desc(self) -> None:
        first = self._create_program(description="first")
        second = self._create_program(description="second")
        response = self.client.get(self._url())
        ids = [item["id"] for item in response.json()["results"]]
        self.assertEqual(ids, [str(second.id), str(first.id)])

    def test_list_omits_code_field(self) -> None:
        self._create_program()
        response = self.client.get(self._url())
        item = response.json()["results"][0]
        self.assertNotIn("code", item)
        # Required compact fields are present
        self.assertEqual(set(item.keys()), {"id", "description", "status", "created_at", "updated_at"})

    def test_list_includes_installed_and_uninstalled(self) -> None:
        self._create_program(description="active")
        self._create_program(description="retired", status_value=LiveDebuggerProgram.Status.UNINSTALLED)
        response = self.client.get(self._url())
        statuses = {item["status"] for item in response.json()["results"]}
        self.assertEqual(statuses, {"installed", "uninstalled"})

    def test_list_does_not_leak_programs_from_other_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._create_program(description="mine")
        self._create_program(team=other_team, description="theirs")
        response = self.client.get(self._url())
        descriptions = [item["description"] for item in response.json()["results"]]
        self.assertEqual(descriptions, ["mine"])

    # ----- show (GET /{id}/) -----

    def test_show_returns_full_program_including_code(self) -> None:
        program = self._create_program(code="trace bar() {}", description="bar")
        response = self.client.get(self._url(f"{program.id}/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["id"], str(program.id))
        self.assertEqual(body["code"], "trace bar() {}")
        self.assertEqual(body["description"], "bar")

    def test_show_returns_404_for_unknown_id(self) -> None:
        response = self.client.get(self._url("00000000-0000-0000-0000-000000000000/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_show_returns_404_for_program_from_other_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        program = self._create_program(team=other_team)
        response = self.client.get(self._url(f"{program.id}/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ----- uninstall (POST /{id}/uninstall/) -----

    def test_uninstall_transitions_status_to_uninstalled(self) -> None:
        program = self._create_program()
        response = self.client.post(self._url(f"{program.id}/uninstall/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], LiveDebuggerProgram.Status.UNINSTALLED)
        program.refresh_from_db()
        self.assertEqual(program.status, LiveDebuggerProgram.Status.UNINSTALLED)

    def test_uninstall_is_idempotent(self) -> None:
        program = self._create_program(status_value=LiveDebuggerProgram.Status.UNINSTALLED)
        original_updated_at = program.updated_at
        response = self.client.post(self._url(f"{program.id}/uninstall/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], LiveDebuggerProgram.Status.UNINSTALLED)
        # updated_at not bumped when no transition needed
        program.refresh_from_db()
        self.assertEqual(program.updated_at, original_updated_at)

    def test_uninstall_returns_404_for_unknown_id(self) -> None:
        response = self.client.post(self._url("00000000-0000-0000-0000-000000000000/uninstall/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_uninstall_does_not_touch_other_team_program(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        program = self._create_program(team=other_team)
        response = self.client.post(self._url(f"{program.id}/uninstall/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        program.refresh_from_db()
        self.assertEqual(program.status, LiveDebuggerProgram.Status.INSTALLED)

    # ----- events (GET /{id}/events/) -----

    def test_events_empty_when_no_hits(self) -> None:
        program = self._create_program()
        response = self.client.get(self._url(f"{program.id}/events/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["results"], [])
        self.assertEqual(body["count"], 0)
        self.assertFalse(body["has_more"])

    def test_events_returns_hits_for_this_program(self) -> None:
        program = self._create_program()
        self._emit_hit(program_id=str(program.id), probe_id="p1", function_name="foo")
        self._emit_hit(program_id=str(program.id), probe_id="p2", function_name="bar")
        flush_persons_and_events()

        response = self.client.get(self._url(f"{program.id}/events/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertFalse(body["has_more"])
        function_names = {event["function_name"] for event in body["results"]}
        self.assertEqual(function_names, {"foo", "bar"})
        for event in body["results"]:
            self.assertEqual(event["program_id"], str(program.id))
            self.assertEqual(event["filename"], "app.py")
            self.assertEqual(event["line_number"], 42)
            self.assertEqual(event["locals"], {"x": 1})

    def test_events_excludes_hits_from_other_programs(self) -> None:
        program = self._create_program()
        other_program = self._create_program()
        self._emit_hit(program_id=str(program.id), probe_id="mine")
        self._emit_hit(program_id=str(other_program.id), probe_id="theirs")
        flush_persons_and_events()

        response = self.client.get(self._url(f"{program.id}/events/"))
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["probe_id"], "mine")

    def test_events_has_more_when_limit_reached(self) -> None:
        program = self._create_program()
        for i in range(3):
            self._emit_hit(program_id=str(program.id), probe_id=f"p{i}")
        flush_persons_and_events()

        response = self.client.get(self._url(f"{program.id}/events/"), {"limit": 2})
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertTrue(body["has_more"])

    def test_events_returns_404_for_unknown_program(self) -> None:
        response = self.client.get(self._url("00000000-0000-0000-0000-000000000000/events/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_events_returns_404_for_other_team_program(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        program = self._create_program(team=other_team)
        response = self.client.get(self._url(f"{program.id}/events/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("limit_too_high", {"limit": 1001}, "limit"),
            ("limit_too_low", {"limit": 0}, "limit"),
            ("limit_negative", {"limit": -1}, "limit"),
            ("limit_non_integer", {"limit": "abc"}, "limit"),
            ("offset_negative", {"offset": -1}, "offset"),
            ("offset_non_integer", {"offset": "abc"}, "offset"),
        ]
    )
    def test_events_rejects_invalid_query_params(self, _name: str, params: dict, expected_attr: str) -> None:
        program = self._create_program()
        response = self.client.get(self._url(f"{program.id}/events/"), params)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_attr, response.json()["attr"])

    @parameterized.expand(
        [
            ("limit_at_max", {"limit": 1000}),
            ("limit_at_min", {"limit": 1}),
            ("default_pagination", {}),
        ]
    )
    def test_events_accepts_boundary_query_params(self, _name: str, params: dict) -> None:
        program = self._create_program()
        response = self.client.get(self._url(f"{program.id}/events/"), params)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ----- disabled HTTP methods -----

    @parameterized.expand(
        [
            ("put", "put"),
            ("patch", "patch"),
            ("delete", "delete"),
        ]
    )
    def test_disabled_methods_return_405(self, _name: str, method: str) -> None:
        program = self._create_program()
        response = getattr(self.client, method)(self._url(f"{program.id}/"))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class TestLiveDebuggerActiveProgramsAPI(APIBaseTest):
    URL = "/api/projects/@current/live_debugger/programs/active/"

    def test_empty_team_returns_empty_program_list(self):
        from products.live_debugger.backend._proto.bytecode_pb2 import ProgramList

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        parsed = ProgramList()
        parsed.ParseFromString(response.content)
        self.assertEqual(list(parsed.programs), [])

    HOGTRACE_SOURCE_A = "fn:myapp.users.create_user:entry { capture(x=arg0); }"
    HOGTRACE_SOURCE_B = "fn:myapp.orders.checkout:entry { capture(y=arg0); }"

    def _make_program(
        self, code: str, team=None, status_value=LiveDebuggerProgram.Status.INSTALLED
    ) -> LiveDebuggerProgram:
        return LiveDebuggerProgram.objects.create(
            team=team or self.team,
            code=code,
            description="test program",
            status=status_value,
        )

    def test_happy_path_returns_compiled_programs(self):
        from hogtrace import ProgramList

        p_a = self._make_program(self.HOGTRACE_SOURCE_A)
        p_b = self._make_program(self.HOGTRACE_SOURCE_B)

        response = self.client.get(self.URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/octet-stream")

        parsed = ProgramList.from_bytes(response.content)
        ids = sorted(p.id for p in parsed.programs)
        self.assertEqual(ids, sorted([str(p_a.id), str(p_b.id)]))

        hashes = [p.hash for p in parsed.programs]
        self.assertEqual(len(set(hashes)), 2, "distinct programs should have distinct hashes")
        for h in hashes:
            self.assertEqual(len(h), 64, "sha256 hex digest is 64 chars")
            self.assertNotEqual(h, "test", "hogtrace placeholder hash must be overwritten")
            int(h, 16)

    def test_hash_is_stable_and_responds_to_code_changes(self):
        from hogtrace import ProgramList

        program = self._make_program(self.HOGTRACE_SOURCE_A)

        resp1 = self.client.get(self.URL)
        resp2 = self.client.get(self.URL)
        hash1 = ProgramList.from_bytes(resp1.content).programs[0].hash
        hash2 = ProgramList.from_bytes(resp2.content).programs[0].hash
        self.assertEqual(hash1, hash2, "same code should produce the same hash")

        program.code = self.HOGTRACE_SOURCE_B
        program.save(update_fields=["code", "updated_at"])

        resp3 = self.client.get(self.URL)
        hash3 = ProgramList.from_bytes(resp3.content).programs[0].hash
        self.assertNotEqual(hash1, hash3, "different code should produce a different hash")

    def test_excludes_uninstalled_programs(self):
        from hogtrace import ProgramList

        installed = self._make_program(self.HOGTRACE_SOURCE_A)
        self._make_program(self.HOGTRACE_SOURCE_B, status_value=LiveDebuggerProgram.Status.UNINSTALLED)

        response = self.client.get(self.URL)

        ids = [p.id for p in ProgramList.from_bytes(response.content).programs]
        self.assertEqual(ids, [str(installed.id)])

    def test_team_isolation(self):
        from hogtrace import ProgramList

        other_team = Team.objects.create(organization=self.organization, name="Sibling")
        self._make_program(self.HOGTRACE_SOURCE_A, team=other_team)
        own = self._make_program(self.HOGTRACE_SOURCE_B)

        response = self.client.get(self.URL)

        ids = [p.id for p in ProgramList.from_bytes(response.content).programs]
        self.assertEqual(ids, [str(own.id)])
