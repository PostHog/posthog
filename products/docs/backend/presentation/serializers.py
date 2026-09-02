"""DRF serializers for docs. Shapes only: they read facade DTOs and never touch models."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.enums import (
    AgentDelivery,
    CollabSubmitStatus,
    DataPointStatus,
    DataShape,
    DiscussionKind,
    DocKind,
    DocStatus,
    DocTemplate,
    PostAuthorKind,
    WatchAction,
    WatchActor,
    WatchEvent,
    WatchStatus,
    WatchStopReason,
    WatchVerdict,
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
_WATCH_STATUS_HELP = "active: checks and the scout run. paused: the page is done. stopped: final."
_WATCH_VERDICT_HELP = (
    "pending: no brief yet. holding: the evidence stands. moved: a number left its baseline. "
    "confirmed or refuted: decided, and the watch ended. stale: the checks could not run."
)


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
    watch_count = serializers.IntegerField(help_text="Hypotheses on the page still under watch.")


class WatchSummarySerializer(serializers.Serializer):
    """A hypothesis under watch, as the space's home lists it."""

    thread_id = serializers.UUIDField(help_text="The watch's thread.")
    doc_id = serializers.UUIDField(help_text="The page the section is on.")
    doc_title = serializers.CharField(allow_blank=True, help_text="Title of that page.")
    anchor_key = serializers.CharField(allow_blank=True, help_text="Key of the watched section's thread.")
    anchor_text = serializers.CharField(allow_blank=True, help_text="The words under watch.")
    status = serializers.ChoiceField(choices=[entry.value for entry in WatchStatus], help_text=_WATCH_STATUS_HELP)
    verdict = serializers.ChoiceField(choices=[entry.value for entry in WatchVerdict], help_text=_WATCH_VERDICT_HELP)
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
    event = serializers.ChoiceField(
        choices=[event.value for event in WatchEvent],
        allow_null=True,
        required=False,
        help_text="On a post a watch wrote: what it stands for, so a timeline reads it without parsing words.",
    )


class DataAnswerSerializer(serializers.Serializer):
    """The query behind a data point."""

    query = serializers.CharField(help_text="A HogQL SELECT. The page runs it on every read.")
    # The key is "label" on the wire; the class attribute of the same name is DRF's own.
    label = serializers.CharField(  # type: ignore[assignment]
        allow_blank=True, help_text="What the data point measures, in a few words."
    )
    note = serializers.CharField(allow_blank=True, help_text="A caveat for the reader, or empty.")
    shape = serializers.ChoiceField(
        choices=[(shape.value, shape.value) for shape in DataShape],
        help_text="number: one cell, shown inline. series: dates and numbers, shown as a sparkline. table: anything else, shown as a chart block.",
    )
    run_id = serializers.CharField(allow_null=True, help_text="The run that submitted it.")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When it was last submitted.")


class WatchEvidenceSerializer(serializers.Serializer):
    """One number the claim stands on, and where it is against its baseline."""

    label = serializers.CharField(allow_blank=True, help_text="What the number counts.")  # type: ignore[assignment]
    query = serializers.CharField(help_text="The HogQL SELECT the page reruns.")
    shape = serializers.ChoiceField(
        choices=[(shape.value, shape.value) for shape in DataShape], help_text="number, or series for a trend."
    )
    baseline = serializers.FloatField(allow_null=True, help_text="The value when the brief landed.")
    value = serializers.FloatField(allow_null=True, help_text="The value at the last check.")
    checked_at = serializers.DateTimeField(allow_null=True, help_text="When it was last checked.")
    error = serializers.CharField(allow_null=True, help_text="Why the last check did not run, or null.")
    history = serializers.ListField(
        child=serializers.ListField(child=serializers.JSONField()),
        help_text="[time, value] pairs, oldest first, at most sixty.",
    )
    moved = serializers.BooleanField(help_text="True when the value left its baseline by a fifth or more.")


class WatchBriefSerializer(serializers.Serializer):
    """What the agent compiled the claim into."""

    claim = serializers.CharField(help_text="The claim in one sentence.")
    confirms = serializers.CharField(allow_blank=True, help_text="What would confirm it.")
    refutes = serializers.CharField(allow_blank=True, help_text="What would refute it.")
    evidence = WatchEvidenceSerializer(many=True, help_text="The numbers the page rechecks daily.")
    signals = serializers.ListField(
        child=serializers.CharField(), help_text="What the scout follows: events, flags, errors, replays."
    )
    submitted_at = serializers.DateTimeField(allow_null=True, help_text="When the brief landed.")


class WatchVerdictSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=[entry.value for entry in WatchVerdict], help_text=_WATCH_VERDICT_HELP)
    reason = serializers.CharField(allow_blank=True, help_text="Why, in one line.")
    by = serializers.ChoiceField(
        choices=[entry.value for entry in WatchActor], help_text="agent, person, or page for a derived verdict."
    )
    at = serializers.DateTimeField(allow_null=True, help_text="When the verdict was set.")


class WatchScoutSerializer(serializers.Serializer):
    config_id = serializers.CharField(help_text="The scout config that follows the signals.")
    skill_name = serializers.CharField(help_text="The scout's skill name.")


