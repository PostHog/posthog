import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.facade.enums import HighlightLabel
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import workflow_ideas, workflows
from products.today.backend.logic.highlight_types import Context
from products.workflows.backend.facade.contracts import EmailSendingState, OwnedWorkflowHealth

WORKFLOW_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
CONTEXT = cast(Context, SimpleNamespace(team=SimpleNamespace(id=1), user=None))


def _workflow(**fields: Any) -> OwnedWorkflowHealth:
    return OwnedWorkflowHealth(
        **{
            "workflow_id": WORKFLOW_ID,
            "name": "Onboarding drip",
            "succeeded": 100,
            "failed": 0,
            "email_sending_paused": False,
            "pending_suggestions": 0,
            **fields,
        }
    )


class TestWorkflows(SimpleTestCase):
    @parameterized.expand(
        [
            ("healthy", _workflow(), []),
            (
                "emails paused",
                _workflow(email_sending_paused=True),
                [
                    (
                        HighlightLabel.RISK,
                        "Emails are paused for workflow ‘Onboarding drip’",
                        "It sends no emails until sending resumes",
                        f"/workflows/{WORKFLOW_ID}/workflow",
                    )
                ],
            ),
            (
                "failing",
                _workflow(succeeded=30, failed=10),
                [
                    (
                        HighlightLabel.RISK,
                        "Workflow ‘Onboarding drip’ failed 10 times in the last 7 days",
                        "25% of its runs failed",
                        f"/workflows/{WORKFLOW_ID}/invocations",
                    )
                ],
            ),
            ("too few failures", _workflow(succeeded=0, failed=9), []),
            ("failures are a small share of runs", _workflow(succeeded=1000, failed=99), []),
            (
                "one suggestion",
                _workflow(pending_suggestions=1),
                [
                    (
                        HighlightLabel.OPPORTUNITY,
                        "1 suggested change to workflow ‘Onboarding drip’ is waiting for review",
                        "Approve or reject it on the Self-driving tab",
                        f"/workflows/{WORKFLOW_ID}/self-driving",
                    )
                ],
            ),
            (
                "several suggestions",
                _workflow(pending_suggestions=3),
                [
                    (
                        HighlightLabel.OPPORTUNITY,
                        "3 suggested changes to workflow ‘Onboarding drip’ are waiting for review",
                        "Approve or reject them on the Self-driving tab",
                        f"/workflows/{WORKFLOW_ID}/self-driving",
                    )
                ],
            ),
        ]
    )
    def test_a_workflow_shows_what_needs_its_owner(
        self, _name: str, workflow: OwnedWorkflowHealth, expected: list[tuple[HighlightLabel, str, str, str]]
    ) -> None:
        registered = next(s for s in load_sources() if s.name == "workflows")

        with (
            patch.object(workflows, "list_owned_workflow_health", return_value=[workflow]),
            patch.object(workflows, "get_email_sending_state", return_value=None),
        ):
            found = registered.find(CONTEXT)

        self.assertEqual([(c.label, c.title, c.detail, c.url) for c in found.items], expected)

    @parameterized.expand(
        [
            ("suspended", [_workflow()], True, ["Email sending is suspended for this project"]),
            ("suspended, with no live workflow of yours", [], True, []),
            ("sending on", [_workflow()], False, []),
        ]
    )
    def test_a_suspended_project_shows_to_workflow_owners(
        self, _name: str, owned: list[OwnedWorkflowHealth], suspended: bool, expected: list[str]
    ) -> None:
        registered = next(s for s in load_sources() if s.name == "workflows")
        state = EmailSendingState(
            suspended_at=datetime(2026, 10, 1, tzinfo=UTC) if suspended else None,
            suspension_reason="",
            tier=1,
            tier_pinned=False,
            tier_updated_at=None,
        )

        with (
            patch.object(workflows, "list_owned_workflow_health", return_value=owned),
            patch.object(workflows, "get_email_sending_state", return_value=state),
        ):
            found = registered.find(CONTEXT)

        self.assertEqual([c.title for c in found.items], expected)

    @parameterized.expand(
        [
            ("none", 0, []),
            ("one", 1, ["1 workflow idea based on your events is ready"]),
            ("several", 4, ["4 workflow ideas based on your events are ready"]),
        ]
    )
    def test_waiting_workflow_ideas_show_once(self, _name: str, count: int, expected: list[str]) -> None:
        registered = next(s for s in load_sources() if s.name == "workflow_ideas")

        with patch.object(workflow_ideas, "count_waiting_data_suggestions", return_value=count):
            found = registered.find(CONTEXT)

        self.assertEqual([(c.title, c.url) for c in found.items], [(title, "/workflows") for title in expected])
