from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_import import WorkflowImport
from products.workflows.backend.presentation.views import workflow_import_drafts
from products.workflows.backend.services.resend_import import drafts

SEGMENT_DESCRIPTION = "Imported from Resend segment seg-1."


def _automation(automation_id: str, *, segment: bool = False) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"key": "start", "type": "trigger", "config": {"event_name": "user.created"}},
        {"key": "wait", "type": "delay", "config": {"duration": "1 hour"}},
    ]
    connections = [{"from": "start", "to": "wait"}]
    if segment:
        steps.append({"key": "tag", "type": "add_to_segment", "config": {"segment_id": "seg-1"}})
        connections.append({"from": "wait", "to": "tag"})
    return {"id": automation_id, "name": f"Invented {automation_id}", "steps": steps, "connections": connections}


class TestResendAutomationDrafts(BaseTest):
    def _import(self, automation: dict[str, Any], **kwargs: Any) -> Any:
        return drafts.import_resend_automation(self.team.id, self.user.id, automation, {}, **kwargs)

    def test_access_rules_load_once_for_a_page_of_automations(self) -> None:
        with patch.object(drafts, "UserAccessControl", wraps=drafts.UserAccessControl) as access:
            with drafts.reuse_import_access():
                results = [self._import(_automation(automation_id)) for automation_id in ("a1", "a2")]

        assert [result.status for result in results] == ["created", "created"]
        assert access.call_count == 1

    def test_an_automation_whose_draft_was_deleted_imports_again(self) -> None:
        first = self._import(_automation("a1"))
        assert self._import(_automation("a1")).status == "skipped"
        HogFlow.objects.filter(id=first.workflow_id).delete()

        again = self._import(_automation("a1"))

        assert again.status == "created" and again.workflow_id != first.workflow_id
        record = WorkflowImport.objects.for_team(self.team.id).get(source_id="a1")
        assert str(record.hog_flow_id) == again.workflow_id

    def test_failed_imports_are_tried_again_on_the_next_run(self) -> None:
        assert drafts.import_resend_automation(self.team.id, 999_999, _automation("a1"), {}).status == "failed"
        with patch.object(workflow_import_drafts, "_validated_draft", return_value=(None, ["bad step"])):
            assert self._import(_automation("a2")).notes == ("bad step",)
        unreadable = {**_automation("a3"), "steps": [{"key": "wait", "type": "delay", "config": "1 hour"}]}
        assert self._import(unreadable).status == "failed"

        assert [self._import(_automation(key)).status for key in ("a1", "a2")] == ["created", "created"]

    @parameterized.expand(
        [
            ("no_access_to_create_one", None, False, "needs edit access to cohorts"),
            ("no_access_to_the_existing_one", True, False, "needs edit access"),
            ("existing_one_is_not_static", False, True, "isn't static anymore"),
        ]
    )
    def test_a_segment_cohort_needs_cohort_access(
        self, _name: str, existing_static: bool | None, can_edit: bool, note: str
    ) -> None:
        if existing_static is not None:
            Cohort.objects.create(
                team=self.team, name="Pro", description=SEGMENT_DESCRIPTION, is_static=existing_static
            )
        cohorts_before = Cohort.objects.filter(team_id=self.team.id).count()

        with (
            patch.object(
                drafts.UserAccessControl,
                "check_access_level_for_resource",
                side_effect=lambda resource, *_a, **_k: can_edit or resource != "cohort",
            ),
            patch.object(drafts.UserAccessControl, "check_access_level_for_ref", return_value=can_edit),
            patch.object(drafts, "translate_automation", wraps=drafts.translate_automation) as translate,
        ):
            self._import(_automation("a1", segment=True), segments={"seg-1": "Pro"})

        cohort = translate.call_args.args[2].segment_cohorts["seg-1"]
        assert cohort.cohort_id is None and note in (cohort.problem or "")
        assert Cohort.objects.filter(team_id=self.team.id).count() == cohorts_before
