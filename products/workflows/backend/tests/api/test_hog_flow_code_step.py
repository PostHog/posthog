from copy import deepcopy

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.hog_flow import WORKFLOW_CODE_TEMPLATE_ID, workflow_code_hash

TRIGGER = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}
EXIT = {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}
EDGES = [
    {"from": "trigger_node", "to": "code_1", "type": "continue"},
    {"from": "code_1", "to": "exit_node", "type": "continue"},
]
GATE = "products.workflows.backend.presentation.views.hog_flow.gated_template_enabled"
COMPILE = "products.workflows.backend.presentation.views.hog_flow.compile_hog"
FORGED = ["_H", 1, 32, "forged"]
CODE = "return fetch('https://example.com/a').status"


def _code_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = WORKFLOW_CODE_TEMPLATE_ID
    template["status"] = "hidden"
    template["code"] = "return null"
    template["inputs_schema"] = [
        {"key": "params", "type": "dictionary", "label": "Parameters", "secret": False, "required": False},
        {
            "key": "secrets",
            "type": "dictionary",
            "label": "Secrets",
            "secret": True,
            "required": False,
            "templating": False,
        },
    ]
    return template


def code_action(hog: str, **config) -> dict:
    return {
        "id": "code_1",
        "name": "Code",
        "type": "function",
        "config": {"template_id": WORKFLOW_CODE_TEMPLATE_ID, "inputs": {}, "hog": hog, **config},
    }


class TestHogFlowCodeStep(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(_code_template())

    def _save(self, action: dict, flow_id: str | None = None, flag: bool = True):
        body = {"name": "Code flow", "actions": [TRIGGER, action, EXIT], "edges": EDGES}
        url = f"/api/projects/{self.team.id}/hog_flows"
        with patch(GATE, return_value=flag):
            if flow_id:
                return self.client.patch(f"{url}/{flow_id}", body, format="json")
            # The MCP client header selects strict validation, the path API callers use.
            return self.client.post(url, body, format="json", HTTP_X_POSTHOG_CLIENT="mcp")

    def _stored_config(self, flow_id: str) -> dict:
        actions = HogFlow.objects.get(id=flow_id).actions
        return next(action for action in actions if action["id"] == "code_1")["config"]

    def test_compiles_the_code_and_discards_client_bytecode(self):
        response = self._save(code_action(CODE, bytecode=FORGED, bytecode_hash=workflow_code_hash(CODE)))

        assert response.status_code == 201, response.json()
        config = self._stored_config(response.json()["id"])
        assert config["bytecode"] != FORGED
        assert "https://example.com/a" in config["bytecode"]
        assert config["bytecode_hash"] == workflow_code_hash(CODE)

    def test_unchanged_code_reuses_stored_bytecode_and_ignores_a_matching_forged_hash(self):
        created = self._save(code_action(CODE))
        assert created.status_code == 201, created.json()
        flow_id = created.json()["id"]
        compiled = self._stored_config(flow_id)["bytecode"]

        with patch(COMPILE) as compile_hog:
            response = self._save(
                code_action(CODE, bytecode=FORGED, bytecode_hash=workflow_code_hash(CODE)), flow_id=flow_id
            )

        assert response.status_code == 200, response.json()
        compile_hog.assert_not_called()
        assert self._stored_config(flow_id)["bytecode"] == compiled

        changed = "return fetch('https://example.com/b').status"
        response = self._save(code_action(changed), flow_id=flow_id)

        assert response.status_code == 200, response.json()
        assert "https://example.com/b" in self._stored_config(flow_id)["bytecode"]

    @parameterized.expand(
        [
            ("syntax_error", "return {", True, "Hog code has errors"),
            ("disallowed_function", "sendEmail({})", True, "Hog function `sendEmail` is not implemented"),
            ("oversize", "return '" + "x" * 100 * 1024 + "'", True, "exceeds the maximum size of 100KB"),
            ("flag_off", CODE, False, "Code steps are not available for this project"),
        ]
    )
    def test_rejects_unusable_code(self, _name: str, hog: str, flag: bool, message: str):
        response = self._save(code_action(hog), flag=flag)

        assert response.status_code == 400, response.json()
        assert message in str(response.json())


class TestCompileCode(APIBaseTest):
    def _compile(self, hog: str, flag: bool = True):
        with patch(GATE, return_value=flag):
            return self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/compile_code/", {"hog": hog}, format="json"
            )

    @parameterized.expand(
        [
            ("compiles", CODE, {"ok": True, "errors": []}),
            (
                "disallowed_function",
                "let a := 1\n  sendEmail({})",
                {
                    "ok": False,
                    "errors": [{"message": "Hog function `sendEmail` is not implemented", "line": 2, "column": 3}],
                },
            ),
            (
                "oversize",
                "return '" + "x" * 100 * 1024 + "'",
                {"ok": False, "errors": [{"message": "Hog code exceeds the maximum size of 100KB."}]},
            ),
        ]
    )
    def test_reports_compile_errors_with_their_position(self, _name: str, hog: str, expected: dict):
        response = self._compile(hog)

        assert response.status_code == 200, response.json()
        assert response.json() == expected

    def test_points_a_syntax_error_at_its_line(self):
        response = self._compile("let a := 1\nreturn {")

        assert response.status_code == 200, response.json()
        [error] = response.json()["errors"]
        assert error["message"].startswith("Hog code has errors:")
        assert error["line"] == 2
        assert "column" in error

    def test_is_refused_when_the_flag_is_off(self):
        response = self._compile(CODE, flag=False)

        assert response.status_code == 403, response.json()
