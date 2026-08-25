from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.canvas.backend.notebook_integration import validate_notebook_canvas_source
from products.notebooks.backend.genui import (
    MAX_FRAME_BYTES,
    GenUIError,
    inspect_genui_inputs,
    normalize_inputs,
    read_genui_frame,
)
from products.notebooks.backend.genui_generation import GENUI_MODEL, _generation_prompt, generate_genui_source
from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookNodeRun

from ee.models.rbac.access_control import AccessControl


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


class TestGenUIGeneration(SimpleTestCase):
    @parameterized.expand(
        [
            ("normalizes", [" locations_df ", "users_df"], ["locations_df", "users_df"], None),
            ("duplicate", ["events_df", "events_df"], None, "duplicate_input_name"),
            ("invalid", ["events-df"], None, "invalid_input_name"),
            ("too_many", ["a", "b", "c", "d", "e"], None, "too_many_inputs"),
        ]
    )
    def test_normalize_inputs(
        self, _name: str, raw: list[str], expected: list[str] | None, error_code: str | None
    ) -> None:
        if error_code is None:
            assert normalize_inputs(raw) == expected
            return
        with self.assertRaises(GenUIError) as error:
            normalize_inputs(raw)
        assert error.exception.code == error_code

    def test_prompt_contains_schema_but_not_rows(self) -> None:
        prompt = _generation_prompt(
            prompt="Render a globe",
            schemas=[{"name": "locations_df", "columns": [{"name": "lat", "type": "float64"}]}],
            input_names=["locations_df"],
        )

        assert "locations_df" in prompt
        assert '"lat"' in prompt
        assert "51.5" not in prompt
        assert "await ph.readFrame" in prompt

    def test_invalid_source_gets_one_repair_attempt(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"source":"import chart from \\"unsupported-chart\\"; export default function Canvas() { return <div /> }"}'
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"source":"export default function Canvas() { return <div>Ready</div> }"}'
                        )
                    )
                ]
            ),
        ]

        source = generate_genui_source(
            team_id=42,
            trace_id="trace-42",
            prompt="Render a globe",
            schemas=[{"name": "locations_df", "columns": [{"name": "lat", "type": "float64"}]}],
            input_names=["locations_df"],
            client=client,
        )

        assert source == "export default function Canvas() { return <div>Ready</div> }"
        assert client.chat.completions.create.call_count == 2
        assert client.chat.completions.create.call_args_list[0].kwargs["model"] == GENUI_MODEL
        repair_prompt = client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
        assert "import_not_allowed" in repair_prompt

    def test_canvas_validation_rejects_network_and_unlisted_frames(self) -> None:
        diagnostics = validate_notebook_canvas_source(
            'export default function Canvas() { fetch("https://example.com"); ph.readFrame("private_df"); return null }',
            ["public_df"],
        )

        error_codes = {item.get("code") for item in diagnostics if item.get("severity") == "error"}
        assert "network_fetch" in error_codes
        assert "notebook_frame_not_allowed" in error_codes

    def test_canvas_validation_accepts_an_allowed_frame(self) -> None:
        diagnostics = validate_notebook_canvas_source(
            'export default async function Canvas() { await ph.readFrame("public_df"); return null }',
            ["public_df"],
        )

        assert not [item for item in diagnostics if item.get("severity") == "error"]


