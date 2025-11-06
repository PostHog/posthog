from posthog.test.base import APIBaseTest

from rest_framework import status

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

        from products.enterprise.backend.models.rbac.access_control import AccessControl

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

        from products.enterprise.backend.models.rbac.access_control import AccessControl

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

        from products.enterprise.backend.models.rbac.access_control import AccessControl

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
