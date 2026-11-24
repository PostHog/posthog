from rest_framework import serializers


class NotebookRunCellSerializer(serializers.Serializer):
    node_id = serializers.CharField(help_text="Durable cell identity, the same id the cell run endpoints take.")
    cell_type = serializers.CharField(help_text="Cell kind: 'sql' or 'python'.")
    dataframe_name = serializers.CharField(
        allow_blank=True, help_text="Name other cells reference this cell's result by; blank means display-only."
    )
    run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="This cell's run in the whole-notebook run; null until the run reaches the cell.",
    )
    # CharField, not ChoiceField: a `status` enum collides with other generated enums.
    status = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="The cell's own state: 'running', 'done', 'failed', or 'interrupted'; null before it starts.",
    )
    error = serializers.CharField(required=False, allow_null=True, help_text="Why this cell failed, when it did.")
