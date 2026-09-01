"""DRF serializers for docs. Shapes only: they read facade DTOs and never touch models."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.enums import CollabSubmitStatus, DocStatus, DocTemplate

_PROSEMIRROR_SCHEMA = {
    "type": "object",
    "description": "A ProseMirror document node tree. The root node has type 'doc' and a 'content' array.",
    "additionalProperties": True,
}

_DOC_STATUS_HELP = (
    "Where the doc is in its life: draft while it is being written, active once the space "
    "works from it, done when it is finished."
)
_DOC_STATUS_CHOICES = [status.value for status in DocStatus]


@extend_schema_field(_PROSEMIRROR_SCHEMA)
class ProseMirrorField(serializers.JSONField):
    """The doc body. Blocks hold references (task id, object kind and id), never live values."""


class DocPersonSerializer(serializers.Serializer):
    """Who did something, as much of a person as a doc surface needs."""

    id = serializers.IntegerField(help_text="Numeric id of the person.")
    uuid = serializers.UUIDField(help_text="Stable id of the person.")
    first_name = serializers.CharField(allow_blank=True, help_text="First name.")
    last_name = serializers.CharField(allow_blank=True, help_text="Last name.")
    email = serializers.EmailField(help_text="Email address.")


class DocSummarySerializer(serializers.Serializer):
    """A doc without its body. Used for the tab row and the space home list."""

    id = serializers.UUIDField(help_text="Unique id of the doc.")
    channel_id = serializers.UUIDField(help_text="The space (channel) the doc belongs to.")
    title = serializers.CharField(allow_blank=True, help_text="Title of the doc, shown on its tab.")
    status = serializers.ChoiceField(choices=_DOC_STATUS_CHOICES, help_text=_DOC_STATUS_HELP)
    position = serializers.IntegerField(help_text="Order of the doc in the space's tab row, lowest first.")
    version = serializers.IntegerField(
        help_text="Collab version of the stored body. Increases by one for every accepted step."
    )
    created_by = DocPersonSerializer(allow_null=True, help_text="The person who created the doc.")
    created_at = serializers.DateTimeField(help_text="When the doc was created.")
    updated_at = serializers.DateTimeField(help_text="When the doc was last written to.")


class DocSerializer(DocSummarySerializer):
    """A doc with its body."""

    content = ProseMirrorField(allow_null=True, help_text="The doc body as a ProseMirror document.")
    text_content = serializers.CharField(
        allow_blank=True, help_text="Plain-text mirror of the body, written on every save."
    )


class DocCreateSerializer(serializers.Serializer):
    """What a new doc needs."""

    channel = serializers.UUIDField(help_text="The space (channel) the doc belongs to.")
    title = serializers.CharField(
        required=False, allow_blank=True, max_length=400, help_text="Title of the doc. Defaults to the template name."
    )
    template = serializers.ChoiceField(
        choices=[template.value for template in DocTemplate],
        default=DocTemplate.BLANK.value,
        help_text="Starting content: 'blank' is an empty page, 'notes' has headings for notes from a call.",
    )


class DocUpdateSerializer(serializers.Serializer):
    """The parts of a doc a person can change outside the editor."""

    title = serializers.CharField(required=False, allow_blank=True, max_length=400, help_text="New title for the doc.")
    status = serializers.ChoiceField(required=False, choices=_DOC_STATUS_CHOICES, help_text=_DOC_STATUS_HELP)


class DocReorderSerializer(serializers.Serializer):
    """The new left-to-right order of a space's tabs."""

    channel = serializers.UUIDField(help_text="The space (channel) whose docs are being reordered.")
    doc_ids = serializers.ListField(
        child=serializers.UUIDField(help_text="Id of a doc in this space."),
        help_text="Doc ids in their new order. Ids that are not in this space are ignored.",
    )


