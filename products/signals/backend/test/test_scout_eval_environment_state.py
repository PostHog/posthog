from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from pydantic import ValidationError

from posthog.models import User

from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt
from products.signals.backend.models import SignalScoutConfig, SignalScoutNote, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentOrganization,
    ScoutEnvironmentRecord,
    ScoutEnvironmentSkill,
    ScoutEnvironmentStartingState,
    ScoutEnvironmentUser,
)
from products.signals.backend.scout_harness.eval_environment.state import ScoutEnvironmentState
from products.skills.backend.models.skills import LLMSkill


class TestScoutEnvironmentState(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.checkpoint = datetime(2030, 6, 4, 12, tzinfo=UTC)
        self.source_user_uuid = uuid4()
        self.run_id = uuid4()
        self.case = ScoutEnvironmentCase(
            environment_id="example-environment",
            source_cutoff=self.checkpoint - timedelta(hours=1),
            checkpoint=self.checkpoint,
            organization=ScoutEnvironmentOrganization(name="Example organization", is_ai_data_processing_approved=True),
            project_name="Example project",
            skill=ScoutEnvironmentSkill(
                id=uuid4(),
                name="example-scout",
                body="Investigate example actions.",
                version=3,
                origin="custom",
                created_by="source-owner",
                owners=["source-owner"],
            ),
            users=[
                ScoutEnvironmentUser(
                    id="source-owner",
                    uuid=self.source_user_uuid,
                    first_name="Example owner",
                    is_operator=True,
                ),
                ScoutEnvironmentUser(id="source-member", first_name="Example member"),
            ],
            state=ScoutEnvironmentStartingState(
                runs=[
                    ScoutEnvironmentRecord(
                        id=self.run_id,
                        created_at=self.checkpoint - timedelta(days=1),
                        fields={
                            "skill_name": "example-scout",
                            "skill_version": 3,
                            "status": "completed",
                            "summary": "An earlier finding.",
                            "total_spend": 1.2345,
                        },
                    )
                ],
                notes=[
                    ScoutEnvironmentRecord(
                        id=uuid4(),
                        created_at=self.checkpoint - timedelta(hours=2),
                        fields={"content": "Watch example actions.", "created_by_id": "source-owner"},
                    )
                ],
                memory=[
                    ScoutEnvironmentRecord(
                        id=uuid4(),
                        created_at=self.checkpoint - timedelta(hours=3),
                        fields={
                            "key": "example",
                            "content": f"Run {self.run_id}",
                            "created_by_run_id": str(self.run_id),
                        },
                    )
                ],
            ),
        )
        self.receipt = EnvironmentReceipt(
            phase="complete",
            manifest_sha256="0" * 64,
            environment_id=self.case.environment_id,
            source_cutoff=self.case.source_cutoff,
            target_cutoff=self.checkpoint + timedelta(days=7),
            timezone="UTC",
            databases={"fixture": "local"},
            identity_namespace=uuid4(),
            provenance={},
            team_id=self.team.id,
            project_id=self.team.project_id,
            organization_id=self.organization.id,
            user_id=self.user.id,
        )

    @override_settings(DEBUG=True)
    @patch.object(ScoutEnvironmentState, "_seed_users", autospec=True)
    def test_rejects_receipt_for_other_databases_before_seeding(self, seed_users) -> None:
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value={"fixture": "other"},
        ):
            with self.assertRaisesRegex(ValueError, "complete import receipt"):
                ScoutEnvironmentState.seed(self.case, self.receipt)
        seed_users.assert_not_called()

    def test_restores_linked_history_with_local_operator_identity_and_rejects_dirty_reuse(self) -> None:
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            result = ScoutEnvironmentState.seed(self.case, self.receipt)
            ScoutEnvironmentState.verify(self.case, self.receipt, result)
            with self.assertRaisesRegex(ValueError, "already populated"):
                ScoutEnvironmentState.seed(self.case, self.receipt)
        config = SignalScoutConfig.objects.for_team(self.team.id).get(id=result.config_id)
        self.organization.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.organization.name, "Example organization")
        self.assertEqual(self.team.name, "Example project")
        self.assertEqual(self.team.project.name, "Example project")
        member = User.objects.get(id=int(result.identity_map["user:source-member"]))
        self.assertTrue(member.email.startswith("member-"))
        self.assertTrue(member.email.endswith("@example.com"))
        self.assertTrue(self.organization.is_ai_data_processing_approved)
        self.assertFalse(self.organization.is_ai_training_opted_in)
        self.assertFalse(config.enabled)
        note = SignalScoutNote.objects.for_team(self.team.id).get()
        self.assertEqual(note.created_by_id, self.user.id)
        self.assertEqual(result.identity_map[str(self.source_user_uuid)], str(self.user.uuid))
        run = SignalScoutRun.objects.for_team(self.team.id).get()
        memory = SignalScratchpad.objects.for_team(self.team.id).get()
        self.assertEqual(memory.created_by_run_id, run.id)
        self.assertIn(str(run.id), memory.content)
        self.assertEqual(run.task_run.task.team_id, self.team.id)
        self.assertEqual(
            run.task_run.task.created_at,
            self.case.state.runs[0].created_at + timedelta(seconds=result.time_delta_seconds),
        )
        self.assertEqual(
            run.task_run.created_at,
            self.case.state.runs[0].created_at + timedelta(seconds=result.time_delta_seconds),
        )
        self.assertEqual(
            note.created_at, self.case.state.notes[0].created_at + timedelta(seconds=result.time_delta_seconds)
        )
        SignalScratchpad.objects.for_team(self.team.id).filter(id=memory.id).update(content="Changed baseline")
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            with self.assertRaisesRegex(ValueError, "baseline changed"):
                ScoutEnvironmentState.verify(self.case, self.receipt, result)

    def test_unknown_relationship_rolls_back_the_whole_starting_state(self) -> None:
        corrupted = self.case.model_copy(
            update={
                "state": self.case.state.model_copy(
                    update={
                        "memory": [
                            self.case.state.memory[0].model_copy(
                                update={
                                    "fields": {
                                        "key": "bad-link",
                                        "content": "Example",
                                        "created_by_run_id": str(uuid4()),
                                    }
                                }
                            )
                        ]
                    }
                )
            }
        )
        original_name = self.user.first_name
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            with self.assertRaisesRegex(ValueError, "supplied local records"):
                ScoutEnvironmentState.seed(corrupted, self.receipt)
        self.assertFalse(LLMSkill.objects.filter(team_id=self.team.id).exists())
        self.assertFalse(SignalScoutConfig.objects.for_team(self.team.id).exists())
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, original_name)

    def test_record_versions_after_checkpoint_are_rejected_but_future_expiry_is_allowed(self) -> None:
        value = self.case.model_dump()
        value["state"]["notes"][0]["created_at"] = self.checkpoint + timedelta(seconds=1)
        with self.assertRaisesRegex(ValidationError, "versions written after"):
            ScoutEnvironmentCase.model_validate(value)
        value["state"]["notes"][0]["created_at"] = self.checkpoint
        value["state"]["notes"][0]["fields"]["expires_at"] = (self.checkpoint + timedelta(days=1)).isoformat()
        self.assertIsNotNone(ScoutEnvironmentCase.model_validate(value))

    def test_future_completion_is_rejected_even_when_record_creation_precedes_checkpoint(self) -> None:
        state = ScoutEnvironmentState(self.case, self.receipt)
        with self.assertRaisesRegex(ValueError, "after the checkpoint"):
            state._fields(
                SignalScoutConfig,
                {"last_run_at": (self.checkpoint + timedelta(seconds=1)).isoformat()},
                frozenset({"last_run_at"}),
            )
