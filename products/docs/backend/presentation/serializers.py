"""DRF serializers for docs. Shapes only: they read facade DTOs and never touch models."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.enums import (
    AgentDelivery,
    CollabSubmitStatus,
    DataPointStatus,
    DiscussionKind,
    DocKind,
    DocStatus,
    DocTemplate,
    PostAuthorKind,
)

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
_TASK_ID_HELP = "The agent task this thread talks to. Set by the client that started the run."
_SEND_TO_AGENT_HELP = "True when the post tags the agent. With a live run the text is forwarded into it."
_LOOP_ID_HELP = "The loop that keeps checking a watched section. Each of its reports lands as a post."


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
    kind = serializers.ChoiceField(
        choices=[kind.value for kind in DocKind],
        help_text="page: a page the space writes. context: the one doc that is the space's context notes.",
    )
    position = serializers.IntegerField(help_text="Order of the doc in the space's tab row, lowest first.")
    version = serializers.IntegerField(
        help_text="Collab version of the stored body. Increases by one for every accepted step."
    )
    created_by = DocPersonSerializer(allow_null=True, help_text="The person who created the doc.")
    created_at = serializers.DateTimeField(help_text="When the doc was created.")
    updated_at = serializers.DateTimeField(help_text="When the doc was last written to.")
    excerpt = serializers.CharField(
        allow_blank=True, help_text="The first words of the page, for a list. Empty outside the space home."
    )
    open_thread_count = serializers.IntegerField(help_text="Threads on the page not yet marked handled.")
    watch_count = serializers.IntegerField(help_text="Sections of the page the agent keeps checking.")


class WatchSummarySerializer(serializers.Serializer):
    """A section under watch, as the space's context page lists it."""

    doc_id = serializers.UUIDField(help_text="The page the section is on.")
    doc_title = serializers.CharField(allow_blank=True, help_text="Title of that page.")
    anchor_key = serializers.CharField(allow_blank=True, help_text="Key of the watched section's thread.")
    anchor_text = serializers.CharField(allow_blank=True, help_text="The words under watch.")
    loop_id = serializers.CharField(allow_null=True, help_text=_LOOP_ID_HELP)
    last_report = serializers.CharField(allow_blank=True, help_text="The agent's newest report, or empty.")
    last_report_at = serializers.DateTimeField(allow_null=True, help_text="When that report landed.")
    created_at = serializers.DateTimeField(help_text="When the watch started.")


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
    """One message in a thread."""

    id = serializers.UUIDField(help_text="Unique id of the message.")
    content = serializers.CharField(allow_blank=True, help_text="What was written.")
    created_by = DocPersonSerializer(
        allow_null=True, help_text="The person who wrote it. Null for the agent and for system lines."
    )
    created_at = serializers.DateTimeField(help_text="When it was written.")
    author_kind = serializers.ChoiceField(
        choices=[kind.value for kind in PostAuthorKind],
        help_text="human: a person. agent: the agent's turn. system: a one-line note the page wrote.",
    )
    sent_to_agent = serializers.BooleanField(help_text="Whether this post reached the agent's run.")


class DataAnswerSerializer(serializers.Serializer):
    """The query behind a data point."""

    query = serializers.CharField(
        help_text="A HogQL SELECT that gives one row and one column. The page runs it on every read."
    )
    # The key is "label" on the wire; the class attribute of the same name is DRF's own.
    label = serializers.CharField(  # type: ignore[assignment]
        allow_blank=True, help_text="What the data point measures, in a few words."
    )
    note = serializers.CharField(allow_blank=True, help_text="A caveat for the reader, or empty.")
    run_id = serializers.CharField(allow_null=True, help_text="The run that submitted it.")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When it was last submitted.")


