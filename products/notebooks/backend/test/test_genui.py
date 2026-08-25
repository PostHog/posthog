from types import SimpleNamespace
from typing import Any, cast
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
    GenUIStatus,
    _generation_cancellation_key,
    infer_genui_inputs,
    inspect_genui_inputs,
    normalize_inputs,
    read_genui_frame,
)
from products.notebooks.backend.genui_generation import (
    GENUI_MODEL_MAX_TOKENS,
    GENUI_MODEL_TEMPERATURE,
    GENUI_MODEL_TIMEOUT_SECONDS,
    GenUISourceGenerationCancelled,
    GenUISourceGenerationError,
    _generation_prompt,
    generate_genui_source,
)
from products.notebooks.backend.genui_models import DEFAULT_GENUI_MODEL
from products.notebooks.backend.models import Notebook, NotebookGenUI, NotebookNodeRun
from products.notebooks.backend.presentation.genui_serializers import GenUIGenerateRequestSerializer

from ee.models.rbac.access_control import AccessControl


def markdown_content(markdown: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "ph-markdown-notebook", "attrs": {"nodeId": "markdown-notebook-v2", "markdown": markdown}}
        ],
    }


def completion_stream(content: str, finish_reason: str | None = None) -> MagicMock:
    stream = MagicMock()
    stream.__iter__.return_value = iter(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)]
            )
        ]
    )
    return stream


