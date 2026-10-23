from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from pydantic import JsonValue, ValidationError

from posthog.models import User

from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalScoutConfig, SignalScoutNote, SignalScoutRun, SignalScratchpad
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentOrganization,
    ScoutEnvironmentRecord,
    ScoutEnvironmentSkill,
    ScoutEnvironmentStartingState,
    ScoutEnvironmentUser,
)
from products.signals.backend.scout_harness.eval_environment.state import ScoutEnvironmentState
from products.signals.backend.scout_harness.lazy_seed import (
    HARNESS_SEEDED_BY,
    CanonicalSkill,
    CanonicalSkillFile,
    _compute_canonical_hash,
)
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.models import TaskRun


class TestScoutEnvironmentState(BaseTest):
    def _companion_skill(
        self, origin: Literal["canonical", "custom"], *, diverged: bool = False
    ) -> ScoutEnvironmentSkill:
        canonical = CanonicalSkill(
            name="example-companion",
            description="Supporting guidance.",
            body="Read the supporting reference.",
            allowed_tools=("query-run",),
            files=(
                CanonicalSkillFile(
                    path="references/example.md", content="Supporting evidence.", content_type="text/markdown"
                ),
            ),
            source_path=Path("/tmp/example-companion"),
        )
        return ScoutEnvironmentSkill(
            id=uuid4(),
            name=canonical.name,
            description=canonical.description,
            body="Read the team's supporting reference." if diverged else canonical.body,
            allowed_tools=list(canonical.allowed_tools),
            version=2,
            origin=origin,
            category="",
            created_by="source-owner",
            owners=["source-member"],
            files={file.path: file.content for file in canonical.files},
            file_content_types={file.path: file.content_type for file in canonical.files},
            metadata={"seeded_by": HARNESS_SEEDED_BY, "canonical_hash": _compute_canonical_hash(canonical)}
            if origin == "canonical" or diverged
            else {},
        )

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

    @parameterized.expand(["custom", "canonical", "diverged_custom"])
    def test_restores_linked_history_with_local_operator_identity_and_rejects_dirty_reuse(self, source: str) -> None:
        companion = self._companion_skill(
            "canonical" if source == "canonical" else "custom", diverged=source == "diverged_custom"
        )
        self.case = self.case.model_copy(update={"companion_skills": [companion]})
        with (
            patch(
                "products.signals.backend.scout_harness.lazy_seed.canonical_skill_names",
                return_value=frozenset({companion.name}),
            ),
            patch(
                "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
                return_value=self.receipt.databases,
            ),
        ):
            result = ScoutEnvironmentState.seed(self.case, self.receipt)
            ScoutEnvironmentState.verify(self.case, self.receipt, result)
            with self.assertRaisesRegex(ValueError, "already populated"):
                ScoutEnvironmentState.seed(self.case, self.receipt)
        config = SignalScoutConfig.objects.for_team(self.team.id).get(id=result.config_id)
        restored_companion = LLMSkill.objects.get(team_id=self.team.id, name=companion.name)
        self.assertEqual(restored_companion.body, companion.body)
        self.assertEqual(restored_companion.description, companion.description)
        self.assertEqual(restored_companion.allowed_tools, companion.allowed_tools)
        self.assertEqual(restored_companion.version, companion.version)
        self.assertEqual(restored_companion.category, companion.category)
        self.assertEqual(restored_companion.files.get().content, "Supporting evidence.")
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
        with (
            patch(
                "products.signals.backend.scout_harness.lazy_seed.canonical_skill_names",
                return_value=frozenset({companion.name}),
            ),
            patch(
                "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
                return_value=self.receipt.databases,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "baseline changed"):
                ScoutEnvironmentState.verify(self.case, self.receipt, result)

    @parameterized.expand(
        ["canonical", "body", "description", "allowed_tools", "file", "missing_files", "diverged_custom"]
    )
    def test_preflight_hashes_complete_staged_companion_content_without_database_queries(self, change: str) -> None:
        companion = self._companion_skill(
            "custom" if change == "diverged_custom" else "canonical", diverged=change == "diverged_custom"
        )
        if change == "body":
            companion = companion.model_copy(update={"body": "Different instructions."})
        elif change == "description":
            companion = companion.model_copy(update={"description": "Different guidance."})
        elif change == "allowed_tools":
            companion = companion.model_copy(update={"allowed_tools": []})
        elif change == "file":
            companion = companion.model_copy(update={"files": {"references/example.md": "Different evidence."}})
        elif change == "missing_files":
            companion = companion.model_copy(update={"files": {}, "file_content_types": {}})
        case = self.case.model_copy(update={"companion_skills": [companion]})
        with (
            patch(
                "products.signals.backend.scout_harness.lazy_seed.canonical_skill_names",
                return_value=frozenset({companion.name}),
            ),
            self.assertNumQueries(0),
        ):
            if change in {"canonical", "diverged_custom"}:
                ScoutEnvironmentState.validate_input(case, self.receipt)
            else:
                with self.assertRaisesRegex(ValueError, "declared origin"):
                    ScoutEnvironmentState.validate_input(case, self.receipt)

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

    @parameterized.expand([("artefact",), ("shared_legacy_claim",), ("legacy_assignment",), ("legacy_task",)])
    def test_restores_report_claims_and_pull_requests_with_backing_tasks(self, source: str) -> None:
        task_id, report_id, claim_id, pr_id = (uuid4() for _ in range(4))
        created_at = self.checkpoint - timedelta(hours=1)
        state = self.case.state.model_copy(
            update={
                "tasks": [
                    ScoutEnvironmentRecord(
                        id=task_id,
                        created_at=created_at,
                        fields={
                            "title": "Example repair",
                            "description": "Repair the example.",
                            "origin_product": "signal_report",
                            "internal": True,
                            "created_by_id": "source-owner",
                            "archived": True,
                            "archived_at": created_at.isoformat(),
                            "last_activity_at": created_at.isoformat(),
                        },
                    )
                ],
                "reports": [
                    ScoutEnvironmentRecord(
                        id=report_id, created_at=created_at, fields={"title": "Example report", "status": "ready"}
                    )
                ],
                "pull_requests": [
                    ScoutEnvironmentRecord(
                        id=pr_id,
                        created_at=created_at,
                        fields={
                            "repository": "example/project",
                            "number": 1,
                            "url": "https://github.com/example/project/pull/1",
                            "state": "open",
                        },
                    )
                ],
                "report_artefacts": [
                    ScoutEnvironmentRecord(
                        id=claim_id,
                        created_at=created_at,
                        fields={
                            "report_id": str(report_id),
                            "type": "work_claim",
                            "content": "{}",
                            "actor_kind": "task",
                            "task_id": str(task_id),
                        },
                    ),
                    ScoutEnvironmentRecord(
                        id=uuid4(),
                        created_at=created_at,
                        fields={
                            "report_id": str(report_id),
                            "type": "pull_request",
                            "content": "{}",
                            "actor_kind": "task",
                            "task_id": str(task_id),
                            "claim_id": str(claim_id),
                            "pull_request_id": str(pr_id),
                        },
                    ),
                ],
            }
        )
        if source == "shared_legacy_claim":
            state = state.model_copy(
                update={
                    "report_assignments": [
                        ScoutEnvironmentRecord(
                            id=claim_id,
                            created_at=created_at,
                            fields={
                                "report_id": str(report_id),
                                "actor_kind": "task",
                                "actor_task_id": str(task_id),
                                "claimed_at": created_at.isoformat(),
                            },
                        )
                    ]
                }
            )
        elif source != "artefact":
            assignment_fields: dict[str, JsonValue] = {
                "report_id": str(report_id),
                "actor_kind": "task",
                "actor_task_id": str(task_id),
                "claimed_at": created_at.isoformat(),
            }
            if source == "legacy_assignment":
                assignment_fields.update(
                    pr_url="https://github.com/example/project/pull/1",
                    repository="example/project",
                    pr_number=1,
                    pr_state="open",
                    pr_merged=False,
                )
            state = state.model_copy(
                update={
                    "pull_requests": [],
                    "report_artefacts": [
                        ScoutEnvironmentRecord(
                            id=uuid4(),
                            created_at=created_at,
                            fields={
                                "report_id": str(report_id),
                                "type": "note",
                                "content": '{"note":"Example work update."}',
                                "actor_kind": "task",
                                "task_id": str(task_id),
                                "claim_id": str(claim_id),
                            },
                        )
                    ],
                    "report_assignments": [
                        ScoutEnvironmentRecord(id=claim_id, created_at=created_at, fields=assignment_fields)
                    ],
                }
            )
            if source == "legacy_task":
                state = state.model_copy(
                    update={
                        "report_tasks": [
                            ScoutEnvironmentRecord(
                                id=uuid4(),
                                created_at=created_at,
                                fields={
                                    "report_id": str(report_id),
                                    "task_id": str(task_id),
                                    "relationship": "implementation",
                                },
                            )
                        ],
                        "task_runs": [
                            ScoutEnvironmentRecord(
                                id=uuid4(),
                                created_at=created_at,
                                fields={
                                    "task_id": str(task_id),
                                    "status": "completed",
                                    "environment": "local",
                                    "output": {
                                        "pr_url": "https://github.com/example/project/pull/1",
                                        "pr_state": "open",
                                    },
                                    "state": {"ai_stage": "implementation"},
                                },
                            )
                        ],
                    }
                )
        case = ScoutEnvironmentCase.model_validate(self.case.model_copy(update={"state": state}).model_dump())
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            result = ScoutEnvironmentState.seed(case, self.receipt)
            ScoutEnvironmentState.verify(case, self.receipt, result)
        local_report = result.identity_map[str(report_id)]
        claim = get_active_claim(team_id=self.team.id, report_id=local_report)
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(str(claim.actor_task_id), result.identity_map[str(task_id)])
        self.assertEqual(str(claim.claim_id), result.identity_map[str(claim_id)])
        prs = fetch_implementation_prs_for_reports([local_report], team_id=self.team.id)[local_report]
        self.assertEqual([(pr.url, pr.state) for pr in prs], [("https://github.com/example/project/pull/1", "open")])
        self.assertEqual(
            prs[0].claim_id,
            result.identity_map[str(claim_id)] if source in {"artefact", "shared_legacy_claim"} else None,
        )
        if source == "legacy_task":
            TaskRun.objects.bulk_create(
                [
                    TaskRun(
                        task_id=result.identity_map[str(task_id)],
                        team_id=self.team.id,
                        status="completed",
                        environment="local",
                        output={"pr_url": "https://github.com/example/project/pull/2"},
                    )
                ]
            )
            with patch(
                "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
                return_value=self.receipt.databases,
            ):
                with self.assertRaisesRegex(ValueError, "TaskRun record set changed"):
                    ScoutEnvironmentState.verify(case, self.receipt, result)

    def test_source_emails_use_normal_account_storage_and_verify_without_changing_the_case(self) -> None:
        case = self.case.model_copy(
            update={
                "users": [
                    self.case.users[0].model_copy(update={"email": "Owner.Mixed+tag@Example.COM"}),
                    self.case.users[1].model_copy(update={"email": "Member.Mixed@Example.COM"}),
                ]
            }
        )
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            result = ScoutEnvironmentState.seed(case, self.receipt)
            ScoutEnvironmentState.verify(case, self.receipt, result)
        self.user.refresh_from_db()
        member = User.objects.get(id=int(result.identity_map["user:source-member"]))
        self.assertEqual(self.user.email, "owner.mixed+tag@example.com")
        self.assertEqual(member.email, "member.mixed@example.com")
        self.assertEqual(case.users[0].email, "Owner.Mixed+tag@Example.COM")
        self.assertEqual(case.users[1].email, "Member.Mixed@Example.COM")

    @parameterized.expand(
        [
            ("operator", "source-owner", "operator email belongs to another local user"),
            ("member", "source-member", "user email already exists outside this fresh environment"),
        ]
    )
    def test_rejects_source_email_that_resolves_to_an_existing_account(
        self, _label: str, source_id: str, message: str
    ) -> None:
        User.objects.create_user(email="duplicate@example.com", password=None, first_name="Existing account")
        before = User.objects.count()
        case = self.case.model_copy(
            update={
                "users": [
                    source.model_copy(update={"email": "DUPLICATE@EXAMPLE.COM"}) if source.id == source_id else source
                    for source in self.case.users
                ]
            }
        )
        with patch(
            "products.signals.backend.scout_harness.eval_environment.state.PreparedEnvironment.assert_local",
            return_value=self.receipt.databases,
        ):
            with self.assertRaisesRegex(ValueError, message):
                ScoutEnvironmentState.seed(case, self.receipt)
        self.assertEqual(User.objects.count(), before)
        self.assertFalse(SignalScoutConfig.objects.for_team(self.team.id).exists())

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
