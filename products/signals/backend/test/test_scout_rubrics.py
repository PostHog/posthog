from __future__ import annotations

from collections.abc import Awaitable
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.rubrics import (
    GENERATION_TIMEOUT,
    ScoutRubricCriterion,
    ScoutRubricGenerationStatus,
    ScoutRubricSource,
    ScoutRubricSuggestion,
    ScoutRubricSuggestionBatch,
    default_criteria,
    read_rubric_state,
    reserve_generation,
    save_rubric,
    update_generation,
)
from products.signals.backend.scout_harness.rubrics_runner import run_rubric_generation
from products.signals.backend.scout_rubrics_api import ScoutRubricSaveSerializer
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def custom_criterion() -> ScoutRubricCriterion:
    return ScoutRubricCriterion(
        id="custom-checkout",
        title="Verify checkout failures",
        description="Check whether reported checkout failures affect completed purchases.",
        pass_condition="A finding connects a checkout failure to the affected purchase flow using inspected evidence.",
        applicability="When checkout failures were investigated.",
        enabled=True,
        source=ScoutRubricSource.CUSTOM,
    )


class TestRubricValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("duplicate", "duplicate"),
            ("too_many", "too_many"),
            ("empty_condition", "empty_condition"),
            ("forged_default", "forged_default"),
            ("bad_custom_id", "bad_custom_id"),
        ]
    )
    def test_invalid_rubrics_are_rejected(self, _name: str, variant: str) -> None:
        item = custom_criterion().model_dump(mode="json")
        criteria = [item]
        if variant == "duplicate":
            criteria = [item, item]
        elif variant == "too_many":
            criteria = [{**item, "id": f"custom-{index}"} for index in range(31)]
        elif variant == "empty_condition":
            item["pass_condition"] = " "
        elif variant == "forged_default":
            item["source"] = "default"
        elif variant == "bad_custom_id":
            item["id"] = "unreserved"
        serializer = ScoutRubricSaveSerializer(data={"revision": 0, "criteria": criteria})
        self.assertFalse(serializer.is_valid())


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestScoutRubricsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.config = SignalScoutConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, skill_name="signals-scout-checkout", enabled=False
        )
        self.url = f"/api/projects/{self.team.id}/signals/scout/rubrics/{self.config.id}/"
        self.team_patch = patch("products.signals.backend.scout_rubrics_api.RUBRIC_TEAM_ID", self.team.id)
        self.team_patch.start()
        self.addCleanup(self.team_patch.stop)

    def test_defaults_are_read_only_until_saved_and_stale_saves_cannot_overwrite(self) -> None:
        initial = self.client.get(self.url)
        self.assertEqual(initial.status_code, 200)
        body = initial.json()
        self.assertEqual(body["revision"], 0)
        self.assertTrue(all(item["enabled"] for item in body["criteria"]))
        self.config.refresh_from_db()
        self.assertIsNone(self.config.rubrics)

        body["criteria"][0]["enabled"] = False
        body["criteria"][0]["pass_condition"] = "Check each conclusion against the cited evidence."
        saved = self.client.put(self.url, {"revision": 0, "criteria": body["criteria"]})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["revision"], 1)
        stale = self.client.put(self.url, {"revision": 0, "criteria": []})
        self.assertEqual(stale.status_code, 409)
        reloaded = self.client.get(self.url).json()
        self.assertFalse(reloaded["criteria"][0]["enabled"])
        self.assertEqual(reloaded["criteria"][0]["pass_condition"], body["criteria"][0]["pass_condition"])

    @parameterized.expand([("staff", False, False), ("team", True, True)])
    def test_internal_gate_covers_every_action(self, _name: str, staff: bool, different_team: bool) -> None:
        self.user.is_staff = staff
        self.user.save(update_fields=["is_staff"])
        with patch("products.signals.backend.scout_rubrics_api.RUBRIC_TEAM_ID", -1 if different_team else self.team.id):
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.put(self.url, {"revision": 0, "criteria": []}).status_code, 403)
            self.assertEqual(self.client.post(self.url + "generate/").status_code, 403)

    def test_other_projects_config_is_not_readable_or_writable(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        other = SignalScoutConfig.objects.for_team(other_team.id).create(team_id=other_team.id, skill_name="other")
        url = f"/api/projects/{self.team.id}/signals/scout/rubrics/{other.id}/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.put(url, {"revision": 0, "criteria": []}).status_code, 404)
        self.assertEqual(self.client.post(url + "generate/").status_code, 404)

    def test_save_uses_criterion_validation(self) -> None:
        criterion = custom_criterion().model_dump(mode="json")
        criterion["pass_condition"] = ""
        response = self.client.put(self.url, {"revision": 0, "criteria": [criterion]})
        self.assertEqual(response.status_code, 400)

    def test_generate_is_deduplicated_and_preserves_concurrent_manual_save(self) -> None:
        client = SimpleNamespace(start_workflow=AsyncMock())
        with patch("products.signals.backend.scout_rubrics_api.sync_connect", return_value=client):
            first = self.client.post(self.url + "generate/")
            second = self.client.post(self.url + "generate/")
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["generation"]["id"], second.json()["generation"]["id"])
        self.assertEqual(client.start_workflow.await_count, 1)
        self.config.refresh_from_db()
        generation = read_rubric_state(self.config).generation
        assert generation is not None
        self.client.put(self.url, {"revision": 0, "criteria": [custom_criterion().model_dump(mode="json")]})
        generation.status = ScoutRubricGenerationStatus.COMPLETED
        generation.suggestions = default_criteria()[:1]
        generation.completed_at = timezone.now()
        update_generation(self.team.id, str(self.config.id), generation)
        reloaded = self.client.get(self.url).json()
        self.assertEqual(reloaded["revision"], 1)
        self.assertEqual(reloaded["criteria"][0]["id"], "custom-checkout")
        self.assertEqual(reloaded["generation"]["status"], "completed")
        self.assertEqual(len(reloaded["generation"]["suggestions"]), 1)

    def test_timed_out_generation_is_retryable_and_old_worker_cannot_replace_it(self) -> None:
        config, _ = reserve_generation(self.team.id, str(self.config.id))
        old = read_rubric_state(config).generation
        assert old is not None
        old.requested_at = timezone.now() - GENERATION_TIMEOUT - timedelta(seconds=1)
        update_generation(self.team.id, str(self.config.id), old)
        self.assertEqual(self.client.get(self.url).json()["generation"]["status"], "failed")
        with patch(
            "products.signals.backend.scout_rubrics_api.sync_connect",
            return_value=SimpleNamespace(start_workflow=AsyncMock()),
        ):
            response = self.client.post(self.url + "generate/")
        self.assertEqual(response.status_code, 202)
        self.assertNotEqual(response.json()["generation"]["id"], old.id)
        old.status = ScoutRubricGenerationStatus.COMPLETED
        self.assertFalse(update_generation(self.team.id, str(self.config.id), old))
        self.assertEqual(self.client.get(self.url).json()["generation"]["status"], "queued")

    def test_dispatch_failure_keeps_rubric_and_allows_retry(self) -> None:
        save_rubric(self.team.id, str(self.config.id), revision=0, criteria=[custom_criterion()])
        with patch("products.signals.backend.scout_rubrics_api.sync_connect", side_effect=RuntimeError("offline")):
            response = self.client.post(self.url + "generate/")
        self.assertEqual(response.status_code, 500)
        state = self.client.get(self.url).json()
        self.assertEqual(state["generation"]["status"], "failed")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["criteria"][0]["id"], "custom-checkout")

    def test_generation_requires_ai_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.assertEqual(self.client.post(self.url + "generate/").status_code, 403)
        self.config.refresh_from_db()
        self.assertIsNone(self.config.rubrics)

    @parameterized.expand([("completed", False, False), ("failed", True, False), ("cleanup_failed", False, True)])
    def test_agent_output_is_saved_as_suggestions_without_changing_rubric(
        self, _name: str, fail: bool, cleanup_fails: bool
    ) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name=self.config.skill_name,
            description="Check the checkout flow.",
            body="Inspect checkout failures and report reproducible issues.",
            version=1,
        )
        config, _ = reserve_generation(self.team.id, str(self.config.id))
        generation = read_rubric_state(config).generation
        assert generation is not None
        session = SimpleNamespace(
            end=AsyncMock(side_effect=RuntimeError("Sandbox unavailable") if cleanup_fails else None)
        )
        run_id = uuid4()

        async def start(**kwargs: object) -> tuple[SimpleNamespace, ScoutRubricSuggestionBatch]:
            self.assertEqual(kwargs["origin_product"], "scout_suggestions")
            context = kwargs["context"]
            assert isinstance(context, CustomPromptSandboxContext)
            self.assertEqual(
                context.posthog_mcp_scopes,
                ["user:read", "project:read", "llm_skill:read", "signal_scout:read", "task:read"],
            )
            self.assertFalse(context.github_read_access)
            self.assertIn(context.initial_permission_mode, ("full-access", "bypassPermissions"))
            self.assertEqual(context.sandbox_timeout_seconds, 17 * 60)
            self.assertEqual(kwargs["mcp_gateway_server_ids"], [])
            self.assertIsNone(kwargs.get("output_schema"))
            callback = kwargs["on_task_run_created"]
            assert callable(callback)
            result = callback(SimpleNamespace(id=run_id, task_id=uuid4()))
            assert isinstance(result, Awaitable)
            await result
            if fail:
                raise ValueError("Invalid output")
            criterion = custom_criterion()
            return session, ScoutRubricSuggestionBatch(
                summary="Criteria based on the instructions. There are no recent runs.",
                suggestions=[ScoutRubricSuggestion(**criterion.model_dump(exclude={"id", "source", "enabled"}))],
            )

        with (
            patch("products.signals.backend.scout_harness.rubrics_runner.RUBRIC_TEAM_ID", self.team.id),
            patch("products.signals.backend.scout_harness.rubrics_runner.MultiTurnSession.start", side_effect=start),
        ):
            async_to_sync(run_rubric_generation)(self.team.id, str(self.config.id), generation.id, self.user.id)
        self.config.refresh_from_db()
        state = read_rubric_state(self.config)
        self.assertEqual(state.revision, 0)
        self.assertEqual([item.id for item in state.criteria], [item.id for item in default_criteria()])
        assert state.generation is not None
        self.assertEqual(state.generation.task_run_id, str(run_id))
        self.assertEqual(state.generation.status, "failed" if fail else "completed")
        self.assertEqual(len(state.generation.suggestions), 0 if fail else 1)
