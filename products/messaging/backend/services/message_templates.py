from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import models, transaction
from django.db.models.functions import Cast

from products.messaging.backend.models import MessageTemplate


def get_email_content(team_id: int, template_id: UUID) -> dict | None:
    template = MessageTemplate.objects.filter(team_id=team_id, id=template_id, deleted=False).first()
    email_content = (template.content or {}).get("email") if template else None
    return email_content if isinstance(email_content, dict) else None


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
