from copy import deepcopy
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.messaging.backend.facade.transactional_email import make_transactional
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
from products.workflows.backend.services.hog_flow_writes import save_validated_workflow


def _content(
    subject: str = "Reset your password",
    from_integration_id: int | None = None,
    html: str = "<a href='{{ variables.link }}'>Reset</a>",
    text: str = "Reset: {{ variables.link }}",
    sensitive: bool = False,
    click_tracking_enabled: bool | None = None,
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
        click_tracking_enabled=click_tracking_enabled,
    )


class TestTransactionalEmailWorkflows(APIBaseTest):
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

    def _restore_and_publish(self, flow_id, version: int) -> dict:
        restore = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/{version}/restore", {})
        assert restore.status_code == 200, restore.json()
        with patch("products.workflows.backend.presentation.views.hog_flow.get_hog_flow_in_flight_count") as mock_count:
            mock_count.return_value = MagicMock(
                status_code=200, json=lambda: {"count": 0, "by_action": {}, "position_unknown": 0}
            )
            preview = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert preview.status_code == 200, preview.json()
        published = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
        )
        assert published.status_code == 200, published.json()
        live = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}")
        assert live.status_code == 200, live.json()
        return live.json()

    @parameterized.expand(
        [
            ("sensitive_with_default_clicks", False, None, True, None),
            ("sensitive_with_clicks_opted_in", False, None, True, True),
            ("sensitive_restoring_version_that_had_clicks_on", True, True, True, None),
            ("non_sensitive_with_clicks_off", False, None, False, False),
        ]
    )
    def test_publishing_an_older_version_keeps_the_protection_set_on_the_template(
        self, _name, v1_sensitive, v1_clicks, live_sensitive, live_clicks
    ):
        flow_id = create_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            content=_content(subject="Original subject", sensitive=v1_sensitive, click_tracking_enabled=v1_clicks),
        )
        update_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            hog_flow_id=flow_id,
            content=_content(subject="New subject", sensitive=live_sensitive, click_tracking_enabled=live_clicks),
        )

        published = self._restore_and_publish(flow_id, 1)

        email_action = next(action for action in published["actions"] if action["type"] == "function_email")
        config = email_action["config"]
        assert config["inputs"]["email"]["value"]["subject"] == "Original subject"
        assert config["sensitive"] is live_sensitive
        if live_clicks is None:
            assert "click_tracking_enabled" not in config
        else:
            assert config["click_tracking_enabled"] is live_clicks

    def test_restoring_after_email_step_removed_recovers_template_click_tracking_setting(self):
        created = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {
                "name": "Order confirmation",
                "content": {"email": {"subject": "Order received", "text": "Thanks"}},
                "type": "email",
                "sensitive": False,
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        template_id = created.json()["id"]
        flow_id = make_transactional(
            self.team.id, UUID(template_id), user_id=self.user.id, from_integration_id=self.sender.id
        )

        updated = self.client.patch(
            f"/api/projects/{self.team.id}/messaging_templates/{template_id}/",
            {"click_tracking_enabled": False},
            format="json",
        )
        assert updated.status_code == 200, updated.json()

        flow = HogFlow.objects.get(id=flow_id)
        no_email_actions = [action for action in flow.actions if action["type"] != "function_email"]
        HogFlow.objects.filter(id=flow_id).update(actions=no_email_actions, edges=[])

        published = self._restore_and_publish(flow_id, 1)

        email_action = next(action for action in published["actions"] if action["type"] == "function_email")
        assert email_action["config"]["sensitive"] is False
        assert email_action["config"]["click_tracking_enabled"] is False

    def test_resuming_paused_workflow_keeps_concurrent_click_tracking_update(self):
        flow_id = create_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            content=_content(sensitive=False, click_tracking_enabled=None),
        )
        HogFlow.objects.filter(id=flow_id).update(status=HogFlow.State.DRAFT)
        stale_flow = HogFlow.objects.get(id=flow_id)
        stale_serializer = HogFlowSerializer(
            stale_flow,
            data={"status": HogFlow.State.ACTIVE},
            partial=True,
            context={"team_id": self.team.id, "get_team": lambda: self.team},
        )
        assert stale_serializer.is_valid(), stale_serializer.errors
        stale_validated = dict(stale_serializer.validated_data)

        update_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            hog_flow_id=flow_id,
            content=_content(sensitive=False, click_tracking_enabled=False),
        )
        save_validated_workflow(team_id=self.team.id, hog_flow_id=flow_id, validated_data=stale_validated)

        config = HogFlow.objects.get(id=flow_id).actions[1]["config"]
        assert config["click_tracking_enabled"] is False

    def test_the_stored_workflow_passes_the_workflows_api_validation(self):
        flow = HogFlow.objects.get(
            id=create_transactional_email_workflow(
                team_id=self.team.id,
                user_id=self.user.id,
                content=_content(sensitive=True, click_tracking_enabled=True),
            )
        )

        serializer = HogFlowSerializer(
            data=deepcopy({"name": flow.name, "status": "active", "actions": flow.actions, "edges": flow.edges}),
            context={"team_id": self.team.id, "get_team": lambda: self.team, "is_draft": False},
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["trigger"] == flow.trigger == {"type": "api"}
        assert serializer.validated_data["billable_action_types"] == flow.billable_action_types
        assert serializer.validated_data["actions"][1]["config"]["click_tracking_enabled"] is True

    @parameterized.expand([("unverified_default", False, None), ("another_teams_sender", True, "other")])
    def test_a_new_transactional_email_needs_a_verified_sender_of_its_own(self, _name, verified, requested):
        self.sender.config = {"verified": verified}
        self.sender.save()
        requested_id = None
        if requested == "other":
            requested_id = self._other_teams_sender()

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
