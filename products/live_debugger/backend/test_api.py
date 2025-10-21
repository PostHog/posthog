from posthog.test.base import APIBaseTest

from rest_framework import status

from products.live_debugger.backend.models import LiveDebuggerBreakpoint


class TestLiveDebuggerBreakpointAPI(APIBaseTest):
    def test_create_breakpoint(self):
        data = {
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
        self.assertEqual(response.json()["filename"], data["filename"])
        self.assertEqual(response.json()["line_number"], data["line_number"])
        self.assertEqual(response.json()["enabled"], data["enabled"])
        self.assertEqual(response.json()["condition"], data["condition"])

    def test_create_breakpoint_without_condition(self):
        data = {
            "filename": "capture_event.py",
            "line_number": 456,
            "enabled": True,
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["filename"], data["filename"])
        self.assertIsNone(response.json()["condition"])

    def test_list_breakpoints(self):
        # Create some breakpoints
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="file2.py",
            line_number=200,
            enabled=False,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_retrieve_breakpoint(self):
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
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

        # Verify in database
        breakpoint.refresh_from_db()
        self.assertEqual(breakpoint.enabled, False)
        self.assertEqual(breakpoint.condition, "y < 5")

    def test_delete_breakpoint(self):
        breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="test.py",
            line_number=50,
            enabled=True,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/live_debugger_breakpoints/{breakpoint.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify it's deleted
        self.assertFalse(LiveDebuggerBreakpoint.objects.filter(id=breakpoint.id).exists())

    def test_active_breakpoints_endpoint(self):
        # Create enabled and disabled breakpoints
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="disabled.py",
            line_number=200,
            enabled=False,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        breakpoints = response.json()["breakpoints"]
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["filename"], "enabled.py")
        self.assertEqual(breakpoints[0]["line_number"], 100)

    def test_active_breakpoints_filter_by_filename(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="file1.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="file2.py",
            line_number=200,
            enabled=True,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/live_debugger_breakpoints/active/",
            {"filename": "file1.py"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        breakpoints = response.json()["breakpoints"]
        self.assertEqual(len(breakpoints), 1)
        self.assertEqual(breakpoints[0]["filename"], "file1.py")

    def test_active_breakpoints_include_disabled(self):
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
            filename="enabled.py",
            line_number=100,
            enabled=True,
        )
        LiveDebuggerBreakpoint.objects.create(
            team=self.team,
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
        breakpoints = response.json()["breakpoints"]
        self.assertEqual(len(breakpoints), 2)

    def test_cannot_access_other_team_breakpoints(self):
        # Create a breakpoint for a different team
        other_team = self.organization.teams.create(name="Other Team")
        other_breakpoint = LiveDebuggerBreakpoint.objects.create(
            team=other_team,
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
            filename="my_file.py",
            line_number=100,
            enabled=True,
        )

        # Create breakpoint for different team
        other_team = self.organization.teams.create(name="Other Team")
        LiveDebuggerBreakpoint.objects.create(
            team=other_team,
            filename="their_file.py",
            line_number=200,
            enabled=True,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/live_debugger_breakpoints/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only see own team's breakpoint
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["filename"], "my_file.py")