class DocWatchSerializer(serializers.Serializer):
    """The watch on a thread: whether it runs, what it stands on, and where the claim stands."""

    status = serializers.ChoiceField(choices=[entry.value for entry in WatchStatus], help_text=_WATCH_STATUS_HELP)
    stopped_reason = serializers.ChoiceField(
        choices=[entry.value for entry in WatchStopReason],
        allow_null=True,
        help_text="Why the watch stopped or paused, or null while it runs.",
    )
    verdict = WatchVerdictSerializer(help_text="Where the claim stands.")
    brief = WatchBriefSerializer(allow_null=True, help_text="The brief, or null until the agent hands it in.")
    scout = WatchScoutSerializer(allow_null=True, help_text="The scout, or null when none follows the signals.")
    scout_error = serializers.CharField(allow_null=True, help_text="Why the scout could not start, or null.")
    next_check_at = serializers.DateTimeField(allow_null=True, help_text="When the evidence is checked next.")
    checked_at = serializers.DateTimeField(allow_null=True, help_text="When the evidence was last checked.")
    evidence_only = serializers.BooleanField(help_text="True for a watch on a number already on the page.")


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
            "watch: a hypothesis the page keeps watching."
        ),
    )
    task_id = serializers.CharField(allow_null=True, help_text=_TASK_ID_HELP)
    watch = DocWatchSerializer(allow_null=True, help_text="The watch, on a watch thread.")
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


class WatchEvidenceInputSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        allow_blank=True, max_length=120, help_text="What the number counts."
    )
    query = serializers.CharField(help_text="One HogQL SELECT: one number, or a date and a number per row.")


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
        help_text="text for a phrase, data for a data point the page asked for, watch for a hypothesis to keep watching.",
    )
    task_id = serializers.CharField(required=False, allow_null=True, max_length=64, help_text=_TASK_ID_HELP)
    evidence = WatchEvidenceInputSerializer(
        many=True,
        required=False,
        default=list,
        help_text="For a watch on a number already on the page: its query. No agent and no scout are involved.",
    )
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
    shape = serializers.ChoiceField(
        choices=[(shape.value, shape.value) for shape in DataShape],
        allow_null=True,
        help_text="How the page shows it: number (one cell), series (a sparkline), or table (a chart block).",
    )
    value = serializers.CharField(
        allow_null=True, help_text="The cell the page shows: the number, or the last value of a series."
    )
    rows = serializers.IntegerField(help_text="How many rows the query returned when it ran once.")
    columns = serializers.IntegerField(help_text="How many columns the query returned when it ran once.")
    error = serializers.CharField(
        allow_null=True, help_text="Why the query was not taken. Fix the query and submit again."
    )


class WatchBriefSubmitSerializer(serializers.Serializer):
    """An agent handing in the brief behind a watch."""

    request_id = serializers.CharField(max_length=64, help_text="The request id named in the task.")
    claim = serializers.CharField(max_length=400, help_text="The claim in one sentence, as the page states it.")
    confirms = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=400, help_text="What would confirm it."
    )
    refutes = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=400, help_text="What would refute it."
    )
    evidence = WatchEvidenceInputSerializer(
        many=True, required=False, default=list, help_text="Up to four numbers the claim stands on."
    )
    signals = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        help_text="Up to six things the scout follows: events, flags, experiments, error issues, replay filters.",
    )


class WatchEvidenceResultSerializer(serializers.Serializer):
    label = serializers.CharField(allow_blank=True, help_text="The evidence label as submitted.")  # type: ignore[assignment]
    ok = serializers.BooleanField(help_text="True when the query ran and gave a number or a trend.")
    value = serializers.CharField(allow_null=True, help_text="The number, or the last value of the trend.")
    error = serializers.CharField(allow_null=True, help_text="Why it was not taken. Fix the query and submit again.")


class WatchBriefSubmitResultSerializer(serializers.Serializer):
    """Whether the page took the brief."""

    ok = serializers.BooleanField(help_text="True when every evidence query ran and the brief was kept.")
    evidence = WatchEvidenceResultSerializer(many=True, help_text="One result per evidence query, in order.")
    error = serializers.CharField(allow_null=True, help_text="Why the brief was not taken, or null.")


class WatchVerdictSubmitSerializer(serializers.Serializer):
    """An agent saying where the claim stands."""

    request_id = serializers.CharField(max_length=64, help_text="The request id named in the task.")
    verdict = serializers.ChoiceField(
        choices=[
            entry.value
            for entry in (WatchVerdict.HOLDING, WatchVerdict.MOVED, WatchVerdict.CONFIRMED, WatchVerdict.REFUTED)
        ],
        help_text="holding, moved, confirmed, or refuted. Confirmed and refuted end the watch.",
    )
    reason = serializers.CharField(max_length=600, help_text="Why, in one line the reader sees.")


class WatchActionSerializer(serializers.Serializer):
    """What a person does to a watch."""

    action = serializers.ChoiceField(
        choices=[entry.value for entry in WatchAction],
        help_text="check runs the evidence now. stop and resume toggle the watch. close sets a final verdict. arm starts the scout when it is missing.",
    )
    verdict = serializers.ChoiceField(
        choices=[WatchVerdict.CONFIRMED.value, WatchVerdict.REFUTED.value],
        required=False,
        allow_null=True,
        help_text="With close: confirmed or refuted.",
    )
    reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=600, help_text="With close: why."
    )


class SpaceHomeSerializer(serializers.Serializer):
    """Everything the space home view renders in one call."""

    docs = DocSummarySerializer(many=True, help_text="Docs in this space, in tab order.")
    watches = WatchSummarySerializer(
        many=True, help_text="Hypotheses under watch across the space's pages, the ones that moved first."
    )
