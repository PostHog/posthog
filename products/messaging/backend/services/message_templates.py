from collections.abc import Callable
from copy import deepcopy
from typing import Any
from uuid import UUID

from django.db import models
from django.db.models.fields.json import KT
from django.db.models.functions import Cast

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


def templates_of(team_ids: list[int] | None) -> models.QuerySet[MessageTemplate]:
    queryset = MessageTemplate.objects.all()
    return queryset.filter(team_id__in=team_ids) if team_ids else queryset


def find_ids_containing(text: str, *, team_ids: list[int] | None, template_id: str | None) -> list[UUID]:
    queryset = templates_of(team_ids)
    if template_id:
        queryset = queryset.filter(id=template_id)
    # The text cast stays in the WHERE clause, so the scan never returns a full copy of each content blob.
    return list(
        queryset.annotate(_text_content=Cast("content", models.TextField()))
        .filter(_text_content__contains=text)
        .order_by("id")
        .values_list("id", flat=True)
    )


def team_templates(team_id: int) -> models.QuerySet[MessageTemplate]:
    # The pk tiebreak keeps pages stable, as the mixin ordering did for the queryset view.
    return MessageTemplate.objects.filter(team_id=team_id, deleted=False).order_by("-created_at", "-pk")


def team_template(team_id: int, template_id: UUID | str) -> MessageTemplate:
    return MessageTemplate.objects.get(team_id=team_id, deleted=False, pk=template_id)


def category_id_for_team(team_id: int, category_id: Any) -> UUID:
    # Not filtered on deleted, as the related field this serves never was.
    return MessageCategory.objects.get(team_id=team_id, pk=category_id).pk


def apply_fields(template: MessageTemplate, fields: dict[str, Any]) -> None:
    for attr, value in fields.items():
        setattr(template, "message_category_id" if attr == "message_category" else attr, value)


def create_template(team_id: int, created_by_id: int | None, fields: dict[str, Any]) -> MessageTemplate:
    template = MessageTemplate(team_id=team_id, created_by_id=created_by_id)
    apply_fields(template, fields)
    template.save(force_insert=True)
    return template


def edit_content(template: MessageTemplate, edit: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    template.content = edit(deepcopy(template.content or {}))
