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
from products.workflows.backend.presentation.views.hog_flow import set_workflow_enabled
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

    @parameterized.expand(
        [
            ("non_sensitive_opt_out", {"click_tracking_enabled": False}, False, False),
            ("sensitive_default_off", {"sensitive": True}, True, None),
            ("sensitive_opt_in", {"sensitive": True, "click_tracking_enabled": True}, True, True),
        ]
    )
    def test_restoring_after_email_step_removed_recovers_template_tracking_settings(
        self, _name, patch_body, expected_sensitive, expected_clicks
    ):
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
            patch_body,
            format="json",
        )
        assert updated.status_code == 200, updated.json()

        flow = HogFlow.objects.get(id=flow_id)
        no_email_actions = [action for action in flow.actions if action["type"] != "function_email"]
        HogFlow.objects.filter(id=flow_id).update(actions=no_email_actions, edges=[])

        published = self._restore_and_publish(flow_id, 1)

        email_action = next(action for action in published["actions"] if action["type"] == "function_email")
        assert email_action["config"]["sensitive"] is expected_sensitive
        if expected_clicks is None:
            assert "click_tracking_enabled" not in email_action["config"]
        else:
            assert email_action["config"]["click_tracking_enabled"] is expected_clicks

    def test_resuming_paused_workflow_validates_fresh_locked_graph_after_concurrent_template_edit(self):
        created = self.client.post(
            f"/api/projects/{self.team.id}/messaging_templates/",
            {
                "name": "Password reset",
                "content": {"email": {"subject": "Reset your password", "text": "Token: {{ variables.token }}"}},
                "type": "email",
                "sensitive": True,
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        template_id = created.json()["id"]
        flow_id = make_transactional(
            self.team.id, UUID(template_id), user_id=self.user.id, from_integration_id=self.sender.id
        )
        HogFlow.objects.filter(id=flow_id).update(status=HogFlow.State.DRAFT)

        def _interleave_template_update(**kwargs):
            patched = self.client.patch(
                f"/api/projects/{self.team.id}/messaging_templates/{template_id}/",
                {
                    "content": {"email": {"subject": "Order shipped", "text": "Your order is on the way"}},
                    "sensitive": False,
                    "click_tracking_enabled": False,
                },
                format="json",
            )
            assert patched.status_code == 200, patched.json()
            save_validated_workflow(**kwargs)

        with patch(
            "products.workflows.backend.presentation.views.hog_flow.save_validated_workflow",
            side_effect=_interleave_template_update,
        ):
            new_status = set_workflow_enabled(
                team_id=self.team.id, user_id=self.user.id, workflow_id=flow_id, enabled=True
            )

        assert new_status == HogFlow.State.ACTIVE
        reloaded = HogFlow.objects.get(id=flow_id)
        assert reloaded.status == HogFlow.State.ACTIVE
        config = reloaded.actions[1]["config"]
        assert config["inputs"]["email"]["value"]["subject"] == "Order shipped"
        assert config["sensitive"] is False
        assert config["click_tracking_enabled"] is False

    def test_resuming_multi_step_workflow_preserves_each_steps_tracking_and_sensitivity(self):
        flow_id = create_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            content=_content(sensitive=True, click_tracking_enabled=True),
        )
        flow = HogFlow.objects.get(id=flow_id)
        second_email = deepcopy(flow.actions[1])
        second_email["id"] = "action-send-email-2"
        second_email["config"]["sensitive"] = False
        second_email["config"]["click_tracking_enabled"] = False
        actions = [flow.actions[0], flow.actions[1], second_email, flow.actions[2]]
        edges = [
            {"from": flow.actions[0]["id"], "to": flow.actions[1]["id"], "type": "continue"},
            {"from": flow.actions[1]["id"], "to": second_email["id"], "type": "continue"},
            {"from": second_email["id"], "to": flow.actions[2]["id"], "type": "continue"},
        ]
        HogFlow.objects.filter(id=flow_id).update(status=HogFlow.State.DRAFT, actions=actions, edges=edges)

        set_workflow_enabled(team_id=self.team.id, user_id=self.user.id, workflow_id=flow_id, enabled=True)

        reloaded = HogFlow.objects.get(id=flow_id)
        by_id = {action["id"]: action["config"] for action in reloaded.actions if action["type"] == "function_email"}
        assert by_id[flow.actions[1]["id"]]["sensitive"] is True
        assert by_id[flow.actions[1]["id"]]["click_tracking_enabled"] is True
        assert by_id["action-send-email-2"]["sensitive"] is False
        assert by_id["action-send-email-2"]["click_tracking_enabled"] is False

    def test_the_stored_workflow_passes_the_workflows_api_validation(self):
        flow = HogFlow.objects.get(
            id=create_transactional_email_workflow(
                team_id=self.team.id,
                user_id=self.user.id,
                content=_content(sensitive=True, click_tracking_enabled=True),
            )
        )

        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            deepcopy({"name": flow.name, "status": "active", "actions": flow.actions, "edges": flow.edges}),
            format="json",
        )
        assert created.status_code == 201, created.json()
        fetched = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}/")
        assert fetched.status_code == 200, fetched.json()
        body = fetched.json()
        assert body["trigger"] == flow.trigger == {"type": "api"}
        assert body["billable_action_types"] == flow.billable_action_types
        assert body["actions"][1]["config"]["click_tracking_enabled"] is True

    def test_workflows_api_rejects_non_boolean_and_strips_null_click_tracking_enabled(self):
        flow = HogFlow.objects.get(
            id=create_transactional_email_workflow(
                team_id=self.team.id,
                user_id=self.user.id,
                content=_content(sensitive=False, click_tracking_enabled=None),
            )
        )

        bad_actions = deepcopy(flow.actions)
        bad_actions[1]["config"]["click_tracking_enabled"] = "false"
        rejected = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {"name": "Bad click tracking", "status": "draft", "actions": bad_actions, "edges": flow.edges},
            format="json",
        )
        assert rejected.status_code == 400, rejected.json()

        null_actions = deepcopy(flow.actions)
        null_actions[1]["config"]["click_tracking_enabled"] = None
        accepted = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/",
            {"name": "Null click tracking", "status": "active", "actions": null_actions, "edges": flow.edges},
            format="json",
        )
        assert accepted.status_code == 201, accepted.json()
        assert "click_tracking_enabled" not in accepted.json()["actions"][1]["config"]

    def test_restoring_multi_step_revision_keeps_matching_and_conservative_fallback_click_tracking(self):
        flow_id = create_transactional_email_workflow(
            team_id=self.team.id,
            user_id=self.user.id,
            content=_content(subject="Original subject", sensitive=False, click_tracking_enabled=True),
        )
        flow = HogFlow.objects.get(id=flow_id)
        step_1 = deepcopy(flow.actions[1])
        step_2 = deepcopy(flow.actions[1])
        step_2["id"] = "action-send-email-2"
        step_2["config"]["click_tracking_enabled"] = False
        step_3 = deepcopy(flow.actions[1])
        step_3["id"] = "action-send-email-3"
        step_3["config"]["click_tracking_enabled"] = True

        # Revision 1 contains step_1, step_2, and an extra step_3 that is later removed from live.
        rev1_actions = [flow.actions[0], step_1, step_2, step_3, flow.actions[2]]
        rev1_edges = [
            {"from": flow.actions[0]["id"], "to": step_1["id"], "type": "continue"},
            {"from": step_1["id"], "to": step_2["id"], "type": "continue"},
            {"from": step_2["id"], "to": step_3["id"], "type": "continue"},
            {"from": step_3["id"], "to": flow.actions[2]["id"], "type": "continue"},
        ]
        HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow=flow, version=1).update(
            content={"name": flow.name, "actions": rev1_actions, "edges": rev1_edges}
        )

        # Live workflow keeps step_1 (True) and step_2 (False), without step_3.
        live_actions = [flow.actions[0], step_1, step_2, flow.actions[2]]
        live_edges = [
            {"from": flow.actions[0]["id"], "to": step_1["id"], "type": "continue"},
            {"from": step_1["id"], "to": step_2["id"], "type": "continue"},
            {"from": step_2["id"], "to": flow.actions[2]["id"], "type": "continue"},
        ]
        HogFlow.objects.filter(id=flow_id).update(actions=live_actions, edges=live_edges, version=2)

        published = self._restore_and_publish(flow_id, 1)

        by_id = {
            action["id"]: action["config"] for action in published["actions"] if action["type"] == "function_email"
        }
        assert by_id[step_1["id"]]["click_tracking_enabled"] is True
        assert by_id["action-send-email-2"]["click_tracking_enabled"] is False
        assert by_id["action-send-email-3"]["click_tracking_enabled"] is False

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
