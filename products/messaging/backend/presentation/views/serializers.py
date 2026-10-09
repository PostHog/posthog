from typing import Any

from django.db import models

from rest_framework import serializers


class EmailTemplateDesignOperation(models.TextChoices):
    UPDATE_CONTENT = "update_content", "update_content"
    UPDATE_COLUMN = "update_column", "update_column"
    UPDATE_ROW = "update_row", "update_row"
    UPDATE_BODY = "update_body", "update_body"
    ADD_CONTENT = "add_content", "add_content"
    REMOVE_CONTENT = "remove_content", "remove_content"
    MOVE_CONTENT = "move_content", "move_content"
    ADD_ROW = "add_row", "add_row"
    REMOVE_ROW = "remove_row", "remove_row"


DESIGN_OPERATION_TYPES = list(EmailTemplateDesignOperation.values)

# Per-op required fields, validated in DesignOperationSerializer.validate so a malformed op is rejected
# before any are applied (the whole batch is atomic).
_DESIGN_OPERATION_REQUIRED_FIELDS: dict[str, list[str]] = {
    "update_content": ["id", "patch"],
    "update_column": ["id", "patch"],
    "update_row": ["id", "patch"],
    "update_body": ["patch"],
    "add_content": ["column_id", "content"],
    "remove_content": ["id"],
    "move_content": ["id", "column_id"],
    "add_row": ["row"],
    "remove_row": ["id"],
}


class DesignOperationSerializer(serializers.Serializer):
    op = serializers.ChoiceField(
        choices=DESIGN_OPERATION_TYPES,
        help_text=(
            "Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null "
            "leaf deletes that key) — the surgical path, e.g. change just values.text. update_row / update_column "
            "{id, patch} and update_body {patch}: same deep-merge for row/column/body-level settings. add_content "
            "{column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are "
            "filled in for you). remove_content {id} / move_content {id, column_id, index?}: delete or relocate a "
            "block. add_row {row, index?} / remove_row {id}: add or delete a row."
        ),
    )
    id = serializers.CharField(
        required=False,
        help_text="Target node id. Required for update_content/column/row, remove_content, remove_row, move_content.",
    )
    column_id = serializers.CharField(
        required=False, help_text="Target column id. Required for add_content and move_content."
    )
    patch = serializers.JSONField(
        required=False,
        help_text=(
            "update_* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. "
            "e.g. {values: {text: '<p>Hi</p>'}} changes only the block's text."
        ),
    )
    content = serializers.JSONField(
        required=False,
        help_text=(
            "add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned "
            "server-side. type is one of text, heading, button, image, divider, html, etc."
        ),
    )
    row = serializers.JSONField(
        required=False,
        help_text=(
            "add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer "
            "numbering are assigned server-side for the row and everything nested in it."
        ),
    )
    index = serializers.IntegerField(
        required=False,
        help_text="add_*/move_content only. 0-based insert position; omit to append to the end.",
    )

    def validate(self, data: Any) -> Any:
        op = data["op"]
        missing = [field for field in _DESIGN_OPERATION_REQUIRED_FIELDS[op] if data.get(field) is None]
        if missing:
            raise serializers.ValidationError(f"op '{op}' requires: {', '.join(missing)}")
        if op in ("update_content", "update_column", "update_row", "update_body") and not isinstance(
            data.get("patch"), dict
        ):
            raise serializers.ValidationError(f"{op} 'patch' must be an object")
        if op == "add_content" and not isinstance(data.get("content"), dict):
            raise serializers.ValidationError("add_content 'content' must be an object")
        if op == "add_row" and not isinstance(data.get("row"), dict):
            raise serializers.ValidationError("add_row 'row' must be an object")
        return data
