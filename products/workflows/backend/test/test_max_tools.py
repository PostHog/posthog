import json

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from products.workflows.backend.max_tools import CreateMessageTemplateTool

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException


def _template(design: dict) -> str:
    return json.dumps(
        {
            "name": "Welcome",
            "description": "",
            "content": {
                "templating": "liquid",
                "email": {
                    "subject": "Hi",
                    "text": "Hi",
                    "html": "<p>Hi</p>",
                    "design": design,
                },
            },
        }
    )


VALID_DESIGN = {"body": {"rows": [{"id": "r1"}]}, "schemaVersion": 17}
INVALID_DESIGN = {"body": {"rows": []}}  # empty rows + no schemaVersion


class TestCreateMessageTemplateTool(BaseTest):
    def _tool(self) -> CreateMessageTemplateTool:
        return CreateMessageTemplateTool(team=self.team, user=self.user)

    @patch("products.workflows.backend.max_tools.WebBaseLoader")
    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_blocked_url_is_not_fetched(self, mock_model, mock_loader):
        mock_model.return_value.invoke.return_value = MagicMock(content=_template(VALID_DESIGN))

        # Link-local metadata endpoint — must be refused by the SSRF guard.
        self._tool()._run_impl(instructions="Use http://169.254.169.254/latest/meta-data for branding")

        mock_loader.assert_not_called()

    @patch("products.workflows.backend.max_tools.WebBaseLoader")
    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_invalid_design_triggers_retry(self, mock_model, mock_loader):
        mock_model.return_value.invoke.side_effect = [
            MagicMock(content=_template(INVALID_DESIGN)),
            MagicMock(content=_template(VALID_DESIGN)),
        ]

        _content, template_json = self._tool()._run_impl(instructions="A welcome email")

        self.assertEqual(json.loads(template_json)["content"]["email"]["design"], VALID_DESIGN)
        self.assertEqual(mock_model.return_value.invoke.call_count, 2)
        mock_loader.assert_not_called()

    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_valid_output_passes_first_try(self, mock_model):
        mock_model.return_value.invoke.return_value = MagicMock(content=_template(VALID_DESIGN))

        _content, template_json = self._tool()._run_impl(instructions="A welcome email")

        self.assertEqual(json.loads(template_json)["name"], "Welcome")
        self.assertEqual(mock_model.return_value.invoke.call_count, 1)

    def test_validate_design_rejects_missing_rows(self):
        with self.assertRaises(PydanticOutputParserException):
            CreateMessageTemplateTool._validate_design({"body": {}, "schemaVersion": 17})

    def test_validate_design_rejects_missing_schema_version(self):
        with self.assertRaises(PydanticOutputParserException):
            CreateMessageTemplateTool._validate_design({"body": {"rows": [{"id": "r1"}]}})

    def test_validate_design_accepts_valid(self):
        CreateMessageTemplateTool._validate_design(VALID_DESIGN)

    @patch("products.workflows.backend.max_tools.is_url_allowed", return_value=(True, None))
    @patch("products.workflows.backend.max_tools.WebBaseLoader")
    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_allowed_url_is_fetched_and_passed_to_model(self, mock_model, mock_loader, _mock_allowed):
        mock_model.return_value.invoke.return_value = MagicMock(content=_template(VALID_DESIGN))
        mock_loader.return_value.load.return_value = [MagicMock(page_content="FETCHED-BRANDING")]

        self._tool()._run_impl(instructions="Use https://brand.example.com for branding")

        mock_loader.assert_called_once_with("https://brand.example.com")
        messages = mock_model.return_value.invoke.call_args[0][0]
        self.assertIn("FETCHED-BRANDING", messages[-1].content)

    @patch("products.workflows.backend.max_tools.is_url_allowed", return_value=(True, None))
    @patch("products.workflows.backend.max_tools.WebBaseLoader")
    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_url_fetch_failure_falls_back_to_instructions(self, mock_model, mock_loader, _mock_allowed):
        mock_model.return_value.invoke.return_value = MagicMock(content=_template(VALID_DESIGN))
        mock_loader.return_value.load.side_effect = Exception("network down")

        _content, template_json = self._tool()._run_impl(instructions="Use https://brand.example.com for branding")

        self.assertEqual(json.loads(template_json)["name"], "Welcome")
        self.assertEqual(mock_model.return_value.invoke.call_count, 1)

    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_retry_exhausted_raises(self, mock_model):
        mock_model.return_value.invoke.return_value = MagicMock(content=_template(INVALID_DESIGN))

        with self.assertRaises(PydanticOutputParserException):
            self._tool()._run_impl(instructions="A welcome email")

        self.assertEqual(mock_model.return_value.invoke.call_count, 3)

    @patch.object(CreateMessageTemplateTool, "_model", new_callable=PropertyMock)
    def test_malformed_structure_is_retried(self, mock_model):
        # design returned as a string fails pydantic — must be wrapped and retried, not raised raw.
        malformed = json.dumps(
            {
                "name": "Welcome",
                "description": "",
                "content": {
                    "templating": "liquid",
                    "email": {"subject": "Hi", "text": "Hi", "html": "<p>Hi</p>", "design": "not-a-dict"},
                },
            }
        )
        mock_model.return_value.invoke.side_effect = [
            MagicMock(content=malformed),
            MagicMock(content=_template(VALID_DESIGN)),
        ]

        _content, template_json = self._tool()._run_impl(instructions="A welcome email")

        self.assertEqual(json.loads(template_json)["content"]["email"]["design"], VALID_DESIGN)
        self.assertEqual(mock_model.return_value.invoke.call_count, 2)
