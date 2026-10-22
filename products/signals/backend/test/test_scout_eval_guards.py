from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from unittest import TestCase
from unittest.mock import call, patch

from django.test import override_settings

from parameterized import parameterized

from products.posthog_ai.eval_harness.environment.storage import file_sha256
from products.signals.backend.scout_harness.eval_environment.prompt import (
    NativeScoutPrompt,
    RecordedScoutPrompt,
    read_recorded_prompt,
)
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentSeed,
    ScoutEnvironmentSkill,
    ScoutPromptTransformation,
)
from products.signals.backend.scout_harness.eval_environment.trials import (
    BudgetLedger,
    EvaluationPlan,
    FrozenEnvironment,
    ScoutEvaluationTrials,
    TrialVariant,
    assert_local_url,
    write_private_json,
)
from products.signals.backend.scout_harness.prompt import HARNESS_PROMPT_VERSION


class TestScoutEvaluationGuards(TestCase):
    def make_trials(self) -> ScoutEvaluationTrials:
        trials = object.__new__(ScoutEvaluationTrials)
        trials.seed = ScoutEnvironmentSeed(
            environment_id="synthetic",
            team_id=7,
            user_id=7,
            config_id=uuid4(),
            skill_id=uuid4(),
            identity_map={},
            time_delta_seconds=0,
            steering="",
        )
        return trials

    @parameterized.expand(
        [
            ("unchanged", None),
            ("override", "Unset"),
            ("harness", "harness changed"),
            ("steering", "case does not match"),
            ("file", "changed"),
        ]
    )
    def test_native_prompt_uses_the_frozen_case_and_current_harness_without_a_recorded_override(
        self, change: str, error: str | None
    ) -> None:
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            cutoff = datetime(2030, 1, 1, tzinfo=UTC)
            case = ScoutEnvironmentCase(
                environment_id="example",
                source_cutoff=cutoff,
                checkpoint=cutoff,
                prompt_mode="native",
                steering="Review recent events.",
                skill=ScoutEnvironmentSkill(
                    id=uuid4(), name="example-scout", body="Review example events.", version=1, origin="custom"
                ),
            )
            seed = self.make_trials().seed.model_copy(
                update={"environment_id": case.environment_id, "steering": case.steering}
            )
            case_path = directory / "case.json"
            prompt_path = directory / "runtime-prompt.json"
            freeze_path = directory / "frozen.json"
            write_private_json(case_path, case)
            prompt = NativeScoutPrompt(
                team_id=seed.team_id,
                config_id=seed.config_id,
                skill_name=case.skill.name,
                skill_version=case.skill.version,
                allowed_tools=case.skill.allowed_tools,
                harness_prompt_version=HARNESS_PROMPT_VERSION,
                frozen_inputs={str(case_path): file_sha256(case_path)},
                frozen_manifest=str(freeze_path),
            )
            write_private_json(prompt_path, prompt)
            write_private_json(
                freeze_path, FrozenEnvironment.create([case_path], seed, runtime_prompt=prompt_path, case=case)
            )
            trials = ScoutEvaluationTrials(case, seed, freeze_path)
            if change == "steering":
                trials.case = case.model_copy(update={"steering": "Different instructions."})
            elif change == "file":
                write_private_json(case_path, case.model_copy(update={"steering": "Different instructions."}))
            with (
                override_settings(SCOUT_EVAL_ENVIRONMENT_FILE=str(prompt_path) if change == "override" else ""),
                patch(
                    "products.signals.backend.scout_harness.prompt.HARNESS_PROMPT_VERSION",
                    "changed-version" if change == "harness" else HARNESS_PROMPT_VERSION,
                ),
            ):
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        trials.check_prompt_configuration()
                else:
                    trials.check_prompt_configuration()
                    assert "recorded_prompt" not in prompt.model_dump()

    @parameterized.expand(
        [
            ("recorded_prompt", "Previous run instructions."),
            ("prompt_transformations", [{"source": "a", "replacement": "b", "reason": "Change instructions."}]),
        ]
    )
    def test_native_cases_refuse_recorded_instruction_overrides(self, field: str, value: object) -> None:
        cutoff = datetime(2030, 1, 1, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "ordinary harness prompt"):
            ScoutEnvironmentCase.model_validate(
                {
                    "environment_id": "example",
                    "source_cutoff": cutoff,
                    "checkpoint": cutoff,
                    "prompt_mode": "native",
                    "skill": {
                        "id": uuid4(),
                        "name": "example-scout",
                        "body": "Review example events.",
                        "version": 1,
                        "origin": "custom",
                    },
                    field: value,
                }
            )

    @parameterized.expand([0, 2])
    def test_check_refuses_missing_or_ambiguous_frozen_bundle_before_any_gateway_probe(self, matches: int) -> None:
        trials = self.make_trials()
        receipt = SimpleNamespace(phase="complete", manifest_sha256="f" * 64)
        trials.freeze_path = Path("/tmp/example/frozen.json")
        trials.freeze = FrozenEnvironment(
            created_at=datetime(2030, 1, 1, tzinfo=UTC),
            team_id=trials.seed.team_id,
            config_id=trials.seed.config_id,
            runtime_prompt_path="/tmp/example/runtime-prompt.json",
            runtime_prompt_sha256="0" * 64,
            inputs={f"/tmp/example/{index}/environment.json": "f" * 64 for index in range(matches)},
        )
        with (
            patch.object(FrozenEnvironment, "verify"),
            patch("products.posthog_ai.eval_harness.environment.guard.assert_local_databases"),
            patch(
                "products.posthog_ai.eval_harness.environment.restore.PreparedEnvironment.read_receipt",
                return_value=receipt,
            ),
            patch("products.posthog_ai.eval_harness.environment.restore.PreparedEnvironment.verify") as verify,
            patch.object(trials, "probe_gateway") as probe,
            self.assertRaisesRegex(ValueError, "exactly one frozen environment manifest"),
        ):
            trials.check(probe_gateway=True)
        verify.assert_not_called()
        probe.assert_not_called()

    @parameterized.expand(
        [
            ("http://127.0.0.1:8000", True),
            ("http://host.docker.internal:8787/mcp", True),
            ("http://backend:8000", True),
            ("https://us.posthog.com", False),
            ("http://localhost.example.com", False),
            ("http://user:password@localhost", False),
            (None, False),
        ]
    )
    def test_calls_require_explicit_local_routes(self, value: str | None, allowed: bool) -> None:
        if allowed:
            assert_local_url(value, "test endpoint")
        else:
            with self.assertRaises(ValueError):
                assert_local_url(value, "test endpoint")

    @parameterized.expand(
        [
            ("local", {}, None),
            (
                "remote_fallback",
                {"SANDBOX_LLM_GATEWAY_URL": "https://gateway.example.com"},
                "SANDBOX_LLM_GATEWAY_URL",
            ),
            ("implicit_fallback", {"SANDBOX_LLM_GATEWAY_URL": None}, "SANDBOX_LLM_GATEWAY_URL"),
            ("missing_rubrics", {"SANDBOX_AI_GATEWAY_PRODUCTS": "signals_scout"}, "signals_scout_suggestions"),
            ("missing_judge", {"SANDBOX_AI_GATEWAY_PRODUCTS": "signals_scout_suggestions"}, "signals_scout"),
            (
                "qualified_judge",
                {"SANDBOX_AI_GATEWAY_PRODUCTS": "signals_scout_suggestions,signals_scout:trial_judge"},
                None,
            ),
            ("missing_mint", {"SANDBOX_AI_GATEWAY_MINT_KEY": ""}, "SANDBOX_AI_GATEWAY_MINT_KEY"),
        ]
    )
    def test_scoring_routes_require_local_fallback_and_both_actual_products(
        self, _name: str, overrides: dict[str, str | None], error: str | None
    ) -> None:
        configuration = {
            "SANDBOX_API_URL": "http://localhost:8000",
            "SANDBOX_MCP_URL": "http://localhost:8787/mcp",
            "SANDBOX_AI_GATEWAY_URL": "http://localhost:8080",
            "SANDBOX_LLM_GATEWAY_URL": "http://localhost:8080",
            "AI_GATEWAY_URL": "http://localhost:8080/v1",
            "SANDBOX_AI_GATEWAY_PRODUCTS": "signals_scout,signals_scout_suggestions",
            "SANDBOX_AI_GATEWAY_MINT_KEY": "fake-mint-key",
            **overrides,
        }
        with (
            override_settings(**configuration),
            patch.dict("os.environ", {"POSTHOG_API_BASE_URL": "http://localhost:8000"}),
        ):
            if error is not None:
                with self.assertRaisesRegex(ValueError, error):
                    ScoutEvaluationTrials.check_local_routes()
            else:
                ScoutEvaluationTrials.check_local_routes()

    def test_budget_retries_do_not_double_reserve_and_unknown_spend_blocks_new_batches(self) -> None:
        with TemporaryDirectory() as folder:
            ledger = BudgetLedger(Path(folder) / "budget.json")
            first = uuid4()
            ledger.reserve(first, Decimal("200"), plan_sha256="f" * 64)
            assert ledger.reserve(first, Decimal("200"), plan_sha256="f" * 64).committed_usd == Decimal("200")
            with self.assertRaisesRegex(ValueError, "Reconcile"):
                ledger.reserve(uuid4(), Decimal("1"), plan_sha256="0" * 64)
            ledger.settle(first, Decimal("50"))
            with self.assertRaisesRegex(ValueError, "already settled.*new plan"):
                ledger.reserve(first, Decimal("200"), plan_sha256="f" * 64)
            assert ledger.read().committed_usd == Decimal("50")
            assert ledger.reserve(uuid4(), Decimal("250"), plan_sha256="0" * 64).committed_usd == Decimal("300")

    def test_pending_budget_cannot_authorize_a_second_standalone_launch_or_an_unbound_legacy_plan(self) -> None:
        with TemporaryDirectory() as folder:
            ledger = BudgetLedger(Path(folder) / "budget.json")
            plan = EvaluationPlan(
                mode="trial",
                freeze_sha256="0" * 64,
                config_id=uuid4(),
                team_id=7,
                user_id=7,
                request={"variants": [{"launch_ids": [str(uuid4())], "model": "example-model"}]},
                reserved_usd=Decimal("30"),
                scout_cap_usd=Decimal("10"),
                judge_cap_usd=Decimal("10"),
                report_checks_per_run=2,
            )
            ledger.reserve(plan.comparison_id, plan.reserved_usd, plan_sha256=plan.fingerprint())
            saved = EvaluationPlan.model_validate_json(plan.model_dump_json())
            assert (
                ledger.reserve(saved.comparison_id, saved.reserved_usd, plan_sha256=saved.fingerprint()).committed_usd
                == plan.reserved_usd
            )
            changed = plan.model_copy(
                update={"request": {"variants": [{"launch_ids": [str(uuid4())], "model": "example-model"}]}}
            )
            self.assertNotEqual(plan.fingerprint(), changed.fingerprint())
            with self.assertRaisesRegex(ValueError, "not bound to this exact plan"):
                ledger.reserve(changed.comparison_id, changed.reserved_usd, plan_sha256=changed.fingerprint())
            stored = ledger.read()
            assert stored.reservations[str(plan.comparison_id)].plan_sha256 == plan.fingerprint()
            legacy = stored.model_dump(mode="json")
            legacy["reservations"][str(plan.comparison_id)].pop("plan_sha256")
            write_private_json(ledger.path, legacy)
            with self.assertRaisesRegex(ValueError, "not bound to this exact plan"):
                ledger.reserve(plan.comparison_id, plan.reserved_usd, plan_sha256=plan.fingerprint())
            assert ledger.read().committed_usd == Decimal("30")

    def test_budget_refuses_projected_spend_above_campaign_limit(self) -> None:
        with TemporaryDirectory() as folder:
            ledger = BudgetLedger(Path(folder) / "budget.json")
            with self.assertRaisesRegex(ValueError, "exceed"):
                ledger.reserve(uuid4(), Decimal("301"), plan_sha256="f" * 64)
            assert not ledger.path.exists()

    def test_comparison_reserves_the_actual_judge_product_cap(self) -> None:
        trials = self.make_trials()
        cutoff = datetime(2030, 1, 1, tzinfo=UTC)
        trials.case = ScoutEnvironmentCase(
            environment_id="example",
            source_cutoff=cutoff,
            checkpoint=cutoff,
            skill=ScoutEnvironmentSkill(
                id=uuid4(), name="example-scout", body="Review example events.", version=1, origin="custom"
            ),
        )
        with (
            TemporaryDirectory() as folder,
            patch.object(trials, "check"),
            override_settings(
                SANDBOX_AI_GATEWAY_TOKEN_CAP_USD_PRODUCT_OVERRIDES='{"signals_scout":"10","posthog_ai":"2"}'
            ),
        ):
            trials.freeze_path = Path(folder) / "frozen.json"
            trials.freeze_path.write_text("{}")
            plan = trials.plan(
                [TrialVariant(label="baseline", model="example-model", reasoning_effort="high", repeats=2)]
            )
        assert plan.scout_cap_usd == Decimal("10")
        assert plan.judge_cap_usd == Decimal("10")
        assert plan.reserved_usd == Decimal("80")

    def test_gateway_probe_revokes_its_private_token_without_starting_a_model_run(self) -> None:
        trials = self.make_trials()
        service = SimpleNamespace(user=SimpleNamespace(distinct_id="synthetic-operator"))
        with (
            patch.object(trials, "_service", return_value=service),
            patch(
                "products.tasks.backend.facade.gateway.mint_private_gateway_token", return_value="fake-token"
            ) as mint,
            patch("products.tasks.backend.facade.gateway.revoke_private_gateway_token") as revoke,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.mint_scoped_token",
                side_effect=["fake-judge-token", "fake-rubric-token"],
            ) as scoring_mint,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.revoke_scoped_token"
            ) as scoring_revoke,
        ):
            trials.probe_gateway()
        mint.assert_called_once_with(team_id=7, user="synthetic-operator", expires_in_seconds=60)
        revoke.assert_called_once_with("fake-token")
        assert scoring_mint.call_args_list == [
            call(ai_product=product, team_id=7, user="synthetic-operator", expires_in_seconds=60)
            for product in ("signals_scout", "signals_scout_suggestions")
        ]
        assert scoring_revoke.call_args_list == [call("fake-judge-token"), call("fake-rubric-token")]

    @parameterized.expand(
        [
            ("signals_scout", [None], []),
            ("signals_scout_suggestions", ["fake-judge-token", None], ["fake-judge-token"]),
        ]
    )
    def test_gateway_probe_fails_closed_when_a_scoring_mint_fails(
        self, product: str, tokens: list[str | None], revoked: list[str]
    ) -> None:
        trials = self.make_trials()
        service = SimpleNamespace(user=SimpleNamespace(distinct_id="synthetic-operator"))
        with (
            patch.object(trials, "_service", return_value=service),
            patch("products.tasks.backend.facade.gateway.mint_private_gateway_token", return_value="fake-token"),
            patch("products.tasks.backend.facade.gateway.revoke_private_gateway_token") as revoke,
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.mint_scoped_token", side_effect=tokens
            ),
            patch(
                "products.tasks.backend.temporal.process_task.ai_gateway_token.revoke_scoped_token"
            ) as scoring_revoke,
        ):
            with self.assertRaisesRegex(ValueError, f"{product} gateway credential"):
                trials.probe_gateway()
        revoke.assert_called_once_with("fake-token")
        assert scoring_revoke.call_args_list == [call(token) for token in revoked]

    @parameterized.expand([("launch", "_launch"), ("export", "_export")])
    def test_command_boundary_gives_live_tool_reads_a_team_scope(self, public: str, internal: str) -> None:
        from posthog.models.scoping import get_current_team_id

        trials = self.make_trials()
        with (
            patch("posthog.models.scoping.manager.resolve_effective_team_id", return_value=7),
            patch.object(trials, internal, side_effect=lambda *_: get_current_team_id()),
        ):
            assert getattr(trials, public)(None, None) == 7
        assert get_current_team_id() is None


