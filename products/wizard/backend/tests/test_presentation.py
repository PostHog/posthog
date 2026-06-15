from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization

from products.wizard.backend.models import WizardSession
from products.wizard.backend.presentation.views import _wizard_sync_killswitch_enabled


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
        first = self.client.post(self._url(), self._payload(), format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            self._url(),
            self._payload(run_phase="completed", tasks=[{"id": "1", "title": "Install SDK", "status": "completed"}]),
            format="json",
        )

        # Second POST against the same session_id is an update, not a create.
        self.assertEqual(response.status_code, status.HTTP_200_OK)

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

    def test_list_empty_skill_id_is_ignored(self):
        # An empty skill_id is treated as no filter, so the session still shows up.
        self.client.post(
            self._url(),
            self._payload(workflow_id="onboarding", skill_id="nextjs"),
            format="json",
        )

        response = self.client.get(self._url() + "?workflow_id=onboarding&skill_id=")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_retrieve_by_session_id(self):
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.get(self._url("onboarding-nextjs-2026-05-19T10:00:00Z/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["workflow_id"], "onboarding")

    def test_retrieve_unknown_session_returns_404(self):
        response = self.client.get(self._url("does-not-exist/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_latest_returns_most_recent_session_for_workflow(self):
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

        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["started_at"], "2026-05-19T19:00:00Z")
        # A bare object, not a paginated `{results: [...]}` envelope.
        self.assertNotIn("results", body)
        self.assertEqual(body["session_id"], "onboarding-nextjs-2026-05-19T19:00:00Z")

    def test_latest_breaks_started_at_ties_by_created_at(self):
        # Same started_at; the row POSTed second has the later created_at and wins.
        self.client.post(
            self._url(),
            self._payload(
                session_id="onboarding-nextjs-first",
                started_at="2026-05-19T10:00:00Z",
            ),
            format="json",
        )
        self.client.post(
            self._url(),
            self._payload(
                session_id="onboarding-nextjs-second",
                started_at="2026-05-19T10:00:00Z",
            ),
            format="json",
        )

        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["session_id"], "onboarding-nextjs-second")

    def test_latest_skill_id_narrows_the_match(self):
        self.client.post(
            self._url(),
            self._payload(session_id="onboarding-nextjs-1", skill_id="nextjs"),
            format="json",
        )

        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding&skill_id=django")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_latest_without_a_session_returns_204_not_404(self):
        # 204, not 404: the detector treats 404 as a missing endpoint and stops polling.
        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")

    def test_latest_requires_workflow_id(self):
        response = self.client.get(self._url("latest/"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_latest_does_not_collide_with_session_id_lookup(self):
        # lookup_value_regex excludes "latest", so the action wins over a retrieve
        # of a session whose id is literally "latest".
        self.client.post(
            self._url(),
            self._payload(session_id="latest", started_at="2026-05-19T10:00:00Z"),
            format="json",
        )

        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand([("delete",), ("put",)])
    def test_disallowed_verb_returns_405(self, method):
        self.client.post(self._url(), self._payload(), format="json")

        response = getattr(self.client, method)(self._url("onboarding-nextjs-2026-05-19T10:00:00Z/"))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    @parameterized.expand(
        [
            ("invalid_task_status", {"tasks": [{"id": "1", "title": "x", "status": "pizza"}]}),
            ("invalid_run_phase", {"run_phase": "exploded"}),
        ]
    )
    def test_invalid_enum_payload_rejected(self, _label, payload_overrides):
        response = self.client.post(self._url(), self._payload(**payload_overrides), format="json")
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

    def test_latest_other_team_cannot_see_sessions(self):
        # Create a session in self.team's project.
        self.client.post(self._url(), self._payload(), format="json")

        # Spin up a separate org + team. The current user is not a member,
        # so the project endpoint should refuse the request entirely.
        other_org = Organization.objects.create(name="Other Org")
        other_team = self.create_team_with_organization(other_org)

        response = self.client.get(f"/api/projects/{other_team.id}/wizard/sessions/latest/?workflow_id=onboarding")
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

    def test_stream_requires_workflow_id(self):
        # No params → 400 from the view-level validation (workflow_id is the
        # only required query param; skill_id is optional for pattern subscribe).
        response = self.client.get(f"{self._url()}stream/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.wizard.backend.presentation.views.posthoganalytics.feature_enabled", return_value=True)
    def test_stream_killswitch_returns_204(self, _mock_feature_enabled):
        # When the killswitch flag is on, the endpoint short-circuits with a 204
        # before any stream work — a 204 tells EventSource to stop reconnecting.
        response = self.client.get(f"{self._url()}stream/?workflow_id=onboarding")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @patch("products.wizard.backend.presentation.views.posthoganalytics.feature_enabled", return_value=True)
    def test_latest_killswitch_returns_204_even_with_a_live_session(self, _mock_feature_enabled):
        # Parity with stream: with the killswitch on, `latest` short-circuits to a 204
        # even though a real session exists, so the detector's 60s poll winds down too
        # (the client treats 204 as "no run") rather than only the SSE stream closing.
        self.client.post(self._url(), self._payload(), format="json")

        response = self.client.get(self._url("latest/") + "?workflow_id=onboarding")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    @parameterized.expand([("on", True, True), ("off", False, False), ("unresolved", None, False)])
    def test_wizard_sync_killswitch_helper(self, _label, flag_value, expected):
        with patch(
            "products.wizard.backend.presentation.views.posthoganalytics.feature_enabled",
            return_value=flag_value,
        ):
            self.assertEqual(_wizard_sync_killswitch_enabled("distinct-id"), expected)