class DocCollabSaveSerializer(serializers.Serializer):
    """One batch of prosemirror-collab steps, with the document they produce."""

    client_id = serializers.CharField(max_length=64, help_text="Id of the editing client, unique per open tab.")
    steps = serializers.ListField(
        child=serializers.JSONField(help_text="One prosemirror-collab step, serialized."),
        help_text="The steps to append, in order.",
    )
    version = serializers.IntegerField(help_text="The collab version the submitted steps are based on.")
    content = ProseMirrorField(help_text="The whole document after the steps are applied.")
    text_content = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Plain-text mirror of the body."
    )
    title = serializers.CharField(
        required=False, allow_blank=True, max_length=400, help_text="Title to store with this save."
    )
    cursor_head = serializers.IntegerField(
        required=False, allow_null=True, help_text="The caller's caret position, broadcast with the steps."
    )


class DocCollabConflictSerializer(serializers.Serializer):
    """The save was rejected because other steps landed first."""

    code = serializers.ChoiceField(
        choices=[CollabSubmitStatus.CONFLICT.value, CollabSubmitStatus.STALE.value],
        help_text="'conflict' means the missed steps are included. 'stale' means the client must reload the doc.",
    )
    steps = serializers.ListField(
        required=False,
        child=serializers.JSONField(help_text="One prosemirror-collab step the client has not seen."),
        help_text="The steps the client missed, in order.",
    )
    client_ids = serializers.ListField(
        required=False,
        child=serializers.CharField(help_text="Client that authored the step at the same index."),
        help_text="Authors of the missed steps, index-aligned with 'steps'.",
    )
    version = serializers.IntegerField(help_text="The current collab version of the doc.")


class DocPresenceSerializer(serializers.Serializer):
    """A caret ping, broadcast to everyone else in the doc."""

    client_id = serializers.CharField(max_length=64, help_text="Id of the editing client, unique per open tab.")
    version = serializers.IntegerField(help_text="The collab version the caret position is relative to.")
    cursor = serializers.JSONField(help_text="Caret position as {'anchor': int, 'head': int}.")


class DiscussionPostSerializer(serializers.Serializer):
    """One message in a discussion."""

    id = serializers.UUIDField(help_text="Unique id of the message.")
    content = serializers.CharField(allow_blank=True, help_text="What the person wrote.")
    created_by = DocPersonSerializer(allow_null=True, help_text="The person who wrote it.")
    created_at = serializers.DateTimeField(help_text="When it was written.")


class DiscussionThreadSerializer(DiscussionPostSerializer):
    """A discussion anchored to a phrase in the doc, with its replies."""

    anchor_key = serializers.CharField(
        allow_blank=True, help_text="Key that ties this thread to a mark in the doc body."
    )
    anchor_text = serializers.CharField(allow_blank=True, help_text="The phrase the thread was started from.")
    resolved = serializers.BooleanField(help_text="Whether the thread is marked as handled.")
    replies = DiscussionPostSerializer(many=True, help_text="Replies, oldest first.")


class DiscussionCreateSerializer(serializers.Serializer):
    """What a new discussion needs."""

    content = serializers.CharField(help_text="The first message.")
    anchor_key = serializers.CharField(
        max_length=64, help_text="Key the client also writes onto the mark around the selected phrase."
    )
    anchor_text = serializers.CharField(
        allow_blank=True, max_length=280, help_text="The selected phrase, quoted in the panel."
    )


class DiscussionReplySerializer(serializers.Serializer):
    """A reply to an existing discussion."""

    content = serializers.CharField(help_text="What to add to the thread.")


class DiscussionResolveSerializer(serializers.Serializer):
    """Mark a discussion handled, or bring it back."""

    resolved = serializers.BooleanField(help_text="True marks the thread handled, false reopens it.")


class SpaceHomeSerializer(serializers.Serializer):
    """Everything the space home view renders in one call."""

    docs = DocSummarySerializer(many=True, help_text="Docs in this space, in tab order.")