class TestRecordedScoutPrompt(TestCase):
    @parameterized.expand([("missing", 0, 1), ("exact", 1, 1), ("unexpected_repeat", 2, 1), ("declared_repeat", 2, 2)])
    def test_instruction_transformations_require_exact_declared_occurrences(
        self, _name: str, occurrences: int, expected_occurrences: int
    ) -> None:
        original = (
            "Original policy.\n" * occurrences + "Owner: source-owner\n- **team_id**: `2`\n- **run_id**: `source-run`\n"
            "- **started_at**: `2030-01-01T00:00:00Z`\n<run_note>\nOriginal steering.\n</run_note>"
        )
        arguments = {
            "team_id": 7,
            "config_id": uuid4(),
            "skill_name": "example-scout",
            "skill_version": 1,
            "allowed_tools": [],
            "recorded_prompt": original,
            "prompt_transformations": [
                ScoutPromptTransformation(
                    source="Original policy.",
                    replacement="Approved policy.",
                    reason="The operator authorized an instruction update.",
                    expected_occurrences=expected_occurrences,
                )
            ],
            "harness_prompt_version": "example-version",
            "replacements": {"source-owner": "local-owner"},
            "frozen_inputs": {},
            "frozen_manifest": "/private/frozen.json",
        }

        if occurrences != expected_occurrences:
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                RecordedScoutPrompt.model_validate(arguments)
            return

        document = RecordedScoutPrompt.model_validate(arguments)
        rendered = document.render(
            run_id="local-run", started_at=datetime(2030, 1, 3, tzinfo=UTC), run_note="Current steering."
        )

        assert rendered.count("Approved policy.") == expected_occurrences
        assert "Original policy." not in rendered
        assert "Owner: local-owner" in rendered
        assert "<run_note>\nCurrent steering.\n</run_note>" in rendered
        assert document.recorded_prompt == original
        assert document.prompt_transformations[0].reason not in rendered

    @parameterized.expand(
        [("no_steering", "", False), ("blank_steering", "  ", False), ("added_steering", "Current steering.", True)]
    )
    def test_recorded_prompt_without_steering_block(self, _name: str, run_note: str, appended: bool) -> None:
        identity = "- **team_id**: `2`\n- **run_id**: `source-run`\n- **started_at**: `2030-01-01T00:00:00Z`"
        document = RecordedScoutPrompt(
            team_id=7,
            config_id=uuid4(),
            skill_name="example-scout",
            skill_version=1,
            allowed_tools=[],
            recorded_prompt=identity,
            harness_prompt_version="example-version",
            frozen_inputs={},
            frozen_manifest="/private/frozen.json",
        )

        rendered = document.render(run_id="local-run", started_at=datetime(2030, 1, 3, tzinfo=UTC), run_note=run_note)

        assert rendered.startswith(
            "- **team_id**: `7`\n- **run_id**: `local-run`\n- **started_at**: `2030-01-03T00:00:00+00:00`"
        )
        assert rendered.count("<run_note>") == int(appended)
        if appended:
            assert f"<run_note>\n{run_note}\n</run_note>" in rendered

    @parameterized.expand([("legacy", False), ("declared", True)])
    def test_prompt_time_replacements_preserve_declared_boundaries_and_legacy_replays(
        self, _name: str, declared: bool
    ) -> None:
        document = RecordedScoutPrompt(
            team_id=7,
            config_id=uuid4(),
            skill_name="example-scout",
            skill_version=1,
            allowed_tools=[],
            recorded_prompt=(
                "Date: 2030-01-01\nUndeclared timestamp: 2030-01-01T12:00:00Z\n"
                "- **team_id**: `2`\n- **run_id**: `source-run`\n"
                "- **started_at**: `2029-12-01T00:00:00Z`\n<run_note>\nSource note.\n</run_note>"
            ),
            harness_prompt_version="example-version",
            replacements={"2030-01-01": "2030-01-02"},
            time_strings=["2030-01-01"] if declared else [],
            frozen_inputs={},
            frozen_manifest="/private/frozen.json",
        )

        rendered = document.render(run_id="local-run", started_at=datetime(2030, 1, 3, tzinfo=UTC), run_note="")

        assert "Date: 2030-01-02\n" in rendered
        expected_date = "2030-01-01" if declared else "2030-01-02"
        assert f"Undeclared timestamp: {expected_date}T12:00:00Z\n" in rendered

    def test_replay_preserves_identity_lookup_guidance_and_changes_only_declared_context(self) -> None:
        source = (
            "Use scout-members-list to find reviewers.\n"
            "- **team_id**: `2`, implicit on calls.\n"
            "- **run_id**: `source-run`, passed to writes.\n"
            "- **started_at**: `2024-01-01T00:00:00+00:00`, informational.\n"
            "Owner: source-owner\n<run_note>\nInspect the original interval.\n</run_note>"
        )
        document = RecordedScoutPrompt(
            team_id=7,
            config_id=uuid4(),
            skill_name="example-scout",
            skill_version=1,
            allowed_tools=["emit_report"],
            recorded_prompt=source,
            harness_prompt_version="example-version",
            replacements={"source-owner": "local-owner"},
            frozen_inputs={},
            frozen_manifest="/private/frozen.json",
        )
        rendered = document.render(
            run_id="local-run", started_at=datetime(2025, 1, 1, tzinfo=UTC), run_note="Inspect the shifted interval."
        )
        assert rendered == source.replace("`2`", "`7`").replace("source-run", "local-run").replace(
            "2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"
        ).replace("source-owner", "local-owner").replace("original interval", "shifted interval")

    def test_replay_refuses_changed_frozen_inputs(self) -> None:
        with TemporaryDirectory() as folder:
            source = Path(folder) / "case.json"
            source.write_text("original")
            prompt = RecordedScoutPrompt(
                team_id=7,
                config_id=uuid4(),
                skill_name="example-scout",
                skill_version=1,
                allowed_tools=["emit_report"],
                recorded_prompt="Example prompt",
                harness_prompt_version="example-version",
                frozen_inputs={str(source): file_sha256(source)},
                frozen_manifest=str(Path(folder) / "frozen.json"),
            )
            output = Path(folder) / "prompt.json"
            write_private_json(output, prompt)
            write_private_json(
                Path(prompt.frozen_manifest),
                FrozenEnvironment(
                    created_at=datetime(2030, 1, 1, tzinfo=UTC),
                    inputs=prompt.frozen_inputs,
                    team_id=prompt.team_id,
                    config_id=prompt.config_id,
                    runtime_prompt_path=str(output),
                    runtime_prompt_sha256=file_sha256(output),
                ),
            )
            read_recorded_prompt(output)
            source.write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                read_recorded_prompt(output)
