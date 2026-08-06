from copy import deepcopy

import pytest

from rest_framework import serializers

from products.messaging.backend.api.design_operations import apply_design_operations
from products.messaging.backend.api.design_validation import validate_design


def _sample_design() -> dict:
    return {
        "counters": {"u_row": 1, "u_column": 2, "u_content_text": 1},
        "schemaVersion": 16,
        "body": {
            "id": "body1",
            "rows": [
                {
                    "id": "row1",
                    "cells": [1, 1],
                    "columns": [
                        {
                            "id": "col1",
                            "contents": [
                                {
                                    "id": "txt1",
                                    "type": "text",
                                    "values": {
                                        "text": "<p>Hello</p>",
                                        "containerPadding": "10px",
                                        "_meta": {"htmlID": "u_content_text_1", "htmlClassNames": "u_content_text"},
                                    },
                                }
                            ],
                            "values": {"_meta": {"htmlID": "u_column_1"}, "padding": "0px"},
                        },
                        {"id": "col2", "contents": [], "values": {"_meta": {"htmlID": "u_column_2"}}},
                    ],
                    "values": {"backgroundColor": "#eee"},
                }
            ],
            "values": {"backgroundColor": "#ffffff", "contentWidth": "600px"},
        },
    }


def _content_by_id(design: dict, content_id: str) -> dict:
    for row in design["body"]["rows"]:
        for column in row["columns"]:
            for content in column["contents"]:
                if content["id"] == content_id:
                    return content
    raise AssertionError(f"content {content_id} not found")


