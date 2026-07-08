from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionAction, VisionActionRun, VisionActionRunStatus


class _VisionActionAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Creating an action provisions a Slack internal_destination HogFunction, which resolves the
        # template from the DB.
        sync_template_to_db(template_slack)
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        # Saving a HogFunction pushes it to the CDP workers; there are none in tests.
        self.reload_patcher = patch(
            "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers",
        )
        self.reload_patcher.start()
        self.scanner = self._create_scanner()
        self.integration = self._create_slack_integration()

    def tearDown(self) -> None:
        self.reload_patcher.stop()
        self.flag_patcher.stop()
        super().tearDown()

    @property
    def actions_url(self) -> str:
        return f"/api/projects/{self.team.id}/vision/actions/"

    def _create_scanner(self, team: Team | None = None, name: str = "my-scanner") -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=team or self.team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _create_slack_integration(self, team: Team | None = None) -> Integration:
        return Integration.objects.create(
            team=team or self.team,
            kind="slack",
            integration_id="T_TEST",
            config={"team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

    def _create_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "daily-summary",
            "scanner": str(self.scanner.id),
            "trigger_config": {"rrule": "FREQ=DAILY", "timezone": "UTC"},
            "selection": {"verdict": ["yes"]},
            "synthesis_config": {"prompt_guide": "keep it short"},
            "delivery_config": [
                {"type": "slack", "integration_id": self.integration.id, "channel": "#general"},
            ],
        }
        payload.update(overrides)
        return payload


class TestVisionActionViewSet(_VisionActionAPITestCase):
    def test_create_happy_path(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["name"], "daily-summary")
        self.assertEqual(data["scanner"], str(self.scanner.id))
        self.assertEqual(data["trigger_type"], "schedule")
        self.assertEqual(data["mode"], "group_summary")
        self.assertIsNotNone(data["next_run_at"])
        self.assertIsNone(data["last_run_at"])
        # Delivery is an internal_destination HogFunction (no HogFlow), so hog_flow_id stays null.
        self.assertIsNone(data["hog_flow_id"])
        self.assertEqual(data["created_by"]["id"], self.user.id)

        action = VisionAction.all_teams.get(id=data["id"])
        self.assertEqual(action.team_id, self.team.id)
        self.assertEqual(action.delivery_config[0]["integration_id"], self.integration.id)
        self.assertIsNotNone(action.next_run_at)

    def test_list(self) -> None:
        self.client.post(self.actions_url, data=self._create_payload(), format="json")
        resp = self.client.get(self.actions_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_list_filtered_by_scanner(self) -> None:
        # The per-scanner tab lists one scanner's actions via ?scanner=<id>.
        other_scanner = self._create_scanner(name="other-scanner")
        self.client.post(self.actions_url, data=self._create_payload(name="a"), format="json")
        self.client.post(
            self.actions_url, data=self._create_payload(name="b", scanner=str(other_scanner.id)), format="json"
        )

        resp = self.client.get(self.actions_url, data={"scanner": str(self.scanner.id)})
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual([r["name"] for r in results], ["a"])
        self.assertEqual(results[0]["scanner"], str(self.scanner.id))

    def test_list_with_malformed_scanner_param_returns_empty(self) -> None:
        # A non-UUID ?scanner= must not 500 (it would, building the UUID-column query) — return nothing.
        self.client.post(self.actions_url, data=self._create_payload(name="a"), format="json")
        resp = self.client.get(self.actions_url, data={"scanner": "not-a-uuid"})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["results"], [])

    def test_actions_flag_off_hides_endpoint(self) -> None:
        # `replay-vision-actions` gates the sub-feature even when product-level `replay-vision` is on.
        def _flags(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key != "replay-vision-actions"

        with patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", side_effect=_flags):
            list_resp = self.client.get(self.actions_url)
            create_resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(list_resp.status_code, 404, list_resp.content)
        self.assertEqual(create_resp.status_code, 404, create_resp.content)

    def test_retrieve(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.get(f"{self.actions_url}{created['id']}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], created["id"])

    def test_patch(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.patch(
            f"{self.actions_url}{created['id']}/", data={"name": "renamed", "enabled": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["name"], "renamed")
        self.assertFalse(resp.json()["enabled"])

    def test_delete(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.delete(f"{self.actions_url}{created['id']}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(VisionAction.all_teams.filter(id=created["id"]).exists())

    def test_reject_threshold_trigger(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(trigger_type="threshold"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("threshold", resp.json()["detail"].lower())

    def test_reject_per_observation_mode(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(mode="per_observation"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("per-observation", resp.json()["detail"].lower())

    def test_invalid_rrule(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(trigger_config={"rrule": "NOT_A_RULE", "timezone": "UTC"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_timezone(self) -> None:
        # An unknown TZ must be rejected at the API, not blow up later in the scheduling workflow.
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(trigger_config={"rrule": "FREQ=DAILY", "timezone": "Mars/Phobos"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_duplicate_name(self) -> None:
        self.client.post(self.actions_url, data=self._create_payload(), format="json")
        resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "name")

    def test_selection_valid_accepted(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(selection={"min_score": 0.5, "max_score": 1.0, "tags": ["a", "b"]}),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        action = VisionAction.all_teams.get(id=resp.json()["id"])
        self.assertEqual(action.selection["min_score"], 0.5)

    def test_selection_unknown_key_ignored(self) -> None:
        # The typed SelectionSerializer is the allowlist; unknown keys (including the retired
        # scanner_type/status/window_days) are dropped, not persisted.
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(selection={"scanner_type": "summarizer", "window_days": 3, "bogus_key": "x"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        action = VisionAction.all_teams.get(id=resp.json()["id"])
        for key in ("bogus_key", "scanner_type", "window_days"):
            self.assertNotIn(key, action.selection)

    @parameterized.expand(
        [
            ("min_above_max", {"min_score": 2.0, "max_score": 1.0}),
            ("unknown_verdict", {"verdict": ["maybe"]}),
            ("verdict_not_a_list", {"verdict": "yes"}),
        ]
    )
    def test_selection_invalid_rejected(self, _name: str, selection: dict[str, Any]) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(selection=selection), format="json")
        self.assertEqual(resp.status_code, 400, resp.content)


class TestVisionActionCrossTeamIDOR(_VisionActionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="other-org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other-team")
        self.other_scanner = self._create_scanner(team=self.other_team, name="other-scanner")
        self.other_integration = self._create_slack_integration(team=self.other_team)
        self.other_action = VisionAction.all_teams.create(
            team=self.other_team,
            scanner=self.other_scanner,
            name="other-action",
        )

    def test_cannot_retrieve_other_team_action(self) -> None:
        resp = self.client.get(f"{self.actions_url}{self.other_action.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_patch_other_team_action(self) -> None:
        resp = self.client.patch(f"{self.actions_url}{self.other_action.id}/", data={"name": "hijack"}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_delete_other_team_action(self) -> None:
        resp = self.client.delete(f"{self.actions_url}{self.other_action.id}/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(VisionAction.all_teams.filter(id=self.other_action.id).exists())

    def test_cannot_bind_other_team_scanner(self) -> None:
        resp = self.client.post(
            self.actions_url, data=self._create_payload(scanner=str(self.other_scanner.id)), format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_reference_other_team_integration(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(
                delivery_config=[{"type": "slack", "integration_id": self.other_integration.id, "channel": "#x"}]
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class TestVisionActionRunViewSet(_VisionActionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.action = VisionAction.all_teams.create(team=self.team, scanner=self.scanner, name="daily-summary")

    def runs_url(self, action_id: str | None = None) -> str:
        return f"/api/projects/{self.team.id}/vision/actions/{action_id or self.action.id}/runs/"

    def _create_run(self, action: VisionAction | None = None, **overrides: Any) -> VisionActionRun:
        defaults: dict[str, Any] = {
            "team": self.team,
            "vision_action": action or self.action,
            "idempotency_key": f"key-{VisionActionRun.all_teams.count()}",
            "status": VisionActionRunStatus.COMPLETED,
        }
        defaults.update(overrides)
        return VisionActionRun.all_teams.create(**defaults)

    def _create_observation(
        self,
        session_id: str,
        *,
        summary: str = "churned",
        title: str | None = "Checkout",
        email: str | None = "user@example.com",
        scanner: ReplayScanner | None = None,
    ) -> ReplayObservation:
        # team_id is copied from the scanner by ReplayObservation.save(); don't pass it.
        return ReplayObservation.objects.create(
            scanner=scanner or self.scanner,
            session_id=session_id,
            recording_subject_email=email,
            scanner_result={"model_output": {"summary": summary, **({"title": title} if title else {})}},
        )

    def test_list_runs_for_action(self) -> None:
        self._create_run(status=VisionActionRunStatus.COMPLETED, synthesized_markdown="# Themes", observation_count=3)
        self._create_run(status=VisionActionRunStatus.SKIPPED, error={"skip_reason": "nothing to summarize"})

        resp = self.client.get(self.runs_url())
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.json()["results"]
        self.assertEqual(len(results), 2)
        completed = next(r for r in results if r["status"] == "completed")
        self.assertEqual(completed["observation_count"], 3)
        self.assertIsNone(completed["error_reason"])
        # The list stays light — the report body + observations are only fetched on retrieve.
        self.assertNotIn("synthesized_markdown", completed)
        self.assertNotIn("observations", completed)

    def test_retrieve_returns_summary_and_observations_in_stored_order(self) -> None:
        obs_a = self._create_observation("sess-a", title="Checkout")
        obs_b = self._create_observation("sess-b", title="Onboarding")
        # observation_ids is the summary order; the API must preserve it rather than DB order.
        run = self._create_run(
            status=VisionActionRunStatus.COMPLETED,
            synthesized_markdown="# Themes",
            observation_count=2,
            observation_ids=[str(obs_b.id), str(obs_a.id)],
        )

        body = self.client.get(f"{self.runs_url()}{run.id}/").json()
        self.assertEqual(body["synthesized_markdown"], "# Themes")
        self.assertEqual([o["id"] for o in body["observations"]], [str(obs_b.id), str(obs_a.id)])
        # 1-based position in summary order — what the report's `[obs N]` citations reference.
        self.assertEqual([o["index"] for o in body["observations"]], [1, 2])
        self.assertEqual(body["observations"][0]["session_id"], "sess-b")
        self.assertEqual(body["observations"][0]["title"], "Onboarding")
        self.assertEqual(body["observations"][1]["recording_subject_email"], "user@example.com")

    def test_retrieve_does_not_resolve_cross_team_observation_ids(self) -> None:
        # A stray id from another team stored on the run must never resolve — ReplayObservation isn't fail-closed.
        other_team = Team.objects.create(organization=self.organization, name="rv-other-team")
        other_scanner = self._create_scanner(team=other_team, name="rv-other-scanner")
        foreign = self._create_observation("foreign", scanner=other_scanner)
        mine = self._create_observation("mine")
        run = self._create_run(
            status=VisionActionRunStatus.COMPLETED,
            synthesized_markdown="# Themes",
            observation_ids=[str(foreign.id), str(mine.id)],
        )

        body = self.client.get(f"{self.runs_url()}{run.id}/").json()
        self.assertEqual([o["id"] for o in body["observations"]], [str(mine.id)])
        # `mine` was second in observation_ids; dropping the unresolved foreign id must leave a gap, not
        # renumber it to 1 — otherwise its `index` would no longer match the `[obs 2]` citation in the report.
        self.assertEqual(body["observations"][0]["index"], 2)

    @parameterized.expand(
        [
            # (status, error, expected copy)
            (
                VisionActionRunStatus.SKIPPED,
                {"skip_reason": "skipped_empty"},
                "No new observations in this window to summarize.",
            ),
            # Historical run rows (pre-#66892) stored the old enum; the alias must still humanize.
            (
                VisionActionRunStatus.SKIPPED,
                {"skip_reason": "no_delivery_flow"},
                "No delivery destination is configured for this action.",
            ),
            # Abort reasons carry FAILED status — the copy must not contradict the "failed" banner by saying "Skipped".
            (
                VisionActionRunStatus.FAILED,
                {"aborted": "aborted_no_consent"},
                "AI data processing isn't enabled for this organization.",
            ),
        ]
    )
    def test_error_reason_humanized(self, status: str, error: dict[str, Any], expected: str) -> None:
        # A raw engine skip/abort reason is mapped to human copy, not surfaced verbatim.
        run = self._create_run(status=status, error=error)
        resp = self.client.get(f"{self.runs_url()}{run.id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["error_reason"], expected)
        self.assertNotIn("Skipped", resp.json()["error_reason"])

    def test_failed_run_error_reason_does_not_leak_raw_exception(self) -> None:
        # The engine stamps error["message"] with raw exception text (str(e)[:500]); the API must not
        # echo it to callers — a failed run surfaces a generic reason instead.
        run = self._create_run(
            status=VisionActionRunStatus.FAILED,
            error={"message": "Traceback: KeyError 'secret_token' in synthesize at line 42"},
        )
        resp = self.client.get(f"{self.runs_url()}{run.id}/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn("secret_token", resp.json()["error_reason"])
        self.assertEqual(resp.json()["error_reason"], "This run failed while generating the summary.")

    def test_runs_scoped_to_their_action(self) -> None:
        other_action = VisionAction.all_teams.create(team=self.team, scanner=self.scanner, name="other-action")
        mine = self._create_run(self.action)
        self._create_run(other_action)

        results = self.client.get(self.runs_url()).json()["results"]
        self.assertEqual([r["id"] for r in results], [str(mine.id)])

    def test_malformed_action_id_returns_404(self) -> None:
        resp = self.client.get(self.runs_url("not-a-uuid"))
        self.assertEqual(resp.status_code, 404)

    def test_flag_off_hides_endpoint(self) -> None:
        self._create_run()

        def _flags(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key != "replay-vision-actions"

        with patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", side_effect=_flags):
            resp = self.client.get(self.runs_url())
        self.assertEqual(resp.status_code, 404, resp.content)


class TestVisionActionRunCrossTeamIDOR(_VisionActionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="other-org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other-team")
        self.other_scanner = self._create_scanner(team=self.other_team, name="other-scanner")
        self.other_action = VisionAction.all_teams.create(
            team=self.other_team, scanner=self.other_scanner, name="other-action"
        )
        VisionActionRun.all_teams.create(
            team=self.other_team, vision_action=self.other_action, idempotency_key="other-run"
        )

    def test_cannot_list_other_team_action_runs(self) -> None:
        # The action belongs to another team, so the nested route must 404 rather than leak its runs.
        resp = self.client.get(f"/api/projects/{self.team.id}/vision/actions/{self.other_action.id}/runs/")
        self.assertEqual(resp.status_code, 404)
