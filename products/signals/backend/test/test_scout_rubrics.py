from __future__ import annotations

import json
import asyncio
from collections.abc import Awaitable
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync, sync_to_async
from parameterized import parameterized

from posthog.models import Team

from products.signals.backend.models import SignalScoutConfig, SignalScoutRun
from products.signals.backend.presentation.scout_rubrics import ScoutRubricSaveSerializer
from products.signals.backend.scout_harness.prompt import build_run_prompt
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
from products.signals.backend.scout_harness.rubrics_runner import read_selection_output, run_rubric_generation
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import Task, TaskRun


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
            ("duplicate", [0, 0], None),
            ("out_of_range", [2], None),
            ("preserves_draft_order", [1, 0], [0, 1]),
        ]
    )
    def test_selection_keeps_whole_draft_items_in_order(
        self, _name: str, indices: list[int], expected: list[int] | None
    ) -> None:
        criterion = custom_criterion().model_dump(exclude={"id", "source", "enabled"})
        draft = ScoutRubricSuggestionBatch(
            summary="Draft criteria.",
            suggestions=[
                ScoutRubricSuggestion(**criterion),
                ScoutRubricSuggestion(**{**criterion, "title": "A separate judgment"}),
            ],
        )
        output = json.dumps({"summary": "Selected additions.", "keep_indices": indices})
        if expected is None:
            with self.assertRaises(ValueError):
                read_selection_output(output, draft)
        else:
            selected = read_selection_output(output, draft)
            self.assertEqual(selected.summary, "Selected additions.")
            self.assertEqual(selected.suggestions, [draft.suggestions[index] for index in expected])

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
        self.team_patch = patch("products.signals.backend.presentation.scout_rubrics.RUBRIC_TEAM_ID", self.team.id)
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
        with patch(
            "products.signals.backend.presentation.scout_rubrics.RUBRIC_TEAM_ID", -1 if different_team else self.team.id
        ):
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
        with patch("products.signals.backend.scout_harness.rubrics.sync_connect", return_value=client):
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
        config = reserve_generation(self.team.id, str(self.config.id)).config
        old = read_rubric_state(config).generation
        assert old is not None
        old.requested_at = timezone.now() - GENERATION_TIMEOUT - timedelta(seconds=1)
        update_generation(self.team.id, str(self.config.id), old)
        self.assertEqual(self.client.get(self.url).json()["generation"]["status"], "failed")
        with patch(
            "products.signals.backend.scout_harness.rubrics.sync_connect",
            return_value=SimpleNamespace(start_workflow=AsyncMock()),
        ):
            response = self.client.post(self.url + "generate/")
        self.assertEqual(response.status_code, 202)
        self.assertNotEqual(response.json()["generation"]["id"], old.id)
        old.status = ScoutRubricGenerationStatus.COMPLETED
        self.assertFalse(update_generation(self.team.id, str(self.config.id), old))
        self.assertEqual(self.client.get(self.url).json()["generation"]["status"], "queued")

    @parameterized.expand(
        [
            ("workflow_start", True, None),
            ("limit_check", False, "incr"),
            ("refund", True, "decr"),
        ]
    )
    def test_dispatch_failure_keeps_rubric_and_allows_retry(
        self, _name: str, connect_fails: bool, failing_cache_call: str | None
    ) -> None:
        save_rubric(self.team.id, str(self.config.id), revision=0, criteria=[custom_criterion()])
        cache = MagicMock()
        cache.incr.return_value = 1
        if failing_cache_call:
            getattr(cache, failing_cache_call).side_effect = ConnectionError("cache offline")
        client = SimpleNamespace(start_workflow=AsyncMock())
        with (
            patch("products.signals.backend.scout_chat.cache", cache),
            patch(
                "products.signals.backend.scout_harness.rubrics.sync_connect",
                side_effect=RuntimeError("offline") if connect_fails else None,
                return_value=client,
            ),
        ):
            response = self.client.post(self.url + "generate/")
        self.assertEqual(response.status_code, 500)
        client.start_workflow.assert_not_awaited()
        state = self.client.get(self.url).json()
        self.assertEqual(state["generation"]["status"], "failed")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["criteria"][0]["id"], "custom-checkout")

    @parameterized.expand([("limit_reached", 21, False, 429), ("dispatch_failed", 1, True, 500)])
    def test_refused_generation_keeps_completed_suggestions(
        self, _name: str, attempts: int, connect_fails: bool, expected_status: int
    ) -> None:
        generation = read_rubric_state(reserve_generation(self.team.id, str(self.config.id)).config).generation
        assert generation is not None
        generation.status = ScoutRubricGenerationStatus.COMPLETED
        generation.suggestions = default_criteria()[:1]
        generation.completed_at = timezone.now()
        update_generation(self.team.id, str(self.config.id), generation)
        cache = MagicMock()
        cache.incr.return_value = attempts
        with (
            patch("products.signals.backend.scout_chat.cache", cache),
            patch(
                "products.signals.backend.scout_harness.rubrics.sync_connect",
                side_effect=RuntimeError("offline") if connect_fails else None,
                return_value=SimpleNamespace(start_workflow=AsyncMock()),
            ),
        ):
            response = self.client.post(self.url + "generate/")
        self.assertEqual(response.status_code, expected_status)
        restored = self.client.get(self.url).json()["generation"]
        self.assertEqual(restored["id"], generation.id)
        self.assertEqual(restored["status"], "completed")
        self.assertEqual(len(restored["suggestions"]), 1)

    def test_generation_requires_ai_consent(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.assertEqual(self.client.post(self.url + "generate/").status_code, 403)
        self.config.refresh_from_db()
        self.assertIsNone(self.config.rubrics)

    @parameterized.expand(
        [
            ("completed", None, False),
            ("description_only", None, False),
            ("saved_choices", None, False),
            ("saved_during_draft", None, False),
            ("complete_context", None, False),
            ("truncated_context", None, False),
            ("report_emit", None, False, "emit"),
            ("report_edit", None, False, "edit"),
            ("report_both", None, False, "both"),
            ("start_failed", "start", False),
            ("selection_dispatch_value_error", "review", False),
            ("selection_timeout", "timeout", False),
            ("selection_cancelled", "cancelled", False),
            ("malformed_json_recovered", None, False),
            ("overlong_summary_recovered", None, False),
            ("schema_recovered", None, False),
            ("twice_invalid", "format", False),
            ("cleanup_failed", None, True),
            ("subset_selection", None, False),
            ("empty_selection", None, False),
            ("selection_recovered", None, False),
            ("both_stages_invalid", "shared_repair", False),
            ("oversized_selection", "selection_size", False),
        ]
    )
    def test_agent_output_is_saved_as_suggestions_without_changing_rubric(
        self, name: str, failed_stage: str | None, cleanup_fails: bool, report_channel: str = "none"
    ) -> None:
        body = "" if name == "description_only" else "Inspect checkout failures and report reproducible issues."
        bounded_context = name in {"complete_context", "truncated_context"}
        truncated = name == "truncated_context"
        if bounded_context:
            body = "x" * 60_000 + (" omitted instruction" if truncated else "")
        allowed_tools = {
            "none": [],
            "emit": ["emit_report"],
            "edit": ["edit_report"],
            "both": ["emit_report", "edit_report"],
        }[report_channel]
        skill = LLMSkill.objects.create(
            team=self.team,
            name=self.config.skill_name,
            description="Check the checkout flow.",
            body=body,
            version=2 if bounded_context else 1,
            allowed_tools=allowed_tools,
        )
        normal_scout_prompt = ""
        if report_channel != "none":
            normal_scout_prompt = build_run_prompt(
                load_skill_for_run(self.team, self.config.skill_name),
                run_id=str(uuid4()),
                team_id=self.team.id,
                started_at=timezone.now(),
            )
        reference_paths: list[str] = []
        report_ids: list[str] = []
        if bounded_context:
            reference_paths = [f"references/{index:02d}.md" for index in range(21 if truncated else 20)]
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(
                        skill=skill,
                        path=path,
                        content="r" * (45_001 if truncated and index == 1 else 15_000),
                    )
                    for index, path in enumerate(reference_paths)
                ]
            )
            if not truncated:
                other_team = Team.objects.create(organization=self.organization)
                for reference_team, version in [(self.team, 1), (other_team, 99)]:
                    other_skill = LLMSkill.objects.create(
                        team=reference_team,
                        name=self.config.skill_name,
                        body="Unrelated version or project instructions.",
                        version=version,
                        is_latest=reference_team != self.team,
                    )
                    LLMSkillFile.objects.create(
                        skill=other_skill, path=reference_paths[0], content="Must not reach this generation."
                    )
            task = Task.objects.create(team=self.team, title="Scout history", description="Check the checkout flow.")
            task_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)
            report_ids = [str(uuid4()) for _ in range(6 if truncated else 5)]
            SignalScoutRun.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                task_run=task_run,
                scout_config=self.config,
                skill_name=self.config.skill_name,
                skill_version=1,
                summary="s" * 3000 + (" omitted qualification" if truncated else ""),
                emitted_report_ids=report_ids,
            )
        expected_criteria = default_criteria()
        if name == "saved_choices":
            expected_criteria[0].pass_condition = "Reported checkout counts match the inspected evidence."
            expected_criteria[0].applicability = "When the scout reports checkout counts."
            expected_criteria[1].enabled = False
            enabled_custom = custom_criterion()
            disabled_custom = custom_criterion().model_copy(update={"id": "custom-disabled", "enabled": False})
            expected_criteria.extend([enabled_custom, disabled_custom])
        elif name == "oversized_selection":
            expected_criteria.extend(
                custom_criterion().model_copy(update={"id": f"custom-large-{index}", "pass_condition": "🙂" * 2000})
                for index in range(12)
            )
        if name in {"saved_choices", "oversized_selection"}:
            save_rubric(self.team.id, str(self.config.id), revision=0, criteria=expected_criteria)
        config = reserve_generation(self.team.id, str(self.config.id)).config
        generation = read_rubric_state(config).generation
        assert generation is not None
        criterion = custom_criterion()
        reviewed_batch = ScoutRubricSuggestionBatch(
            summary="Reviewed criteria based on the instructions. There are no recent runs.",
            suggestions=[ScoutRubricSuggestion(**criterion.model_dump(exclude={"id", "source", "enabled"}))],
        )
        if name == "subset_selection":
            reviewed_batch.suggestions.append(
                reviewed_batch.suggestions[0].model_copy(
                    update={
                        "title": "Second judgment",
                        "pass_condition": "The required checkout investigation is completed.",
                    }
                )
            )
        kept_indices = [] if name == "empty_selection" else [1] if name == "subset_selection" else [0]
        selection_summary = "Suggestions after comparison with the original saved criteria."
        selection_json = json.dumps({"summary": selection_summary, "keep_indices": kept_indices})
        reviewed_json = reviewed_batch.model_dump_json()
        review_outputs: list[str | BaseException] = [reviewed_json]
        if name == "malformed_json_recovered":
            review_outputs = ['{"summary":', reviewed_json]
        elif name == "overlong_summary_recovered":
            review_outputs = [json.dumps({**reviewed_batch.model_dump(), "summary": "x" * 2001}), reviewed_json]
        elif name == "schema_recovered":
            review_outputs = [
                json.dumps({"summary": "Synthetic invalid result", "suggestions": "not a list"}),
                reviewed_json,
            ]
        elif failed_stage == "format":
            review_outputs = ["This is not JSON", '{"summary":']
        elif failed_stage == "review":
            review_outputs = [reviewed_json, ValueError("Follow-up dispatch failed")]
        elif failed_stage == "timeout":
            review_outputs = [reviewed_json, TimeoutError("Follow-up timed out")]
        elif failed_stage == "cancelled":
            review_outputs = [reviewed_json, asyncio.CancelledError()]
        if name == "selection_recovered":
            review_outputs = [reviewed_json, '{"summary":', selection_json]
        elif name == "both_stages_invalid":
            review_outputs = ["Invalid initial draft", reviewed_json, "Invalid selection"]
        elif failed_stage is None or failed_stage == "start":
            review_outputs.append(selection_json)
        session = SimpleNamespace(
            send_followup_raw=AsyncMock(side_effect=review_outputs[1:]),
            end=AsyncMock(side_effect=RuntimeError("Sandbox unavailable") if cleanup_fails else None),
        )
        run_id = uuid4()

        async def start(**kwargs: object) -> tuple[SimpleNamespace, str]:
            prompt = kwargs["prompt"]
            assert isinstance(prompt, str)
            bundle_text, schema_text = prompt.split("\nUntrusted source bundle:\n", 1)[1].split("\nResult schema:\n", 1)
            bundle = json.loads(bundle_text)
            scout_context = bundle["scout_context"]
            self.assertEqual(json.loads(schema_text), ScoutRubricSuggestionBatch.model_json_schema())
            references = bundle["reference_texts"]
            if bounded_context:
                self.assertEqual([item["path"] for item in references], reference_paths[: 2 if truncated else 4])
                self.assertEqual(
                    [len(item["content"]) for item in references], [15_000, 45_000] if truncated else [15_000] * 4
                )
                self.assertTrue(all(set(item["content"]) == {"r"} for item in references))
                self.assertEqual(bundle["reference_limits"]["omitted_files"], 19 if truncated else 16)
                self.assertEqual(
                    bundle["reference_limits"]["truncated_files"], [reference_paths[1]] if truncated else []
                )
            else:
                self.assertEqual(references, [])
                self.assertEqual(bundle["reference_limits"], {"omitted_files": 0, "truncated_files": []})
            self.assertEqual(scout_context["description"], "Check the checkout flow.")
            self.assertEqual(scout_context["report_channel"], report_channel)
            disposition = scout_context["report_disposition_instructions"]
            if report_channel == "none":
                self.assertEqual(disposition, "")
            else:
                self.assertIn(disposition, normal_scout_prompt)
                self.assertIn(
                    {
                        "emit": "This run can't edit reports",
                        "edit": "This run updates reports that already exist; it can't author new ones.",
                        "both": "Edit when it already exists *and is still live*",
                    }[report_channel],
                    disposition,
                )
            self.assertEqual(scout_context["instructions"], body[:60_000])
            self.assertEqual(scout_context["instructions_truncated"], truncated)
            self.assertEqual(scout_context["reference_files"], reference_paths[:20])
            self.assertEqual(scout_context["reference_files_truncated"], truncated)
            if bounded_context:
                self.assertEqual(len(scout_context["recent_runs"]), 1)
                recent_run = scout_context["recent_runs"][0]
                self.assertEqual(recent_run["summary"], "s" * 3000)
                self.assertEqual(recent_run["summary_truncated"], truncated)
                self.assertEqual(recent_run["emitted_report_ids"], report_ids[:5])
                self.assertEqual(recent_run["emitted_report_ids_truncated"], truncated)
            else:
                self.assertEqual(scout_context["recent_runs"], [])
            self.assertEqual(
                scout_context["saved_criteria"],
                [
                    item.model_dump(mode="json")
                    for item in expected_criteria
                    if not (item.source == ScoutRubricSource.CUSTOM and item.enabled)
                ],
            )
            self.assertNotIn("shared_defaults", scout_context)
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
            if name == "saved_during_draft":
                edited_criteria = default_criteria()
                edited_criteria[1].enabled = False
                edited_criteria.append(custom_criterion())
                await sync_to_async(save_rubric)(
                    self.team.id, str(self.config.id), revision=0, criteria=edited_criteria
                )
                expected_criteria[:] = edited_criteria
            if failed_stage == "start":
                raise ValueError("Draft failed")
            initial_output = review_outputs[0]
            assert isinstance(initial_output, str)
            return session, initial_output

        with (
            patch("products.signals.backend.scout_harness.rubrics_runner.RUBRIC_TEAM_ID", self.team.id),
            patch(
                "products.signals.backend.scout_harness.rubrics_runner.MultiTurnSession.start_raw", side_effect=start
            ) as start_session,
        ):
            if failed_stage == "cancelled":
                with self.assertRaises(asyncio.CancelledError):
                    async_to_sync(run_rubric_generation)(self.team.id, str(self.config.id), generation.id, self.user.id)
            else:
                async_to_sync(run_rubric_generation)(self.team.id, str(self.config.id), generation.id, self.user.id)
        start_session.assert_awaited_once()
        expected_followups = 0 if failed_stage == "start" else len(review_outputs) - 1
        self.assertEqual(session.send_followup_raw.await_count, expected_followups)
        self.config.refresh_from_db()
        state = read_rubric_state(self.config)
        self.assertEqual(
            state.revision, 1 if name in {"saved_choices", "saved_during_draft", "oversized_selection"} else 0
        )
        self.assertEqual(state.criteria, expected_criteria)
        assert state.generation is not None
        self.assertEqual(state.generation.task_run_id, str(run_id))
        self.assertEqual(state.generation.status, "failed" if failed_stage else "completed")
        self.assertEqual(len(state.generation.suggestions), 0 if failed_stage else len(kept_indices))
        if not failed_stage:
            self.assertEqual(state.generation.summary, selection_summary)
            self.assertEqual(
                [item.model_dump(exclude={"id", "source", "enabled"}) for item in state.generation.suggestions],
                [reviewed_batch.suggestions[index].model_dump() for index in kept_indices],
            )
            selection_calls = [
                call
                for call in session.send_followup_raw.call_args_list
                if call.kwargs["label"] == "rubric_saved_selection"
            ]
            self.assertEqual(len(selection_calls), 1)
            selection_prompt = selection_calls[0].args[0]
            saved_text, numbered_text = selection_prompt.split("\nUntrusted saved criteria:\n", 1)[1].split(
                "\nNumbered draft criteria:\n", 1
            )
            self.assertEqual(json.loads(saved_text), [item.model_dump(mode="json") for item in expected_criteria])
            self.assertEqual(
                json.loads(numbered_text.split("\nSelection schema:\n", 1)[0]),
                [
                    {"index": index, "criterion": item.model_dump(mode="json")}
                    for index, item in enumerate(reviewed_batch.suggestions)
                ],
            )
            if name == "selection_recovered":
                correction = session.send_followup_raw.call_args_list[-1].args[0]
                schema_text, indices_text = correction.split("\nResult schema:\n", 1)[1].split(
                    "\nValid draft indices:\n", 1
                )
                self.assertEqual(set(json.loads(schema_text)["required"]), {"summary", "keep_indices"})
                self.assertEqual(json.loads(indices_text), [0])
        if failed_stage != "start":
            session.end.assert_awaited_once_with(
                status="failed" if failed_stage else "completed",
                error="Rubric generation failed" if failed_stage else None,
            )
