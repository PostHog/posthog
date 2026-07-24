from typing import Any

from posthog.test.base import APIBaseTest

from posthog.models import User

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow, HogFlowActionTemplate


class TestHogFlowActionTemplateAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # A destination catalog template with one plain input (url) and one secret input (api_key).
        self.catalog_template = HogFunctionTemplate.objects.create(
            template_id="template-webhook",
            sha="1.0.0",
            name="Webhook",
            description="Generic webhook",
            code="return event",
            code_language="hog",
            type="destination",
            inputs_schema=[
                {"key": "url", "type": "string", "label": "URL", "required": True},
                {"key": "api_key", "type": "string", "label": "API key", "secret": True, "required": False},
            ],
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/hog_flow_action_templates{suffix}"

    def _create(self, **overrides: Any):
        payload = {
            "name": "Billing webhook",
            "template_id": "template-webhook",
            "inputs": {"url": {"value": "https://example.com/hook"}},
        }
        payload.update(overrides)
        return self.client.post(self._url(), payload)

    def test_create_and_retrieve(self):
        response = self._create()
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["name"] == "Billing webhook"
        assert body["template_id"] == "template-webhook"
        assert body["created_by"]["id"] == self.user.id
        assert body["usage_count"] == 0

    def test_inputs_are_compiled(self):
        # The worker executes the stored inputs directly, so a templated string must be compiled to
        # bytecode at save time (not left as a raw string).
        response = self._create(inputs={"url": {"value": "https://x.com/{event.distinct_id}"}})
        assert response.status_code == 201, response.json()
        template = HogFlowActionTemplate.objects.for_team(self.team.id).get(id=response.json()["id"])
        assert "bytecode" in template.inputs["url"]

    def test_unknown_template_id_rejected(self):
        response = self._create(template_id="template-does-not-exist")
        assert response.status_code == 400, response.json()

    def test_non_destination_template_rejected(self):
        HogFunctionTemplate.objects.create(
            template_id="template-transform",
            sha="1.0.0",
            name="Transform",
            code="return event",
            code_language="hog",
            type="transformation",
            inputs_schema=[],
        )
        response = self._create(template_id="template-transform")
        assert response.status_code == 400, response.json()

    def test_template_id_is_immutable(self):
        created = self._create().json()
        HogFunctionTemplate.objects.create(
            template_id="template-other",
            sha="1.0.0",
            name="Other",
            code="return event",
            code_language="hog",
            type="destination",
            inputs_schema=[],
        )
        response = self.client.patch(self._url(f"/{created['id']}"), {"template_id": "template-other"})
        assert response.status_code == 400, response.json()

    def test_secret_input_is_masked_on_read_and_encrypted_at_rest(self):
        response = self._create(inputs={"url": {"value": "https://x.com"}, "api_key": {"value": "super-secret"}})
        assert response.status_code == 201, response.json()
        body = response.json()
        # Masked in the API response, never the raw value.
        assert body["inputs"]["api_key"] == {"secret": True}
        assert "super-secret" not in response.content.decode()

        template = HogFlowActionTemplate.objects.for_team(self.team.id).get(id=body["id"])
        assert "api_key" not in template.inputs
        assert template.encrypted_inputs["api_key"]["value"] == "super-secret"

    def test_secret_marker_roundtrip_preserves_stored_value(self):
        created = self._create(inputs={"url": {"value": "https://x.com"}, "api_key": {"value": "super-secret"}}).json()
        # Sending the masked marker back must keep the stored secret; a plain input change must not wipe it.
        response = self.client.patch(
            self._url(f"/{created['id']}"),
            {"inputs": {"url": {"value": "https://y.com"}, "api_key": {"secret": True}}},
        )
        assert response.status_code == 200, response.json()
        template = HogFlowActionTemplate.objects.for_team(self.team.id).get(id=created["id"])
        assert template.encrypted_inputs["api_key"]["value"] == "super-secret"
        assert template.inputs["url"]["value"] == "https://y.com"

    def test_secret_can_be_replaced_with_new_value(self):
        created = self._create(inputs={"url": {"value": "https://x.com"}, "api_key": {"value": "old"}}).json()
        response = self.client.patch(
            self._url(f"/{created['id']}"),
            {"inputs": {"url": {"value": "https://x.com"}, "api_key": {"value": "new"}}},
        )
        assert response.status_code == 200, response.json()
        template = HogFlowActionTemplate.objects.for_team(self.team.id).get(id=created["id"])
        assert template.encrypted_inputs["api_key"]["value"] == "new"

    def _link_flow(
        self, action_template_id: str, *, status: str = HogFlow.State.ACTIVE, draft: bool = False
    ) -> HogFlow:
        linked_action = {
            "id": "action_1",
            "name": "Webhook",
            "type": "function",
            "config": {"template_id": "template-webhook", "action_template_id": action_template_id},
        }
        actions = [] if draft else [linked_action]
        return HogFlow.objects.create(
            team=self.team,
            name="Linked flow",
            status=status,
            actions=actions,
            draft={"actions": [linked_action]} if draft else None,
        )

    def test_delete_blocked_when_referenced_by_active_flow(self):
        created = self._create().json()
        self._link_flow(created["id"])
        response = self.client.patch(self._url(f"/{created['id']}"), {"deleted": True})
        assert response.status_code == 400, response.json()
        assert not HogFlowActionTemplate.objects.for_team(self.team.id).get(id=created["id"]).deleted

    def test_delete_blocked_when_referenced_only_by_draft(self):
        created = self._create().json()
        self._link_flow(created["id"], status=HogFlow.State.ACTIVE, draft=True)
        response = self.client.patch(self._url(f"/{created['id']}"), {"deleted": True})
        assert response.status_code == 400, response.json()

    def test_delete_allowed_when_only_archived_flow_references(self):
        created = self._create().json()
        self._link_flow(created["id"], status=HogFlow.State.ARCHIVED)
        response = self.client.patch(self._url(f"/{created['id']}"), {"deleted": True})
        assert response.status_code == 200, response.json()
        assert HogFlowActionTemplate.objects.for_team(self.team.id).get(id=created["id"]).deleted

    def test_hard_delete_is_forbidden(self):
        created = self._create().json()
        response = self.client.delete(self._url(f"/{created['id']}"))
        assert response.status_code == 405, response.content

    def test_usage_endpoint_and_count(self):
        created = self._create().json()
        self._link_flow(created["id"])
        usage = self.client.get(self._url(f"/{created['id']}/usage"))
        assert usage.status_code == 200, usage.json()
        assert usage.json()["count"] == 1
        assert usage.json()["hog_flows"][0]["name"] == "Linked flow"

        listed = self.client.get(self._url())
        assert listed.json()["results"][0]["usage_count"] == 1

    def test_template_id_filter(self):
        self._create()
        HogFunctionTemplate.objects.create(
            template_id="template-slack",
            sha="1.0.0",
            name="Slack",
            code="return event",
            code_language="hog",
            type="destination",
            inputs_schema=[],
        )
        self._create(name="Slack thing", template_id="template-slack", inputs={})

        filtered = self.client.get(self._url("?template_id=template-webhook"))
        assert filtered.status_code == 200, filtered.json()
        results = filtered.json()["results"]
        assert len(results) == 1
        assert results[0]["template_id"] == "template-webhook"

    def test_team_isolation(self):
        created = self._create().json()
        _, other_team, other_user = User.objects.bootstrap("Other", "other@x.com", "pw")
        self.client.force_login(other_user)
        response = self.client.get(f"/api/projects/{other_team.id}/hog_flow_action_templates/{created['id']}")
        assert response.status_code == 404, response.content