class TestGenUIData(APIBaseTest):
    NODE_ID = "globe"
    INPUT_NAME = "locations_df"

    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=markdown_content(
                f'<PythonV2 nodeId="source" code="locations_df = points.copy()" '
                f'returnVariable="{self.INPUT_NAME}" />\n\n'
                f'<GenUI nodeId="{self.NODE_ID}" prompt="Render a globe" inputs="{self.INPUT_NAME}" />'
            ),
        )

    def _run(self, *, value: object = 51.5, connection_id: str | None = None) -> NotebookNodeRun:
        return NotebookNodeRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=self.notebook,
            user=self.user,
            node_id="source",
            node_type=NotebookNodeRun.NodeType.PYTHON,
            code="locations_df = points.copy()",
            connection_id=connection_id,
            status=NotebookNodeRun.Status.DONE,
            envelope={
                "types": [["lat", "float64"], ["label", "string"]],
                "first_page": [[value, "x" * 5_000] for _index in range(100)],
                "row_count": 150,
            },
        )

    def _mapping(self) -> NotebookGenUI:
        return NotebookGenUI.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            notebook=self.notebook,
            node_id=self.NODE_ID,
            prompt="Render a globe",
            inputs=[self.INPUT_NAME],
            generator_version="3",
            generation_hash="",
            canvas_id=uuid4(),
        )

    def test_inspection_uses_latest_successful_run_and_authorizes_it(self) -> None:
        self._run(value=1)
        latest = self._run(value=2)
        authorize = MagicMock()

        inspection = inspect_genui_inputs(self.notebook, [self.INPUT_NAME], authorize)

        assert inspection.resolved_inputs[0].run == latest
        assert inspection.schemas[0]["columns"] == [
            {"name": "lat", "type": "float64"},
            {"name": "label", "type": "string"},
        ]
        authorize.assert_called_once_with(latest)

    def test_frame_is_whitelisted_and_bounded(self) -> None:
        self._run()
        self._mapping()

        result = read_genui_frame(
            notebook=self.notebook,
            node_id=self.NODE_ID,
            frame_name=self.INPUT_NAME,
            authorize_run=lambda _run: None,
        )

        assert result.frame["includedRowCount"] == 100
        assert result.frame["truncated"] is True
        assert len(str(result.frame).encode()) < MAX_FRAME_BYTES
        with self.assertRaises(GenUIError) as error:
            read_genui_frame(
                notebook=self.notebook,
                node_id=self.NODE_ID,
                frame_name="private_df",
                authorize_run=lambda _run: None,
            )
        assert error.exception.code == "frame_not_allowed"

    def test_removed_node_cannot_read_its_old_mapping(self) -> None:
        self._run()
        self._mapping()
        self.notebook.content = markdown_content('<PythonV2 nodeId="source" returnVariable="locations_df" />')
        self.notebook.save(update_fields=["content"])

        with self.assertRaises(GenUIError) as error:
            read_genui_frame(
                notebook=self.notebook,
                node_id=self.NODE_ID,
                frame_name=self.INPUT_NAME,
                authorize_run=lambda _run: None,
            )
        assert error.exception.code == "node_not_found"

    def test_status_endpoint_does_not_generate(self) -> None:
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/genui/{self.NODE_ID}/status/"
        with patch("products.notebooks.backend.genui_generation.generate_genui_source") as generate:
            response = self.client.get(url)

        assert response.status_code == 200
        assert response.json()["lifecycle_status"] == "awaiting_generation"
        generate.assert_not_called()

    def test_query_restricted_member_cannot_generate(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save(update_fields=["level"])
        AccessControl.objects.create(
            team=self.team,
            resource="query",
            resource_id=None,
            organization_member=self.organization_membership,
            access_level="none",
        )
        cache.clear()
        self._run()
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/genui/{self.NODE_ID}/generate/"

        with patch("products.notebooks.backend.genui_generation.generate_genui_source") as generate:
            response = self.client.post(
                url,
                data={"prompt": "Render a globe", "inputs": [self.INPUT_NAME]},
                format="json",
            )

        assert response.status_code == 403
        generate.assert_not_called()

    def test_frame_rechecks_connection_access(self) -> None:
        self._run(connection_id=str(uuid4()))
        self._mapping()
        url = (
            f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/genui/{self.NODE_ID}/frames/"
            f"{self.INPUT_NAME}/"
        )

        with patch(
            "products.notebooks.backend.presentation.views.notebook.get_direct_connection_source", return_value=None
        ):
            response = self.client.get(url)

        assert response.status_code == 403
