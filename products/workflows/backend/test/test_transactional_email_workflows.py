from copy import deepcopy
from uuid import uuid4

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration
from posthog.models.scoping import team_scope

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.facade.api import set_default_email_sender_if_unset
from products.workflows.backend.facade.contracts import (
    TransactionalEmailContent,
    TransactionalEmailContentInvalid,
    TransactionalEmailSenderUnavailable,
    WorkflowNotFound,
)
from products.workflows.backend.facade.transactional_emails import (
    create_transactional_email_workflow,
    update_transactional_email_workflow,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.presentation.views.hog_flow import HogFlowSerializer
from products.workflows.backend.services.hog_flow_revisions import restore_revision
from products.workflows.backend.services.hog_flow_writes import publish_confirm_value, publish_draft


def _content(
    subject: str = "Reset your password",
    from_integration_id: int | None = None,
    html: str = "<a href='{{ variables.link }}'>Reset</a>",
    text: str = "Reset: {{ variables.link }}",
    sensitive: bool = False,
) -> TransactionalEmailContent:
    return TransactionalEmailContent(
        message_template_id=uuid4(),
        name="Password reset",
        subject=subject,
        preheader="",
        html=html,
        text=text,
        from_integration_id=from_integration_id,
        message_category_id=None,
        sensitive=sensitive,
    )


class TestTransactionalEmailWorkflows(BaseTest):
    def setUp(self):
        super().setUp()
        template = dict(MOCK_NODE_TEMPLATES[0])
        template["id"] = "template-email"
        template["inputs_schema"] = [
            {"key": "email", "type": "native_email", "label": "Email", "required": True, "templating": "liquid"}
        ]
        sync_template_to_db(template)
        self.sender = Integration.objects.create(
            team=self.team, kind="email", integration_id="hello@example.com", config={"verified": True}
        )
        set_default_email_sender_if_unset(self.team.id, self.sender.id)

    def test_a_content_change_writes_a_new_version_and_keeps_the_email_live(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())

        update_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            hog_flow_id=flow_id,
            content=_content(subject="New subject", sensitive=True),
        )

        flow = HogFlow.objects.get(id=flow_id)
        assert flow.actions[1]["config"]["sensitive"] is True
        assert flow.status == HogFlow.State.ACTIVE
        assert flow.origin_product == "transactional_emails"
        assert flow.version == 2
        email = flow.actions[1]["config"]["inputs"]["email"]["value"]
        assert email["subject"] == "New subject"
        assert email["from"] == {"integrationId": self.sender.id}
        versions = (
            HogFlowRevision.objects.for_team(self.team.id)
            .filter(hog_flow=flow)
            .order_by("version")
            .values_list("version", flat=True)
        )
        assert list(versions) == [1, 2]

    def test_publishing_an_older_version_keeps_the_protection_set_on_the_template(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())
        update_transactional_email_workflow(
            team_id=self.team.id, user_id=self.user.id, hog_flow_id=flow_id, content=_content(sensitive=True)
        )

        with team_scope(self.team.id):
            restore_revision(hog_flow_id=flow_id, version=1, overwrite=False, expected_draft_updated_at=None)
            draft_updated_at = HogFlow.objects.get(id=flow_id).draft_updated_at
            publish_draft(
                team_id=self.team.id,
                user_id=self.user.id,
                hog_flow_id=flow_id,
                previewed_value=publish_confirm_value(hog_flow_id=flow_id, draft_updated_at=draft_updated_at),
                validate=lambda _state, content: content,
            )

        assert HogFlow.objects.get(id=flow_id).actions[1]["config"]["sensitive"] is True

    def test_the_stored_workflow_passes_the_workflows_api_validation(self):
        flow = HogFlow.objects.get(
            id=create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())
        )

        serializer = HogFlowSerializer(
            data=deepcopy({"name": flow.name, "status": "active", "actions": flow.actions, "edges": flow.edges}),
            context={"team_id": self.team.id, "get_team": lambda: self.team, "is_draft": False},
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["trigger"] == flow.trigger == {"type": "api"}
        assert serializer.validated_data["billable_action_types"] == flow.billable_action_types

    @parameterized.expand(
        [
            ("unverified_default", False, None),
            ("another_teams_sender", True, "other"),
            ("sandbox_sender", True, "sandbox"),
        ]
    )
    def test_a_new_transactional_email_needs_a_verified_sender_of_its_own(self, _name, verified, requested):
        self.sender.config = {"verified": verified}
        self.sender.save()
        requested_id = None
        if requested == "other":
            requested_id = self._other_teams_sender()
        elif requested == "sandbox":
            requested_id = Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
                config={"provider": SANDBOX_EMAIL_PROVIDER, "verified": True},
            ).id

        with self.assertRaises(TransactionalEmailSenderUnavailable):
            create_transactional_email_workflow(
                team_id=self.team.id, user_id=self.user.id, content=_content(from_integration_id=requested_id)
            )

        assert not HogFlow.objects.filter(team_id=self.team.id).exists()

    def test_an_update_cannot_switch_to_another_teams_sender(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())

        with self.assertRaises(TransactionalEmailSenderUnavailable):
            update_transactional_email_workflow(
                team_id=self.team.id,
                user_id=self.user.id,
                hog_flow_id=flow_id,
                content=_content(from_integration_id=self._other_teams_sender()),
            )

        assert HogFlow.objects.get(id=flow_id).version == 1

    @parameterized.expand([("no_subject", {"subject": ""}), ("no_body", {"html": "", "text": ""})])
    def test_content_that_cannot_send_is_refused(self, _name, overrides):
        with self.assertRaises(TransactionalEmailContentInvalid):
            create_transactional_email_workflow(
                team_id=self.team.id, user_id=self.user.id, content=_content(**overrides)
            )

        assert not HogFlow.objects.filter(team_id=self.team.id).exists()

    def test_an_update_restores_an_email_step_removed_from_the_workflow(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())
        flow = HogFlow.objects.get(id=flow_id)
        flow.actions = [action for action in flow.actions if action["type"] != "function_email"]
        flow.save()

        update_transactional_email_workflow(
            team_id=self.team.id, user_id=self.user.id, hog_flow_id=flow_id, content=_content(subject="New subject")
        )

        email = HogFlow.objects.get(id=flow_id).actions[1]["config"]["inputs"]["email"]["value"]
        assert email["subject"] == "New subject"
        assert email["from"] == {"integrationId": self.sender.id}

    def _other_teams_sender(self) -> int:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        return Integration.objects.create(
            team=other_team, kind="email", integration_id="x@example.com", config={"verified": True}
        ).id

    def test_updating_a_deleted_transactional_email_says_it_is_gone(self):
        flow_id = create_transactional_email_workflow(team_id=self.team.id, user_id=self.user.id, content=_content())
        HogFlow.objects.filter(id=flow_id).delete()

        with self.assertRaises(WorkflowNotFound):
            update_transactional_email_workflow(
                team_id=self.team.id, user_id=self.user.id, hog_flow_id=flow_id, content=_content()
            )