class TestApplyDesignOperations:
    def test_update_content_merges_one_field(self):
        result = apply_design_operations(
            _sample_design(), [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>Bye</p>"}}}]
        )
        content = _content_by_id(result, "txt1")
        assert content["values"]["text"] == "<p>Bye</p>"
        # Untouched siblings survive the deep-merge.
        assert content["values"]["containerPadding"] == "10px"
        assert content["values"]["_meta"]["htmlID"] == "u_content_text_1"

    def test_update_content_null_leaf_deletes_key(self):
        result = apply_design_operations(
            _sample_design(),
            [{"op": "update_content", "id": "txt1", "patch": {"values": {"containerPadding": None}}}],
        )
        assert "containerPadding" not in _content_by_id(result, "txt1")["values"]

    @pytest.mark.parametrize(
        "operation",
        [
            {"op": "update_content", "id": "nope", "patch": {"values": {}}},
            {"op": "update_column", "id": "nope", "patch": {"values": {}}},
            {"op": "update_row", "id": "nope", "patch": {"values": {}}},
            {"op": "add_content", "column_id": "nope", "content": {"type": "text"}},
            {"op": "remove_content", "id": "nope"},
            {"op": "move_content", "id": "nope", "column_id": "col2"},
            {"op": "move_content", "id": "txt1", "column_id": "nope"},
            {"op": "remove_row", "id": "nope"},
        ],
        ids=lambda op: f"{op['op']}:{op.get('id') or op.get('column_id')}",
    )
    def test_operation_with_unknown_target_raises(self, operation):
        with pytest.raises(serializers.ValidationError):
            apply_design_operations(_sample_design(), [operation])

    def test_update_body_merges_into_values(self):
        result = apply_design_operations(
            _sample_design(), [{"op": "update_body", "patch": {"values": {"backgroundColor": "#000000"}}}]
        )
        assert result["body"]["values"]["backgroundColor"] == "#000000"
        assert result["body"]["values"]["contentWidth"] == "600px"

    def test_update_row_and_column(self):
        result = apply_design_operations(
            _sample_design(),
            [
                {"op": "update_row", "id": "row1", "patch": {"values": {"backgroundColor": "#111"}}},
                {"op": "update_column", "id": "col1", "patch": {"values": {"padding": "5px"}}},
            ],
        )
        assert result["body"]["rows"][0]["values"]["backgroundColor"] == "#111"
        assert result["body"]["rows"][0]["columns"][0]["values"]["padding"] == "5px"

    def test_add_content_appends_and_assigns_meta(self):
        result = apply_design_operations(
            _sample_design(),
            [{"op": "add_content", "column_id": "col1", "content": {"type": "text", "values": {"text": "<p>New</p>"}}}],
        )
        contents = result["body"]["rows"][0]["columns"][0]["contents"]
        assert len(contents) == 2
        added = contents[1]
        assert added["id"]  # server-assigned
        # counter bumped from 1 -> 2 and _meta numbered to match
        assert result["counters"]["u_content_text"] == 2
        assert added["values"]["_meta"]["htmlID"] == "u_content_text_2"
        assert added["values"]["_meta"]["htmlClassNames"] == "u_content_text"

    def test_add_content_respects_index(self):
        result = apply_design_operations(
            _sample_design(),
            [
                {
                    "op": "add_content",
                    "column_id": "col1",
                    "index": 0,
                    "content": {"type": "button", "values": {}},
                }
            ],
        )
        contents = result["body"]["rows"][0]["columns"][0]["contents"]
        assert contents[0]["type"] == "button"
        assert contents[1]["id"] == "txt1"
        assert result["counters"]["u_content_button"] == 1

    def test_remove_content(self):
        result = apply_design_operations(_sample_design(), [{"op": "remove_content", "id": "txt1"}])
        assert result["body"]["rows"][0]["columns"][0]["contents"] == []

    def test_move_content_between_columns(self):
        result = apply_design_operations(_sample_design(), [{"op": "move_content", "id": "txt1", "column_id": "col2"}])
        assert result["body"]["rows"][0]["columns"][0]["contents"] == []
        moved = result["body"]["rows"][0]["columns"][1]["contents"]
        assert len(moved) == 1 and moved[0]["id"] == "txt1"

    def test_add_row_numbers_nested_nodes(self):
        result = apply_design_operations(
            _sample_design(),
            [
                {
                    "op": "add_row",
                    "row": {
                        "cells": [1],
                        "columns": [{"contents": [{"type": "text", "values": {"text": "<p>R2</p>"}}], "values": {}}],
                        "values": {},
                    },
                }
            ],
        )
        rows = result["body"]["rows"]
        assert len(rows) == 2
        new_row = rows[1]
        assert new_row["id"] and new_row["values"]["_meta"]["htmlID"] == "u_row_2"
        new_col = new_row["columns"][0]
        assert new_col["id"] and new_col["values"]["_meta"]["htmlID"] == "u_column_3"
        new_content = new_col["contents"][0]
        assert new_content["id"] and new_content["values"]["_meta"]["htmlID"] == "u_content_text_2"

    def test_remove_row(self):
        result = apply_design_operations(_sample_design(), [{"op": "remove_row", "id": "row1"}])
        assert result["body"]["rows"] == []

    def test_does_not_mutate_input(self):
        original = _sample_design()
        snapshot = deepcopy(original)
        apply_design_operations(
            original, [{"op": "update_content", "id": "txt1", "patch": {"values": {"text": "<p>x</p>"}}}]
        )
        assert original == snapshot

    def test_operations_apply_in_order(self):
        # add then update the just-added block by the id we can't predict — instead update an existing
        # block, remove it, and confirm the later op sees the earlier op's result.
        with pytest.raises(serializers.ValidationError):
            apply_design_operations(
                _sample_design(),
                [
                    {"op": "remove_content", "id": "txt1"},
                    {"op": "update_content", "id": "txt1", "patch": {"values": {}}},
                ],
            )


class TestValidateDesign:
    def test_valid_design_returns_no_blocking_warnings(self):
        assert validate_design(_sample_design()) == []

    def test_duplicate_id_raises(self):
        design = _sample_design()
        design["body"]["rows"][0]["columns"][0]["id"] = "row1"  # collide with the row id
        with pytest.raises(serializers.ValidationError):
            validate_design(design)

    def test_missing_body_raises(self):
        with pytest.raises(serializers.ValidationError):
            validate_design({"counters": {}})

    def test_rows_not_a_list_raises(self):
        with pytest.raises(serializers.ValidationError):
            validate_design({"body": {"rows": "nope"}})

    def test_empty_rows_warns(self):
        design = _sample_design()
        design["body"]["rows"] = []
        assert any("no rows" in w for w in validate_design(design))

    def test_unknown_content_type_warns(self):
        design = _sample_design()
        design["body"]["rows"][0]["columns"][0]["contents"][0]["type"] = "hologram"
        assert any("unknown type" in w for w in validate_design(design))
