from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization

from products.wizard.backend.models import WizardSession


class TestWizardSessionViewSet(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/wizard/sessions/{suffix}"

    def _payload(self, **overrides) -> dict:
        payload = {
            "session_id": "onboarding-nextjs-2026-05-19T10:00:00Z",
            "workflow_id": "onboarding",
            "skill_id": "nextjs",
            "started_at": "2026-05-19T10:00:00Z",
            "run_phase": "running",
            "tasks": [
                {
                    "id": "1",
                    "title": "Install Next.js plugin",
                    "status": "in_progress",
                },
                {
                    "id": "2",
                    "title": "Configure plugin with API key",
                    "status": "pending",
                },
            ],
        }
        payload.update(overrides)
        return payload

    def test_create_session(self):
        response = self.client.post(self._url(), self._payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["session_id"], "onboarding-nextjs-2026-05-19T10:00:00Z")
        self.assertEqual(data["workflow_id"], "onboarding")
        self.assertEqual(data["skill_id"], "nextjs")
        self.assertEqual(data["run_phase"], "running")
        self.assertEqual(len(data["tasks"]), 2)
        self.assertEqual(data["team_id"], self.team.id)

        self.assertEqual(WizardSession.objects.unscoped().filter(team=self.team).count(), 1)

    def test_repost_same_session_id_upserts(self):
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.post(
            self._url(),
            self._payload(run_phase="completed", tasks=[{"id": "1", "title": "Install SDK", "status": "completed"}]),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["run_phase"], "completed")
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["status"], "completed")

        self.assertEqual(WizardSession.objects.unscoped().filter(team=self.team).count(), 1)

    def test_different_session_id_creates_new_row(self):
        self.client.post(self._url(), self._payload(), format="json")

        self.client.post(
            self._url(),
            self._payload(session_id="onboarding-nextjs-2026-05-19T10:20:39Z"),
            format="json",
        )

        self.assertEqual(WizardSession.objects.unscoped().filter(team=self.team).count(), 2)

    def test_list_returns_sessions_ordered_by_started_at_desc(self):
        self.client.post(
            self._url(),
            self._payload(
                session_id="onboarding-nextjs-2026-05-19T09:00:00Z",
                started_at="2026-05-19T09:00:00Z",
            ),
            format="json",
        )
        self.client.post(
            self._url(),
            self._payload(
                session_id="onboarding-nextjs-2026-05-19T19:00:00Z",
                started_at="2026-05-19T19:00:00Z",
            ),
            format="json",
        )

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["started_at"], "2026-05-19T19:00:00Z")
        self.assertEqual(results[1]["started_at"], "2026-05-19T09:00:00Z")

    def test_list_filters_by_workflow_and_skill(self):
        self.client.post(
            self._url(),
            self._payload(
                session_id="onboarding-nextjs-1",
                workflow_id="onboarding",
                skill_id="nextjs",
            ),
            format="json",
        )
        self.client.post(
            self._url(),
            self._payload(
                session_id="migration-amplitude-1",
                workflow_id="migration",
                skill_id="amplitude",
            ),
            format="json",
        )

        response = self.client.get(self._url() + "?workflow_id=onboarding")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["workflow_id"], "onboarding")

        response = self.client.get(self._url() + "?workflow_id=onboarding&skill_id=django")
        self.assertEqual(len(response.json()["results"]), 0)

    def test_retrieve_by_session_id(self):
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.get(self._url("onboarding-nextjs-2026-05-19T10:00:00Z/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["workflow_id"], "onboarding")

    def test_retrieve_unknown_session_returns_404(self):
        response = self.client.get(self._url("does-not-exist/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_is_disallowed(self):
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.delete(self._url("onboarding-nextjs-2026-05-19T10:00:00Z/"))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_is_disallowed(self):
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.put(
            self._url("onboarding-nextjs-2026-05-19T10:00:00Z/"),
            self._payload(run_phase="completed"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_invalid_task_status_rejected(self):
        response = self.client.post(
            self._url(),
            self._payload(tasks=[{"id": "1", "title": "x", "status": "pizza"}]),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_run_phase_rejected(self):
        response = self.client.post(
            self._url(),
            self._payload(run_phase="exploded"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_team_cannot_see_sessions(self):
        # Create a session in self.team's project.
        self.client.post(self._url(), self._payload(), format="json")

        # Spin up a separate org + team. The current user is not a member,
        # so the project endpoint should refuse the request entirely.
        other_org = Organization.objects.create(name="Other Org")
        other_team = self.create_team_with_organization(other_org)

        response = self.client.get(f"/api/projects/{other_team.id}/wizard/sessions/")
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_event_plan_and_error_persisted(self):
        response = self.client.post(
            self._url(),
            self._payload(
                run_phase="error",
                event_plan={"events": [{"name": "$pageview"}]},
                error={"type": "TimeoutError", "message": "Anthropic API timed out"},
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["event_plan"], {"events": [{"name": "$pageview"}]})
        self.assertEqual(data["error"], {"type": "TimeoutError", "message": "Anthropic API timed out"})
