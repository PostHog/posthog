from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

from django.db import models, transaction
from django.db.models.fields.json import KT
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.api.tagged_item import cleanup_orphan_tags, current_tag_names, set_tags_on_object
from posthog.models import TaggedItem
from posthog.models.tag import tagify

from products.messaging.backend.facade.contracts import EmailTemplateSummary
from products.messaging.backend.models import MessageCategory, MessageTemplate


def get_email_content(team_id: int, template_id: UUID) -> dict | None:
    template = MessageTemplate.objects.filter(team_id=team_id, id=template_id, deleted=False).first()
    email_content = (template.content or {}).get("email") if template else None
    return email_content if isinstance(email_content, dict) else None


def list_email_summaries(team_id: int, *, limit: int) -> list[EmailTemplateSummary]:
    """The team's newest email templates that have a subject and a body. Only the subject leaves the database, so a
    large saved design is never loaded for a listing."""
    rows = (
        MessageTemplate.objects.filter(team_id=team_id, deleted=False, type="email")
        .annotate(subject=KT("content__email__subject"), html=KT("content__email__html"))
        .exclude(subject__isnull=True)
        .exclude(subject="")
        .exclude(html__isnull=True)
        .exclude(html="")
        .order_by("-created_at")
        .values_list("id", "name", "subject")[:limit]
    )
    return [EmailTemplateSummary(id=id, name=name or "", subject=subject) for id, name, subject in rows]


def _templates(team_ids: list[int] | None) -> models.QuerySet[MessageTemplate]:
    queryset = MessageTemplate.objects.all()
    return queryset.filter(team_id__in=team_ids) if team_ids else queryset


def find_ids_containing(text: str, *, team_ids: list[int] | None, template_id: str | None) -> list[UUID]:
    queryset = _templates(team_ids)
    if template_id:
        queryset = queryset.filter(id=template_id)
    # The text cast stays in the WHERE clause, so the scan never returns a full copy of each content blob.
    return list(
        queryset.annotate(_text_content=Cast("content", models.TextField()))
        .filter(_text_content__contains=text)
        .order_by("id")
        .values_list("id", flat=True)
    )


def rewrite_content(
    template_id: UUID, rewrite: Callable[[Any], tuple[Any, int]], *, team_ids: list[int] | None, dry_run: bool
) -> int:
    if dry_run:
        return rewrite(_templates(team_ids).get(pk=template_id).content)[1]

    # Read the row again under a row lock, so a concurrent save is not overwritten with a stale blob.
    with transaction.atomic():
        template = _templates(team_ids).select_for_update().get(pk=template_id)
        new_content, occurrences = rewrite(template.content)
        if not occurrences:
            return 0
        template.content = new_content
        # updated_at is auto_now, so listing it bumps it. The editor's stale-write check reads it.
        template.save(update_fields=["content", "updated_at"])
    return occurrences


def _with_tags(queryset: models.QuerySet[MessageTemplate]) -> models.QuerySet[MessageTemplate]:
    # The contract reads prefetched_tags, so a page costs one tag query rather than one per row.
    return queryset.prefetch_related(
        models.Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
    )


def team_templates(team_id: int) -> models.QuerySet[MessageTemplate]:
    # The pk tiebreak keeps pages stable, as the mixin ordering did for the queryset view.
    return _with_tags(MessageTemplate.objects.filter(team_id=team_id, deleted=False)).order_by("-created_at", "-pk")


def team_template(team_id: int, template_id: UUID | str) -> MessageTemplate:
    return MessageTemplate.objects.get(team_id=team_id, deleted=False, pk=template_id)


def category_id_for_team(team_id: int, category_id: Any) -> UUID:
    # Not filtered on deleted, as the related field this serves never was.
    return MessageCategory.objects.get(team_id=team_id, pk=category_id).pk


def _apply_fields(template: MessageTemplate, fields: dict[str, Any]) -> None:
    for attr, value in fields.items():
        setattr(template, "message_category_id" if attr == "message_category" else attr, value)


def create_template(team_id: int, created_by_id: int | None, fields: dict[str, Any]) -> MessageTemplate:
    fields = dict(fields)
    tags = fields.pop("tags", None)
    with transaction.atomic():
        template = MessageTemplate(team_id=team_id, created_by_id=created_by_id)
        _apply_fields(template, fields)
        template.save(force_insert=True)
        if tags:
            set_tags_on_object(tags, template)
    return template


def update_template(team_id: int, template_id: UUID | str, fields: dict[str, Any]) -> MessageTemplate:
    fields = dict(fields)
    tags = fields.pop("tags", None)
    with transaction.atomic():
        template = team_template(team_id, template_id)
        # The editor sends the tags with every save, so only write them when they change.
        tags_changed = tags is not None and {tagify(tag) for tag in tags} != current_tag_names(template)
        # Tags live on their own rows. Saving the template too would write back every column this
        # read saw, so a tag edit would overwrite content a concurrent publish had just committed.
        if fields:
            _apply_fields(template, fields)
            template.save()
        if tags_changed:
            set_tags_on_object(tags, template)
            cleanup_orphan_tags(team_id)
    return template


def save_draft(team_id: int, template_id: UUID | str, draft: dict[str, Any] | None) -> MessageTemplate:
    # Writes only the draft, so a draft save that races a publish, a delete or a conversion can't undo it.
    MessageTemplate.objects.filter(team_id=team_id, deleted=False, pk=template_id).update(
        draft_content=draft, updated_at=timezone.now()
    )
    return team_template(team_id, template_id)


def edit_content_locked(
    team_id: int, template_id: UUID | str, edit: Callable[[dict[str, Any]], dict[str, Any]]
) -> MessageTemplate:
    with transaction.atomic():
        # nosemgrep: idor-lookup-without-team (re-fetch of an already team-scoped template, locked for update)
        locked = MessageTemplate.objects.select_for_update().get(pk=team_template(team_id, template_id).pk)
        locked.content = edit(deepcopy(locked.content or {}))
        locked.save()
    return locked
