from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models.integration import Integration

from products.cdp.backend.api.hog_function import HogFunctionInvocationSerializer
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.workflows.backend.facade.api import ensure_sandbox_email_sender
from products.workflows.backend.facade.workflows import get_workflow_edit_state
from products.workflows.backend.models.hog_flow import HogFlow
from products.workflows.backend.presentation.views.hog_flow import HogFlowInvocationSerializer


@override_settings(
    WORKFLOWS_SANDBOX_SENDER_DOMAIN="sandbox.example.com",
    SES_SANDBOX_FROM_ADDRESS="hello@sandbox.example.com",
    SES_SANDBOX_TENANT_NAME="posthog-sandbox",
)
class TestSandboxSenderValidation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.flag_enabled = flag.start()
        self.addCleanup(flag.stop)
        capture = patch("posthoganalytics.capture")
        capture.start()
        self.addCleanup(capture.stop)
        self.sender = Integration.objects.get(
            team_id=self.team.id, id=ensure_sandbox_email_sender(self.team.id).integration_id
        )
        self.email_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        HogFunctionTemplate.objects.create(
            template_id="template-email",
            name="Email",
            type="destination",
            status="hidden",
            code="return sendEmail(inputs.email);",
            inputs_schema=self.email_schema,
        )

    def _workflow(self) -> dict[str, Any]:
        return {
            "name": "Sandbox workflow",
            "actions": [
                {
                    "id": "trigger",
                    "type": "trigger",
                    "name": "Trigger",
                    "config": {
                        "type": "event",
                        "filters": {"events": [{"id": "$pageview", "type": "events", "order": 0}]},
                    },
                },
                {
                    "id": "email",
                    "type": "function_email",
                    "name": "Send email",
                    "config": {"inputs": {"email": {"value": self._email()}}},
                },
                {"id": "exit", "type": "exit", "name": "Exit", "config": {}},
            ],
            "edges": [
                {"from": "trigger", "to": "email", "type": "continue"},
                {"from": "email", "to": "exit", "type": "continue"},
            ],
        }

    def _email(self) -> dict[str, Any]:
        return {
            "from": {"integrationId": self.sender.id},
            "to": "member@example.com",
            "subject": "Hello",
            "html": "<p>Hello</p>",
        }

    def _function(self) -> dict[str, Any]:
        return {
            "name": "Sandbox destination",
            "type": "destination",
            "hog": "return 1;",
            "inputs_schema": self.email_schema,
            "inputs": {"email": {"value": self._email()}},
        }

    @parameterized.expand(
        [
            (f"broadcast_{shape}_flag_{'on' if flag_on else 'off'}", "broadcasts", shape, flag_on, "broadcast")
            for shape in ("integer", "float", "string", "malformed_rotation")
            for flag_on in (True, False)
        ]
        + [
            (
                f"transactional_flag_{'on' if flag_on else 'off'}",
                "transactional_emails",
                "integer",
                flag_on,
                "transactional",
            )
            for flag_on in (True, False)
        ]
    )
    def test_broadcasts_and_transactional_email_cannot_select_the_sandbox_sender(
        self, _name: str, origin_product: str, sender_shape: str, flag_on: bool, product_word: str
    ) -> None:
        self.flag_enabled.return_value = flag_on
        workflow = self._workflow()
        workflow["origin_product"] = origin_product
        sender = workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]
        if sender_shape == "float":
            sender["integrationId"] = float(self.sender.id)
        elif sender_shape == "string":
            sender["integrationId"] = str(self.sender.id)
        elif sender_shape == "malformed_rotation":
            sender["integrationIds"] = self.sender.id

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "sandbox sender" in response.json()["detail"].lower()
        assert product_word in response.json()["detail"].lower()

    @parameterized.expand(
        [
            ("flag_on", True, {}),
            ("flag_off", False, {}),
            ("from_address_off_the_sandbox_domain", True, {"SES_SANDBOX_FROM_ADDRESS": "hello@example.org"}),
        ]
    )
    def test_destination_cannot_select_the_sandbox_sender(self, _name: str, flag_on: bool, settings: dict) -> None:
        self.flag_enabled.return_value = flag_on
        with override_settings(**settings):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                self._function(),
            )

        assert response.status_code == 400, response.json()
        assert "sandbox sender" in response.json()["detail"].lower()
        assert "workflow email steps and test sends" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            ("hog_in_a_broadcast", "hog", "hog_flows", "broadcasts", lambda sid: {"integrationId": f"{{{sid}}}"}),
            (
                "liquid_in_a_destination",
                "liquid",
                "hog_functions/",
                None,
                lambda sid: {"integrationId": f"{{{{ {sid} }}}}"},
            ),
            ("non_ascii_digit_in_a_destination", "hog", "hog_functions/", None, lambda _sid: {"integrationId": "²"}),
            (
                "digit_string_too_long_for_an_id_in_a_destination",
                "hog",
                "hog_functions/",
                None,
                lambda _sid: {"integrationId": "9" * 5000},
            ),
            (
                "whole_from_in_a_destination",
                "hog",
                "hog_functions/",
                None,
                lambda sid: f"{{ {{'integrationId': {sid}}} }}",
            ),
            (
                "template_beside_the_sandbox_sender_in_a_workflow",
                "hog",
                "hog_flows",
                None,
                lambda sid: {"integrationIds": [sid, "{inputs.sender}"]},
            ),
            (
                "templated_rotation_in_a_workflow",
                "hog",
                "hog_flows",
                None,
                lambda sid: {"integrationId": sid + 1, "integrationIds": f"{{[{sid}]}}"},
            ),
        ]
    )
    def test_templated_sender_id_cannot_reach_the_sandbox_sender(
        self, _name: str, templating: str, endpoint: str, origin_product: str | None, sender: Any
    ) -> None:
        self.email_schema[0]["templating"] = templating
        HogFunctionTemplate.objects.filter(template_id="template-email").update(inputs_schema=self.email_schema)
        payload = self._workflow() if endpoint == "hog_flows" else self._function()
        if endpoint == "hog_flows":
            if origin_product:
                payload["origin_product"] = origin_product
            email = payload["actions"][1]["config"]["inputs"]["email"]["value"]
        else:
            email = payload["inputs"]["email"]["value"]
        email["from"] = sender(self.sender.id)

        response = self.client.post(f"/api/projects/{self.team.id}/{endpoint}", payload)

        assert response.status_code == 400, response.json()
        assert "templated sender" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            (f"{name}{'_secret' if secret else ''}", change, secret)
            for name, change in (("disabled", {"enabled": False}), ("deleted", {"deleted": True}))
            for secret in (False, True)
        ]
    )
    def test_stored_destination_with_the_sandbox_sender_can_still_be(
        self, _name: str, change: dict, secret: bool
    ) -> None:
        stored_input = {"email": {"value": self._email()}}
        function = HogFunction.objects.create(
            team=self.team,
            name="Stored destination",
            type="destination",
            hog="return 1;",
            inputs_schema=[{**self.email_schema[0], "secret": secret}],
            inputs={} if secret else stored_input,
            encrypted_inputs=stored_input if secret else None,
            enabled=True,
        )

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_functions/{function.id}/", change)

        assert response.status_code == 200, response.json()

    @parameterized.expand(
        [
            ("dictionary_input_retyped_as_email", "dictionary", "email"),
            ("email_value_moved_to_another_input", "native_email", "backup"),
        ]
    )
    def test_stored_sandbox_value_is_not_grandfathered_into_a_different_email_input(
        self, _name: str, stored_type: str, new_key: str
    ) -> None:
        function = HogFunction.objects.create(
            team=self.team,
            name="Stored destination",
            type="destination",
            hog="return 1;",
            inputs_schema=[{"key": "email", "type": stored_type}],
            inputs={"email": {"value": self._email()}},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function.id}/",
            {
                "inputs_schema": [{**self.email_schema[0], "key": new_key}],
                "inputs": {new_key: {"value": self._email()}},
            },
        )

        assert response.status_code == 400, response.json()
        assert "workflow email steps and test sends" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            ("unchanged_mapping_keeps_its_stored_sender", "mapping", "sandbox", ["stored"], None),
            (
                "duplicated_mapping_cannot_borrow_its_original_sender",
                "mapping",
                "sandbox",
                ["stored", "stored"],
                "workflow email steps and test sends",
            ),
            (
                "own_sender_copy_ahead_of_the_original_leaves_it_its_sender",
                "mapping",
                "sandbox",
                ["own", "stored"],
                None,
            ),
            (
                "new_mapping_cannot_borrow_the_top_level_sender",
                "top_level",
                "sandbox",
                ["stored"],
                "workflow email steps and test sends",
            ),
            ("templated_mapping_can_clear_its_reply_to", "mapping", "templated", ["reply_to_cleared"], None),
            (
                "duplicated_templated_mapping_cannot_borrow_its_original_sender",
                "mapping",
                "templated",
                ["reply_to_cleared", "stored"],
                "templated sender",
            ),
        ]
    )
    def test_mapping_sender_is_compared_only_with_its_own_stored_mapping(
        self, _name: str, stored_in: str, stored_sender: str, submitted: list[str], expected_error: str | None
    ) -> None:
        own_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"provider": "ses", "domain": "example.com", "email": "sender@example.com", "verified": True},
        )
        email = self._email()
        if stored_sender == "templated":
            email.update({"from": {"integrationId": "{inputs.sender}"}, "replyTo": "stored-reply@example.com"})
        backup = {**self._email(), "from": {"integrationId": own_sender.id}}
        mapping: dict[str, Any] = {
            "name": "Mapping",
            "inputs_schema": [*self.email_schema, {**self.email_schema[0], "key": "backup"}],
            "inputs": {"email": {"value": email}, "backup": {"value": backup}},
        }
        function = HogFunction.objects.create(
            team=self.team,
            name="Stored destination",
            type="destination",
            hog="return 1;",
            inputs_schema=self.email_schema if stored_in == "top_level" else [],
            inputs={"email": {"value": email}} if stored_in == "top_level" else {},
            mappings=[mapping] if stored_in == "mapping" else None,
        )
        mappings = [deepcopy(mapping) for _ in submitted]
        for sent, change in zip(mappings, submitted):
            if change == "own":
                sent["inputs"]["email"]["value"]["from"] = {"integrationId": own_sender.id}
            elif change == "reply_to_cleared":
                sent["inputs"]["email"]["value"]["replyTo"] = ""

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function.id}/", {"mappings": mappings}
        )

        if expected_error is None:
            assert response.status_code == 200, response.json()
        else:
            assert response.status_code == 400, response.json()
            assert expected_error in response.json()["detail"].lower()

    @parameterized.expand(
        [
            (
                "own_rotation_beside_a_stale_sandbox_fallback",
                "native_email",
                lambda own_id, sandbox_id: {"integrationId": sandbox_id, "integrationIds": [own_id]},
            ),
            ("literal_from_address_without_an_integration", "email", lambda _own_id, _sandbox_id: "sender@example.com"),
        ]
    )
    def test_destination_that_cannot_reach_the_sandbox_sender_saves(
        self, _name: str, input_type: str, sender: Any
    ) -> None:
        own_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"provider": "ses", "domain": "example.com", "email": "sender@example.com", "verified": True},
        )
        function = self._function()
        function["inputs_schema"] = [{**self.email_schema[0], "type": input_type}]
        function["inputs"]["email"]["value"]["from"] = sender(own_sender.id, self.sender.id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", function)

        assert response.status_code == 201, response.json()

    @parameterized.expand([("created",), ("changed_from_an_email_step",)])
    def test_generic_workflow_step_cannot_select_the_sandbox_sender_with_a_legacy_email_schema(
        self, origin: str
    ) -> None:
        template = HogFunctionTemplate.objects.get(template_id="template-email")
        template.inputs_schema = [{**self.email_schema[0], "type": "email"}]
        template.save()
        workflow = self._workflow()
        created_id = None
        if origin == "changed_from_an_email_step":
            created = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)
            assert created.status_code == 201, created.json()
            created_id = created.json()["id"]
        workflow["actions"][1]["type"] = "function"
        workflow["actions"][1]["config"]["template_id"] = "template-email"

        if created_id is None:
            response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)
        else:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{created_id}", {"actions": workflow["actions"]}
            )

        assert response.status_code == 400, response.json()
        assert "workflow email steps and test sends" in response.json()["detail"].lower()

    def test_workflow_can_select_the_sandbox_sender_alone(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._workflow())

        assert response.status_code == 201, response.json()
        assert response.json()["actions"][1]["config"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": self.sender.id
        }

    @parameterized.expand(
        [
            ("exit", "exit", "missing-template"),
            ("function", "function", "missing-template"),
            ("function_email", "function_email", "missing-template"),
            ("function_email_on_a_template_without_an_email_input", "function_email", "template-webhook"),
        ]
    )
    def test_inert_email_data_is_not_an_existing_sandbox_sender(
        self, _name: str, action_type: str, template_id: str
    ) -> None:
        HogFunctionTemplate.objects.create(
            template_id="template-webhook",
            name="Webhook",
            type="destination",
            status="hidden",
            code="return 1;",
            inputs_schema=[{"key": "url", "type": "string", "required": True}],
        )
        workflow = self._workflow()
        action = workflow["actions"][1]
        action["type"] = action_type
        action["config"]["template_id"] = template_id
        email = action["config"]["inputs"]["email"]["value"]
        email["from"]["name"] = "New sender"
        email["replyTo"] = "reply@example.com"
        created = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)
        if action_type == "function_email":
            assert created.status_code == 400, created.json()
            assert "fixed From address and name" in created.json()["detail"]
            return
        assert created.status_code == 201, created.json()
        action["type"] = "function_email"
        action["config"].pop("template_id")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}",
            {"actions": workflow["actions"]},
        )

        assert response.status_code == 400, response.json()
        assert "fixed From address and name" in response.json()["detail"]

    def test_sandbox_sender_cannot_rotate_with_own_senders(self) -> None:
        own_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"provider": "ses", "domain": "example.com", "email": "sender@example.com", "verified": True},
        )
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"] = {
            "integrationIds": [self.sender.id, own_sender.id]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "sandbox sender must be the only sender" in response.json()["detail"].lower()

    def test_oversized_sender_rotation_is_rejected_before_looking_up_integrations(self) -> None:
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]["integrationIds"] = list(range(100))

        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "At most 10 email senders" in response.json()["detail"]
        assert response.json()["attr"] == "actions__1__inputs__email"
        assert not [query for query in queries if 'FROM "posthog_integration"' in query["sql"]]

    @parameterized.expand(
        [
            ("custom From address", "email", "custom@sandbox.example.com"),
            ("templated From address", "email", "{{ person.properties.email }}"),
            ("custom From name", "name", "Custom sender"),
            ("Reply-To", "replyTo", "reply@example.com"),
        ]
    )
    def test_sandbox_sender_cannot_use_sender_overrides(self, _name: str, field: str, value: str) -> None:
        workflow = self._workflow()
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        if field == "replyTo":
            email[field] = value
        else:
            email["from"][field] = value

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)

        assert response.status_code == 400, response.json()
        assert "fixed From address and name" in response.json()["detail"]
        assert "Reply-To" in response.json()["detail"]

    @parameterized.expand(
        [
            (f"{endpoint}_{name}", endpoint, setting)
            for endpoint in ("hog_flows", "hog_functions/")
            for name, setting in (
                ("no_tenant", {"SES_SANDBOX_TENANT_NAME": ""}),
                ("no_from_address", {"SES_SANDBOX_FROM_ADDRESS": ""}),
            )
        ]
    )
    def test_saves_skip_the_sandbox_checks_without_sandbox_settings(
        self, _name: str, endpoint: str, setting: dict
    ) -> None:
        payload = self._workflow() if endpoint == "hog_flows" else self._function()

        with (
            override_settings(**setting),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.client.post(f"/api/projects/{self.team.id}/{endpoint}", payload)

        assert response.status_code == 201, response.json()
        assert not [query for query in queries.captured_queries if '"posthog_integration"' in query["sql"]]

    def test_flag_off_save_looks_up_sandbox_senders_once_for_many_own_senders(self) -> None:
        self.flag_enabled.return_value = False
        workflow = self._workflow()
        trigger, email_step, exit_step = workflow["actions"]
        steps = []
        for index in range(5):
            own_sender = Integration.objects.create(
                team=self.team,
                kind="email",
                config={"provider": "ses", "domain": "example.com", "email": f"sender{index}@example.com"},
            )
            step = deepcopy(email_step)
            step["id"] = f"email-{index}"
            step["config"]["inputs"]["email"]["value"]["from"] = {"integrationId": own_sender.id}
            steps.append(step)
        chain = [trigger, *steps, exit_step]
        workflow["actions"] = chain
        workflow["edges"] = [
            {"from": source["id"], "to": target["id"], "type": "continue"} for source, target in zip(chain, chain[1:])
        ]

        def integration_queries() -> int:
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)
            assert response.status_code == 201, response.json()
            return len([query for query in queries.captured_queries if '"posthog_integration"' in query["sql"]])

        with override_settings(SES_SANDBOX_TENANT_NAME=""):
            without_sandbox_checks = integration_queries()

        assert integration_queries() == without_sandbox_checks + 1

    def test_test_send_configuration_can_select_the_sandbox_sender(self) -> None:
        serializer = HogFunctionInvocationSerializer(
            data={"configuration": self._function()},
            context={"get_team": lambda: self.team, "view": SimpleNamespace(action="invocations")},
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["configuration"]["inputs"]["email"]["value"]["from"] == {
            "integrationId": self.sender.id
        }

    @parameterized.expand([("missing",), ("cleared",)])
    def test_broadcast_test_cannot_clear_its_origin(self, origin: str) -> None:
        workflow = self._workflow()
        stored = HogFlow.objects.create(
            team=self.team,
            name="Broadcast",
            origin_product="broadcasts",
            actions=workflow["actions"],
            edges=workflow["edges"],
        )
        if origin == "cleared":
            workflow["origin_product"] = None
        serializer = HogFlowInvocationSerializer(
            data={"configuration": workflow},
            context={
                "get_team": lambda: self.team,
                "view": SimpleNamespace(action="invocations"),
                "instance": get_workflow_edit_state(
                    team_id=self.team.id, workflow_id=stored.id, user_access_control=None, required_level=None
                ),
            },
        )

        assert not serializer.is_valid(), serializer.validated_data
        assert "broadcast" in str(serializer.errors).lower()

    @parameterized.expand([("live",), ("draft",)])
    def test_unchanged_legacy_sender_survives_unrelated_edits(self, variant: str) -> None:
        live = self._workflow()
        live_email = live["actions"][1]["config"]["inputs"]["email"]["value"]
        live_email["from"].update({"email": "legacy@example.com", "name": "Legacy sender"})
        live_email["replyTo"] = "legacy-reply@example.com"
        draft = deepcopy(live)
        draft_email = draft["actions"][1]["config"]["inputs"]["email"]["value"]
        draft_email["from"]["name"] = "Draft legacy sender"
        draft_email["replyTo"] = "draft-reply@example.com"
        stored = HogFlow.objects.create(
            team=self.team,
            name="Legacy workflow",
            actions=live["actions"],
            edges=live["edges"],
            status=HogFlow.State.ACTIVE,
            draft=draft,
        )
        actions = deepcopy(live["actions"] if variant == "live" else draft["actions"])
        actions[1]["config"]["inputs"]["email"]["value"]["subject"] = "Updated legacy subject"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{stored.id}",
            {"name": "Renamed legacy workflow", "actions": actions},
        )

        assert response.status_code == 200, response.json()

    def _stored_templated_workflow(self, action_type: str) -> tuple[HogFlow, list[dict[str, Any]]]:
        workflow = self._workflow()
        action = workflow["actions"][1]
        action["type"] = action_type
        if action_type == "function":
            action["config"]["template_id"] = "template-email"
        action["config"]["inputs"]["email"]["value"]["from"] = {"integrationId": "{inputs.sender}"}
        action["config"]["inputs"]["email"]["value"]["replyTo"] = "stored-reply@example.com"
        stored = HogFlow.objects.create(
            team=self.team, name="Templated workflow", actions=workflow["actions"], edges=workflow["edges"]
        )
        return stored, deepcopy(workflow["actions"])

    @parameterized.expand(
        [
            ("email_step_renamed", "subject", "Renamed subject", "function_email"),
            ("generic_step_renamed", "subject", "Renamed subject", "function"),
            ("reply_to_cleared", "replyTo", "", "function_email"),
        ]
    )
    def test_stored_templated_sender_survives_edits_that_keep_it(
        self, _name: str, field: str, value: str, action_type: str
    ) -> None:
        stored, actions = self._stored_templated_workflow(action_type)
        actions[1]["config"]["inputs"]["email"]["value"][field] = value

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{stored.id}", {"actions": actions})

        assert response.status_code == 200, response.json()

    @parameterized.expand(
        [
            ("new_generic_step_copies_it", "add_step", "function"),
            ("duplicated_step", "add_step", "function_email"),
            ("other_step_switched_to_it", "switch_other_step", "function_email"),
            ("step_type_switched", "switch_type", "function"),
            ("inert_generic_step_switched_to_the_email_template", "switch_template", "function"),
            ("reply_to_changed", "change_reply_to", "function_email"),
        ]
    )
    def test_stored_templated_sender_is_not_grandfathered_into_a_changed_sender(
        self, _name: str, change: str, action_type: str
    ) -> None:
        stored, actions = self._stored_templated_workflow("function_email")
        templated_from = deepcopy(actions[1]["config"]["inputs"]["email"]["value"]["from"])
        if change == "add_step":
            copy = deepcopy(actions[1])
            copy.update({"id": "email-copy", "type": action_type})
            if action_type == "function":
                copy["config"]["template_id"] = "template-email"
            actions.insert(2, copy)
        elif change == "switch_other_step":
            other = deepcopy(actions[1])
            other["id"] = "email-other"
            other["config"]["inputs"]["email"]["value"]["from"] = {"integrationId": self.sender.id}
            stored.actions = [*stored.actions[:2], other, *stored.actions[2:]]
            stored.save()
            other_edited = deepcopy(other)
            other_edited["config"]["inputs"]["email"]["value"]["from"] = templated_from
            actions.insert(2, other_edited)
        elif change == "switch_type":
            actions[1]["type"] = action_type
            actions[1]["config"]["template_id"] = "template-email"
        elif change == "change_reply_to":
            actions[1]["config"]["inputs"]["email"]["value"]["replyTo"] = "new-reply@example.com"
        elif change == "switch_template":
            stored.actions[1]["type"] = action_type
            stored.actions[1]["config"]["template_id"] = "missing-template"
            stored.save()
            actions[1]["type"] = action_type
            actions[1]["config"]["template_id"] = "template-email"
        else:
            raise AssertionError(change)

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{stored.id}", {"actions": actions})

        assert response.status_code == 400, response.json()
        assert "templated sender" in response.json()["detail"].lower()

    @parameterized.expand([("transactional_emails",), ("transactional_email_keys",)])
    def test_transactional_workflow_update_cannot_select_the_sandbox_sender(self, origin_product: str) -> None:
        own_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"provider": "ses", "domain": "example.com", "email": "sender@example.com", "verified": True},
        )
        workflow = self._workflow()
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        email["from"] = {"integrationId": own_sender.id}
        stored = HogFlow.objects.create(
            team=self.team,
            name="Transactional workflow",
            actions=deepcopy(workflow["actions"]),
            edges=workflow["edges"],
            origin_product=origin_product,
        )
        email["from"] = {"integrationId": self.sender.id}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{stored.id}", {"actions": workflow["actions"]}
        )

        assert response.status_code == 400, response.json()
        assert "transactional" in response.json()["detail"].lower()

    @parameterized.expand([("email",), ("name",), ("replyTo",)])
    def test_legacy_sender_overrides_cannot_be_changed(self, field: str) -> None:
        workflow = self._workflow()
        email = workflow["actions"][1]["config"]["inputs"]["email"]["value"]
        email["from"].update({"email": "legacy@example.com", "name": "Legacy sender"})
        email["replyTo"] = "legacy-reply@example.com"
        stored = HogFlow.objects.create(
            team=self.team,
            name="Legacy workflow",
            actions=workflow["actions"],
            edges=workflow["edges"],
            status=HogFlow.State.ACTIVE,
        )
        if field == "replyTo":
            email[field] = "changed@example.com"
        else:
            email["from"][field] = "changed@example.com" if field == "email" else "Changed sender"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{stored.id}",
            {"actions": workflow["actions"]},
        )

        assert response.status_code == 400, response.json()
        assert "fixed From address and name" in response.json()["detail"]

    def test_malformed_sender_rotation_returns_a_validation_error(self) -> None:
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"]["email"]["value"]["from"]["integrationIds"] = self.sender.id

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow, HTTP_X_POSTHOG_CLIENT="mcp")

        assert response.status_code == 400, response.json()
        assert "list of Integration IDs" in response.json()["detail"]

    def test_null_email_inputs_return_a_validation_error(self) -> None:
        workflow = self._workflow()
        workflow["actions"][1]["config"]["inputs"] = None

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow, HTTP_X_POSTHOG_CLIENT="mcp")

        assert response.status_code == 400, response.json()
