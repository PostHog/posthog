import re
import json
from pathlib import Path
from typing import Any

from products.messaging.backend.api.design_operations import apply_design_operations
from products.messaging.backend.api.design_validation import validate_design

REFERENCE = Path(__file__).resolve().parent.parent / "references" / "unlayer-design-json.md"
JSON_FENCE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
READABLE_PARAGRAPH_SPACING = ("8px 24px", "16px", "150%")


def _json_examples() -> list[dict[str, Any]]:
    return [json.loads(block) for block in JSON_FENCE.findall(REFERENCE.read_text(encoding="utf-8"))]


def _example_design() -> dict[str, Any]:
    (design,) = [example for example in _json_examples() if "body" in example]
    return design


def _example_operations() -> list[dict[str, Any]]:
    return [example for example in _json_examples() if "op" in example]


def _blocks(design: dict[str, Any], block_type: str) -> list[dict[str, Any]]:
    return [
        content
        for row in design["body"]["rows"]
        for column in row["columns"]
        for content in column["contents"]
        if content["type"] == block_type
    ]


def _spacing(block: dict[str, Any]) -> tuple[str, str, str]:
    values = block["values"]
    return values["containerPadding"], values["fontSize"], values["lineHeight"]


class TestUnlayerDesignReference:
    def test_example_design_validates_without_warnings(self) -> None:
        assert validate_design(_example_design()) == []

    def test_documented_operations_relink_the_button_and_keep_paragraphs_evenly_spaced(self) -> None:
        design = _example_design()
        operations = _example_operations()
        (button,) = _blocks(design, "button")
        (relink,) = [op for op in operations if op["op"] == "update_content" and op["id"] == button["id"]]
        new_link = relink["patch"]["values"]["href"]["values"]["href"]

        patched = apply_design_operations(design, operations)

        assert validate_design(patched) == []
        (patched_button,) = _blocks(patched, "button")
        assert patched_button["values"]["href"] == {
            "name": "web",
            "values": {"href": new_link, "target": button["values"]["href"]["values"]["target"]},
        }
        assert new_link != button["values"]["href"]["values"]["href"]
        paragraphs = _blocks(patched, "text")
        assert len(paragraphs) > len(_blocks(design, "text"))
        assert {_spacing(paragraph) for paragraph in paragraphs} == {READABLE_PARAGRAPH_SPACING}
        assert all(paragraph["values"]["text"].count("<p") == 1 for paragraph in paragraphs)