class TestGenUIGeneration(SimpleTestCase):
    @parameterized.expand(
        [
            ("normalizes", [" locations_df ", "users_df"], ["locations_df", "users_df"], None),
            ("duplicate", ["events_df", "events_df"], None, "duplicate_input_name"),
            ("invalid", ["events-df"], None, "invalid_input_name"),
            ("many", ["a", "b", "c", "d", "e"], ["a", "b", "c", "d", "e"], None),
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
        assert "Do not read every frame by default" in prompt
        assert "focused implementation with enough detail for a polished result" in prompt
        assert "without unnecessary repetition" in prompt
        assert "under 350 lines" in prompt
        assert "Do not reduce a complex subject to one generic primitive" in prompt
        assert "compose complex forms from appropriate geometry" in prompt
        assert "Self-contained means no downloaded assets, not flat or textureless materials" in prompt
        assert "THREE.CanvasTexture" in prompt
        assert "give every planet a distinct procedural surface" in prompt
        assert "choose encodings that fit the data" in prompt
        assert "Fill 100% of the available width and height" in prompt
        assert "ResizeObserver" in prompt
        assert "Always provide controls for interacting with the visualization" in prompt
        assert "camera orbit, pan, and zoom" in prompt
        assert "controls for exploring or manipulating the data" in prompt
        assert "without rebuilding the entire scene" in prompt

    def test_invalid_source_gets_one_repair_attempt(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        invalid_stream = completion_stream(
            '{"source":"import chart from \\"unsupported-chart\\"; export default function Canvas() { return <div /> }"}'
        )
        valid_stream = completion_stream('{"source":"export default function Canvas() { return <div>Ready</div> }"}')
        client.chat.completions.create.side_effect = [
            invalid_stream,
            valid_stream,
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
        client.with_options.assert_called_with(timeout=GENUI_MODEL_TIMEOUT_SECONDS[DEFAULT_GENUI_MODEL], max_retries=0)
        assert client.chat.completions.create.call_count == 2
        first_request = client.chat.completions.create.call_args_list[0].kwargs
        assert first_request["model"] == DEFAULT_GENUI_MODEL
        assert first_request["max_tokens"] == GENUI_MODEL_MAX_TOKENS[DEFAULT_GENUI_MODEL]
        assert first_request["temperature"] == GENUI_MODEL_TEMPERATURE[DEFAULT_GENUI_MODEL]
        assert first_request["extra_body"] == {"thinking": {"type": "disabled"}}
        assert first_request["stream"] is True
        invalid_stream.close.assert_called_once()
        valid_stream.close.assert_called_once()
        repair_prompt = client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
        assert "import_not_allowed" in repair_prompt

    def test_generation_closes_the_model_stream_when_canceled(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        stream = completion_stream('{"source":"export default function Canvas() { return <div /> }"}')
        client.chat.completions.create.return_value = stream
        is_cancelled = MagicMock(side_effect=[False, True])

        with self.assertRaises(GenUISourceGenerationCancelled):
            generate_genui_source(
                team_id=42,
                trace_id="trace-42",
                prompt="Render a globe",
                schemas=[],
                input_names=[],
                client=client,
                is_cancelled=is_cancelled,
            )

        stream.close.assert_called_once()

    def test_length_limited_generation_retries_without_partial_source(self) -> None:
        client = MagicMock()
        client.with_options.return_value = client
        truncated_stream = completion_stream("partial-source-marker", finish_reason="length")
        valid_stream = completion_stream('{"source":"export default function Canvas() { return <div>Ready</div> }"}')
        client.chat.completions.create.side_effect = [truncated_stream, valid_stream]

        source = generate_genui_source(
            team_id=42,
            trace_id="trace-42",
            prompt="Build an interactive activity overview",
            schemas=[],
            input_names=[],
            client=client,
        )

        assert source == "export default function Canvas() { return <div>Ready</div> }"
        retry_prompt = client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
        assert "previous response reached the output limit" in retry_prompt
        assert "partial-source-marker" not in retry_prompt
        truncated_stream.close.assert_called_once()
        valid_stream.close.assert_called_once()

    def test_generation_rejects_an_unlisted_model(self) -> None:
        with self.assertRaises(GenUISourceGenerationError):
            generate_genui_source(
                team_id=42,
                trace_id="trace-42",
                prompt="Render a globe",
                schemas=[],
                input_names=[],
                model="not-a-model",
                client=MagicMock(),
            )

    def test_generate_request_defaults_to_the_balanced_model(self) -> None:
        serializer = GenUIGenerateRequestSerializer(data={"prompt": "Render a globe", "generation_id": str(uuid4())})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["model"] == DEFAULT_GENUI_MODEL

    def test_generate_request_rejects_an_unlisted_model(self) -> None:
        serializer = GenUIGenerateRequestSerializer(
            data={"prompt": "Render a globe", "generation_id": str(uuid4()), "model": "not-a-model"}
        )

        assert not serializer.is_valid()
        assert "model" in serializer.errors

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

    def test_infers_dataframe_context_from_the_notebook(self) -> None:
        notebook = cast(
            Notebook,
            SimpleNamespace(
                content=markdown_content(
                    '<PythonV2 nodeId="source" returnVariable="locations_df" />\n\n'
                    '<SQLV2 nodeId="summary" returnVariable="summary_df" />\n\n'
                    '<GenUI nodeId="globe" prompt="Render a globe" />\n\n'
                    '<PythonV2 nodeId="later" returnVariable="future_df" />'
                )
            ),
        )

        assert infer_genui_inputs(notebook, "globe") == ["locations_df", "summary_df", "future_df"]


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

    def test_generate_endpoint_infers_available_dataframes(self) -> None:
        latest = self._run()
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/genui/{self.NODE_ID}/generate/"
        result = GenUIStatus(
            lifecycle_status="building",
            error_detail=None,
            artifact_url=None,
            frame_names=[self.INPUT_NAME],
        )

        with patch(
            "products.notebooks.backend.presentation.views.notebook.generate_genui", return_value=result
        ) as generate:
            response = self.client.post(
                url,
                data={"prompt": "Render a globe", "generation_id": str(uuid4())},
                format="json",
            )

        assert response.status_code == 200
        assert generate.call_args.kwargs["inputs"] == [self.INPUT_NAME]
        assert generate.call_args.kwargs["inspection"].resolved_inputs[0].run == latest

    def test_cancel_endpoint_records_the_request(self) -> None:
        generation_id = uuid4()
        url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/genui/{self.NODE_ID}/cancel/"

        response = self.client.post(url, data={"generation_id": str(generation_id)}, format="json")

        assert response.status_code == 204
        key = _generation_cancellation_key(
            team_id=self.team.id,
            user_id=self.user.id,
            notebook_id=self.notebook.id,
            node_id=self.NODE_ID,
            generation_id=generation_id,
        )
        assert cache.get(key) is True

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
                data={"prompt": "Render a globe", "generation_id": str(uuid4())},
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