class DiscussionThreadSerializer(DiscussionPostSerializer):
    """A thread anchored to a phrase or a data point in the doc, with its posts."""

    anchor_key = serializers.CharField(
        allow_blank=True, help_text="Key that ties this thread to a mark or an inline request in the doc body."
    )
    anchor_text = serializers.CharField(
        allow_blank=True, help_text="The phrase or question the thread was started from."
    )
    resolved = serializers.BooleanField(help_text="Whether the thread is marked as handled.")
    kind = serializers.ChoiceField(
        choices=[kind.value for kind in DiscussionKind],
        help_text=(
            "text: started from a phrase. data: the thread behind a data point the page asked for. "
            "watch: a section the agent keeps checking on a schedule."
        ),
    )
    task_id = serializers.CharField(allow_null=True, help_text=_TASK_ID_HELP)
    loop_id = serializers.CharField(allow_null=True, help_text=_LOOP_ID_HELP)
    answer = DataAnswerSerializer(allow_null=True, help_text="The query a data thread ended with, or null.")
    replies = DiscussionPostSerializer(many=True, help_text="Posts after the first, oldest first.")


class DiscussionReplyResultSerializer(DiscussionThreadSerializer):
    """The thread after a post, and what happened to the post if it was for the agent."""

    delivery = serializers.ChoiceField(
        choices=[delivery.value for delivery in AgentDelivery],
        help_text=(
            "not_requested: a post between people. sent: the agent has it. "
            "no_run: the thread has no live run, so start one. failed: the run did not take it."
        ),
    )


class DiscussionCreateSerializer(serializers.Serializer):
    """What a new thread needs."""

    content = serializers.CharField(help_text="The first message.")
    anchor_key = serializers.CharField(
        max_length=64,
        help_text="Key the client also writes onto the mark around the selected phrase, or the request id.",
    )
    anchor_text = serializers.CharField(
        allow_blank=True, max_length=280, help_text="The selected phrase or the question, quoted in the panel."
    )
    kind = serializers.ChoiceField(
        choices=[kind.value for kind in DiscussionKind],
        default=DiscussionKind.TEXT.value,
        help_text="text for a phrase, data for a data point the page asked for, watch for a section the agent keeps checking.",
    )
    task_id = serializers.CharField(required=False, allow_null=True, max_length=64, help_text=_TASK_ID_HELP)
    loop_id = serializers.CharField(required=False, allow_null=True, max_length=64, help_text=_LOOP_ID_HELP)
    send_to_agent = serializers.BooleanField(default=False, help_text=_SEND_TO_AGENT_HELP)


class DiscussionReplySerializer(serializers.Serializer):
    """A post on an existing thread."""

    content = serializers.CharField(help_text="What to add to the thread.")
    task_id = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text="A task the client just started for this thread. The thread keeps it; the post is not forwarded.",
    )
    send_to_agent = serializers.BooleanField(default=False, help_text=_SEND_TO_AGENT_HELP)


class DiscussionResolveSerializer(serializers.Serializer):
    """Mark a thread handled, or bring it back."""

    resolved = serializers.BooleanField(help_text="True marks the thread handled, false reopens it.")


class DataPointSubmitSerializer(serializers.Serializer):
    """An agent handing in the query behind a data point a page asked for."""

    request_id = serializers.CharField(max_length=64, help_text="The request id named in the task.")
    status = serializers.ChoiceField(
        choices=[status.value for status in DataPointStatus],
        default=DataPointStatus.OK.value,
        help_text="ok: the query answers the question. none: this project's data cannot answer it.",
    )
    query = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="A HogQL SELECT that returns exactly one row and one column. Required unless status is none.",
    )
    label = serializers.CharField(  # type: ignore[assignment]
        required=False,
        allow_blank=True,
        default="",
        max_length=120,
        help_text="What the data point measures, in a few words. The reader sees this on it.",
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=400,
        help_text="One short line for the reader: a caveat, or with status none, why there is no answer.",
    )


class DataPointSubmitResultSerializer(serializers.Serializer):
    """Whether the page took the query."""

    ok = serializers.BooleanField(help_text="True when the page took the query, or took the none status.")
    value = serializers.CharField(
        allow_null=True, help_text="The single cell the query returned when it ran once, as text."
    )
    error = serializers.CharField(
        allow_null=True, help_text="Why the query was not taken. Fix the query and submit again."
    )


class SpaceHomeSerializer(serializers.Serializer):
    """Everything the space home view renders in one call."""

    docs = DocSummarySerializer(many=True, help_text="Docs in this space, in tab order.")
    watches = WatchSummarySerializer(
        many=True, help_text="Sections under watch across the space's pages, newest first."
    )
