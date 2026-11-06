from typing import Protocol
from uuid import UUID

from django.db import IntegrityError, transaction

from products.messaging.backend.facade.contracts import TemplateKeyRefused, TemplateWriteIntent
from products.messaging.backend.models import MessageTemplate
from products.messaging.backend.models.message_template import KEY_CONSTRAINT
from products.messaging.backend.services.template_ownership import check_write, patches_only
from products.messaging.backend.services.template_saves import WorkflowEditorCheck, lock_template
from products.messaging.backend.services.transactional_email import known_key


class KeyedTemplate(Protocol):
    @property
    def key(self) -> str | None: ...


def is_adoption(intent: TemplateWriteIntent) -> bool:
    return patches_only(intent, "key")


def check_key_kept(template: KeyedTemplate, intent: TemplateWriteIntent) -> None:
    if template.key and "key" in intent.payload and intent.payload["key"] != template.key:
        raise _key_already_set(template.key)


def check_key_unchanged(template: KeyedTemplate, intent: TemplateWriteIntent) -> None:
    check_key_kept(template, intent)
    if "key" not in intent.payload or intent.payload["key"] == template.key:
        return
    raise TemplateKeyRefused(
        code="invalid_request",
        detail="`key` can't be set together with other fields.",
        why="A key prepares the template for uploads from code, so it is set in a request of its own.",
        fix="Send a PATCH whose only field is `key`, then send the other changes.",
    )


def adopt_template(
    team_id: int,
    template_id: UUID,
    key: str,
    *,
    intent: TemplateWriteIntent,
    require_workflow_editor: WorkflowEditorCheck,
) -> MessageTemplate:
    try:
        with transaction.atomic():
            template = lock_template(team_id, template_id)
            check_write(template, intent)
            if template.transactional_hog_flow_id:
                require_workflow_editor(template.transactional_hog_flow_id)
            if template.key:
                raise _key_already_set(template.key)
            _require_editor_of_the_key_workflow(team_id, key, require_workflow_editor)
            template.key = key
            template.save(update_fields=["key", "updated_at"])
    except IntegrityError as error:
        if KEY_CONSTRAINT not in str(error):
            raise
        raise _key_in_use(key) from error
    return template


def _require_editor_of_the_key_workflow(team_id: int, key: str, require_workflow_editor: WorkflowEditorCheck) -> None:
    key_workflow = known_key(team_id, key)
    if key_workflow is not None:
        require_workflow_editor(key_workflow.hog_flow_id)


def _key_already_set(key: str) -> TemplateKeyRefused:
    return TemplateKeyRefused(
        code="key_already_set",
        detail=f"This template already has the key `{key}`.",
        why="Code names the template by its key, so a key never changes.",
        fix=f"Use `{key}` in your code, or duplicate the template and give the copy a key.",
    )


def _key_in_use(key: str) -> TemplateKeyRefused:
    return TemplateKeyRefused(
        code="key_in_use",
        detail=f"Another template in this project has the key `{key}`.",
        why="A key names one template in a project.",
        fix="Pick another key, or upload your file to the template that has this key.",
    )
