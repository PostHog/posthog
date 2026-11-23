"""DRF serializers for stacks. They describe the wire shapes and convert JSON to and from facade contracts."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.enums import LabeledStrEnum

from ..facade.enums import BindingStatus, ChangeAction, DiffStatus, PushStatus, StackErrorCode

# Each kind's own naming rule decides a key, so the serializer bounds only the length of the longest one.
KEY_MAX_LENGTH = 512


@extend_schema_field({"type": "object", "additionalProperties": True})
class JsonObjectField(serializers.JSONField):
    """A JSON object whose shape depends on the definition kind."""

    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        return super().to_internal_value(data)


@extend_schema_field({})
class JsonValueField(serializers.JSONField):
    """Any JSON value: a string, number, boolean, object, array or null."""


class DefinitionSourceSerializer(serializers.Serializer):
    file = serializers.CharField(max_length=1000, help_text="Path of the definition's file, relative to the repo root.")
    export = serializers.CharField(
        max_length=200, required=False, help_text="Name of the export in that file that holds the definition."
    )


class DefinitionIdentitySerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, help_text="The definition kind, such as `model` or `flag`.")
    key = serializers.CharField(max_length=KEY_MAX_LENGTH, help_text="The definition's key in the same stack.")


class ResourceDescriptionSerializer(serializers.Serializer):
    kind = serializers.CharField(
        max_length=64, help_text="The definition kind, such as `insight`, `dashboard`, `flag` or `event`."
    )
    key = serializers.CharField(
        max_length=KEY_MAX_LENGTH,
        help_text="The identity the author chose, unique within the kind. For a kind with a natural key, such as a "
        "flag key or an event name, it is that natural key.",
    )
    body = JsonObjectField(
        help_text="The definition, shaped like the API's create body for the kind. A reference to another "
        'definition in the stack is `{"$ref": {"kind", "key", "attr"}}`, and a secret is `{"$secret": "NAME"}`.'
    )
    source = DefinitionSourceSerializer(  # type: ignore[assignment]  # The wire field shadows a Serializer attribute.
        required=False, help_text="Where the definition lives in the repository, for messages and provenance."
    )
    depends_on = DefinitionIdentitySerializer(
        many=True,
        required=False,
        help_text="Definitions in the same stack that must exist before this one is created, because the body names "
        "them by a string rather than a reference, such as a model that another model's SQL reads.",
    )


class StackDescriptionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1, max_value=1, help_text="The description format version. Always 1.")
    resources = ResourceDescriptionSerializer(
        many=True, help_text="Every definition the stack manages, sorted by kind and then key."
    )


class DiffSourceSerializer(serializers.Serializer):
    repository = serializers.CharField(
        max_length=500, allow_blank=True, help_text="The repository the description was built from, such as `org/repo`."
    )
    branch = serializers.CharField(
        max_length=500, allow_blank=True, help_text="The branch the description was built from."
    )
    commit = serializers.CharField(
        max_length=100, allow_blank=True, help_text="The commit the description was built from."
    )


class CreateDiffRequestSerializer(serializers.Serializer):
    description = StackDescriptionSerializer(help_text="The stack description that `hog check` writes.")
    source = DiffSourceSerializer(help_text="The repository, branch and commit the description came from.")  # type: ignore[assignment]


class PushRequestSerializer(serializers.Serializer):
    max_removals = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text="The most entities this push may remove or recreate. Defaults to the stack's own cap. "
        "Set it to confirm a push that removes more.",
    )


class StackFieldChangeSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="The field that changes, as a dotted path into the definition body.")
    before = JsonValueField(allow_null=True, help_text="The value now in PostHog. Null when the field is sensitive.")
    after = JsonValueField(allow_null=True, help_text="The value a push sets. Null when the field is sensitive.")
    sensitive = serializers.BooleanField(help_text="True when the value is secret, so neither value is shown.")


class DefinitionSourceRefSerializer(serializers.Serializer):
    file = serializers.CharField(help_text="Path of the definition's file, relative to the repo root.")
    export = serializers.CharField(required=False, help_text="Name of the export in that file.")


class StackChangeSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ChangeAction.choices, help_text="What a push does to this definition.")
    kind = serializers.CharField(help_text="The definition kind.")
    key = serializers.CharField(help_text="The definition key.")
    name = serializers.CharField(help_text="The entity's display name.")
    summary = serializers.CharField(help_text="One line on what changes, such as `query changed`.")
    fields = StackFieldChangeSerializer(many=True, help_text="Each field that changes.")  # type: ignore[assignment]
    source = DefinitionSourceRefSerializer(allow_null=True, help_text="Where the definition lives in the repository.")  # type: ignore[assignment]
    loses = serializers.CharField(
        allow_null=True, help_text="For a recreate, what a person loses, such as history or links. Null otherwise."
    )
    entity_id = serializers.CharField(
        required=False, help_text="For an adopt, the id of the existing entity the push binds."
    )


class DriftFieldSerializer(serializers.Serializer):
    path = serializers.CharField(help_text="The field that changed outside the code.")
    pushed = JsonValueField(allow_null=True, help_text="The value the last push set.")
    found = JsonValueField(allow_null=True, help_text="The value PostHog holds now.")
    sensitive = serializers.BooleanField(required=False, help_text="True when the value is secret.")


class DriftSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="The definition kind.")
    key = serializers.CharField(help_text="The definition key.")
    deleted = serializers.BooleanField(
        required=False,
        default=False,
        help_text="True when the entity was deleted in PostHog outside of code. A push creates it again.",
    )
    fields = DriftFieldSerializer(many=True, help_text="Each field that changed outside the code.")  # type: ignore[assignment]


class DiffSummarySerializer(serializers.Serializer):
    create = serializers.IntegerField(help_text="Entities a push creates.")  # type: ignore[assignment]
    update = serializers.IntegerField(help_text="Entities a push changes in place.")  # type: ignore[assignment]
    recreate = serializers.IntegerField(help_text="Entities a push deletes and creates again.")
    remove = serializers.IntegerField(help_text="Entities a push removes.")
    adopt = serializers.IntegerField(help_text="Existing entities a push binds to the stack.")
    rename = serializers.IntegerField(help_text="Definitions whose key changes with nothing recreated.")
    release = serializers.IntegerField(
        required=False,
        help_text="Entities the stack stops managing and leaves in PostHog: removed definitions of adopted entities, "
        "detached entities, and kinds code never deletes.",
    )


class DiffErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="A stable code for the error, such as `reference_missing` or `stack_moved`.")
    message = serializers.CharField(help_text="What went wrong and what to do next.")
    kind = serializers.CharField(required=False, help_text="The kind of the definition the error is about.")
    key = serializers.CharField(required=False, help_text="The key of the definition the error is about.")
    path = serializers.CharField(required=False, help_text="The field of the definition the error is about.")


class WarningEntitySerializer(serializers.Serializer):
    entity_id = serializers.CharField(help_text="The id of the entity in PostHog. Adopt takes this id.")
    name = serializers.CharField(help_text="The entity's display name.")


class DiffWarningSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            ("possible_unrecorded_create", "possible_unrecorded_create"),
            ("unrecorded_creates_unchecked", "unrecorded_creates_unchecked"),
        ],
        help_text="`possible_unrecorded_create`: an interrupted push may already have created this definition, and "
        "`entities` lists the candidates. `unrecorded_creates_unchecked`: PostHog could not read every entity of "
        "the kind, so check in PostHog by hand.",
    )
    kind = serializers.CharField(help_text="The definition kind.")
    key = serializers.CharField(allow_null=True, help_text="The definition key. Null for a whole kind.")
    message = serializers.CharField(help_text="What to check and what to do next.")
    entities = WarningEntitySerializer(
        many=True, help_text="Entities with the definition's name that no stack manages. Adopt one, or reconcile."
    )


class DiffResultSerializer(serializers.Serializer):
    changes = StackChangeSerializer(
        many=True, help_text="What a push would create, change, recreate, remove, adopt or rename."
    )
    drift = DriftSerializer(many=True, help_text="Entities changed outside the code since the last push.")
    summary = DiffSummarySerializer(help_text="The number of changes by action.")
    errors = DiffErrorSerializer(many=True, help_text="Why the diff could not be computed. Empty for a ready diff.")  # type: ignore[assignment]
    warnings = DiffWarningSerializer(
        many=True,
        required=False,
        default=list,
        help_text="Only after a push that stopped without a known outcome: entities it may have created without "
        "recording them. Adopt them, or reconcile to let this diff create them.",
    )


class StackDiffSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The diff id. Pushing this id changes PostHog by exactly this diff.")
    stack_name = serializers.CharField(help_text="The stack the diff belongs to.")
    status = serializers.ChoiceField(
        choices=DiffStatus.choices,
        help_text="`running` while the diff or its push runs, `ready` to push, `failed` when the diff or its last push "
        "failed, `pushed` once pushed, `stale` when the stack changed since the diff was made.",
    )
    diff = DiffResultSerializer(allow_null=True, help_text="The diff. Null while it is running.")
    source = DiffSourceSerializer(help_text="The repository, branch and commit the description came from.")  # type: ignore[assignment]
    created_at = serializers.DateTimeField(help_text="When the diff was requested.")
    expires_at = serializers.DateTimeField(help_text="After this time the diff can no longer be pushed.")
    push_status = serializers.ChoiceField(
        choices=PushStatus.choices, allow_null=True, help_text="The last push of this diff. Null when never pushed."
    )
    push_errors = DiffErrorSerializer(many=True, help_text="Why the last push failed. Empty otherwise.")


class BindingSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The binding id. Detach takes this id.")
    stack_name = serializers.CharField(help_text="The stack that manages the entity.")
    repository = serializers.CharField(help_text="The repository the stack was last pushed from. Empty before a push.")
    kind = serializers.CharField(help_text="The definition kind.")
    key = serializers.CharField(help_text="The definition key.")
    entity_id = serializers.CharField(help_text="The id of the entity in PostHog.")
    entity_url = serializers.CharField(
        allow_null=True, help_text="Where the entity opens in PostHog. Null for some kinds."
    )
    source = DefinitionSourceRefSerializer(allow_null=True, help_text="Where the definition lives in the repository.")  # type: ignore[assignment]
    status = serializers.ChoiceField(
        choices=BindingStatus.choices,
        help_text="`bound` once a push made or adopted the entity, `pending` when adopt recorded it and no push ran "
        "yet, `detached` once released to the UI.",
    )
    owned_fields = serializers.ListField(
        child=serializers.CharField(),
        help_text="The fields code owns, as sorted dotted paths into the definition body, such as `name` or "
        "`filters.payloads`. A write to one of them is refused with `managed_in_code`. Empty when code owns none.",
    )


KIND_CHOICES_TEXT = (
    "One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, "
    "`dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`."
)


class AdoptResourceSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, help_text=f"The definition kind of the entity. {KIND_CHOICES_TEXT}")
    key = serializers.CharField(max_length=KEY_MAX_LENGTH, help_text="The key the definition will use in the stack.")
    entity_id = serializers.CharField(max_length=512, help_text="The id of the existing entity in PostHog.")


class AdoptRequestSerializer(serializers.Serializer):
    resources = AdoptResourceSerializer(
        many=True, allow_empty=False, help_text="The entities to bind. The next push binds them and creates nothing."
    )


class AdoptResponseSerializer(serializers.Serializer):
    bindings = BindingSerializer(many=True, help_text="The pending bindings adopt recorded.")


class AdoptableQuerySerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, help_text=f"The definition kind to list. {KIND_CHOICES_TEXT}")
    cursor = serializers.CharField(
        required=False, max_length=2000, help_text="The `cursor` from the previous page's `next` URL."
    )
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, default=100, help_text="How many entities to read, at most 100."
    )


class AdoptableEntitySerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="The definition kind.")
    entity_id = serializers.CharField(help_text="The id of the entity in PostHog.")
    name = serializers.CharField(help_text="The entity's display name.")
    body = JsonObjectField(help_text="The entity shaped like a description body, for generating its definition.")


class BindingLookupQuerySerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=64, help_text=f"The definition kind of the entity. {KIND_CHOICES_TEXT}")
    entity_id = serializers.CharField(
        max_length=512,
        help_text="The id of the entity in PostHog. For a kind whose key is a name, such as an event name or a "
        "context page path, that name finds it too.",
    )


class BindingLookupSerializer(serializers.Serializer):
    binding = BindingSerializer(
        allow_null=True, help_text="The binding that manages the entity. Null when no stack does."
    )


class ReconcileRequestSerializer(serializers.Serializer):
    diff_id = serializers.UUIDField(
        help_text="A ready diff computed since the uncertain push. Reconciling accepts its warnings."
    )


class ReconciledSerializer(serializers.Serializer):
    stack_name = serializers.CharField(help_text="The stack, which can push again.")
    diff_id = serializers.UUIDField(help_text="The diff the person reconciled with. Push it next.")
    acknowledged_warnings = serializers.IntegerField(help_text="How many warnings of that diff were accepted.")


class StackErrorResponseSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="The error class, such as `invalid_request` or `authentication_error`.")
    code = serializers.ChoiceField(
        choices=StackErrorCode.choices,
        help_text="A stable code for the error. `stack_moved`: run diff again. `stack_locked`: wait for the running "
        "push. `diff_expired`: run diff again. `push_uncertain`: run diff, review its warnings, then reconcile. "
        "`permission_denied` with `required_scopes`: the key lacks a scope the run needs. "
        "`nothing_to_reconcile`: the stack has no uncertain push. "
        "`managed_in_code`: edit the definition in the repository instead.",
    )
    detail = serializers.CharField(help_text="What went wrong and what to do next.")
    attr = serializers.CharField(allow_null=True, help_text="The request field the error is about, if any.")
    extra = JsonObjectField(
        required=False,
        help_text="More about the error. `required_scopes` for a missing scope. For `managed_in_code`: `kind`, "
        "`binding_id`, `stack`, `repository`, `source` and `fields`.",
    )


class AdoptablePageSerializer(serializers.Serializer):
    count = serializers.IntegerField(
        allow_null=True, help_text="Always null: the total is not known before the last page is read."
    )
    next = serializers.CharField(allow_null=True, help_text="The URL of the next page, or null on the last page.")
    previous = serializers.CharField(allow_null=True, help_text="Always null: pages are read forward only.")
    results = AdoptableEntitySerializer(many=True, help_text="Entities of the kind that no stack manages.")


class SecretWriteSerializer(serializers.Serializer):
    value = serializers.CharField(
        max_length=65536,
        trim_whitespace=False,
        write_only=True,
        help_text="The secret's value. Stored encrypted and never returned. Send it from a file or stdin, never "
        "from a command line argument.",
    )


class SecretSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The name definitions use in `secret('NAME')`.")
    updated_at = serializers.DateTimeField(help_text="When the value was last set.")


class SecretListSerializer(serializers.Serializer):
    results = SecretSerializer(many=True, help_text="Every secret the stack holds, by name. Never the values.")


class ContextPagesRequestSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(
        help_text="Whether this stack may manage context pages. They belong to the organization's one wiki, so only "
        "an organization admin can turn this on."
    )


class StackSettingsSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="The stack name.")
    context_pages_enabled = serializers.BooleanField(help_text="Whether this stack may manage context pages.")


class ManagedKindSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="A definition kind some stack in this project manages, such as `flag`.")
    stack_name = serializers.CharField(help_text="The stack that manages entities of this kind.")
    repository = serializers.CharField(help_text="The repository the stack was last pushed from. Edit the code there.")
    definitions = serializers.IntegerField(help_text="How many entities of this kind the stack manages.")
    redirect_creates = serializers.BooleanField(
        help_text="True when this kind's entities are definitions named by a natural key, such as an event or a flag. "
        "Do not create one of these outside code: add its definition in the repository instead."
    )


class ManagedKindListSerializer(serializers.Serializer):
    results = ManagedKindSerializer(
        many=True, help_text="One row per kind and stack. Before creating an entity of a listed kind, add it in code."
    )


class ModuleLanguage(LabeledStrEnum):
    PYTHON = "python", "Python"
    GOLANG = "golang", "Go"
    TYPESCRIPT = "typescript", "TypeScript"


class GenerateModuleRequestSerializer(serializers.Serializer):
    description = StackDescriptionSerializer(help_text="The stack description that `check` produced.")
    language = serializers.ChoiceField(
        choices=ModuleLanguage.choices, help_text="The language of the module to generate."
    )


class GeneratedModuleSerializer(serializers.Serializer):
    content = serializers.CharField(
        help_text="The module's source code, typed for the events the description declares."
    )
    language = serializers.ChoiceField(choices=ModuleLanguage.choices, help_text="The module's language.")
    event_count = serializers.IntegerField(help_text="How many events the module covers.")
    schema_hash = serializers.CharField(
        help_text="A hash of the events and the generator version. A module whose hash differs is stale."
    )
    generator_version = serializers.CharField(help_text="The version of the generator that wrote the module.")


class RequestedChangeSerializer(serializers.Serializer):
    path = serializers.CharField(
        max_length=500, help_text="The field to change, as a dotted path into the definition body."
    )
    value = JsonValueField(allow_null=True, help_text="The value the person wants the field to have.")


class StackChangeRequestSerializer(serializers.Serializer):
    note = serializers.CharField(
        max_length=4000,
        help_text="What the person wants changed, in their own words. A cloud task reads it as a description of the "
        "change, not as instructions.",
    )
    changes = serializers.ListField(
        child=RequestedChangeSerializer(),
        required=False,
        default=list,
        max_length=50,
        help_text="Field values the person asked for, if any.",
    )


class StartedChangeRequestSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="The cloud task that edits the definition and opens a pull request.")
    task_url = serializers.CharField(help_text="Where the task's progress shows in PostHog.")
