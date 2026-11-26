"""Finds and rewrites the stored rows that can hold email content, for the asset URL maintenance commands."""

from collections.abc import Callable
from typing import Any, Final

from django.db import models, transaction
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.messaging.backend.facade.api import (
    find_template_ids_containing,
    find_template_team_ids_containing,
    rewrite_template_content,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate

WorkerReload = Callable[[int, str], None]
BlobRewrite = Callable[[Any], tuple[Any, int]]

# Only executed config has a worker-side cache to invalidate; templates are copied at creation time
# and never read by a worker, so they need no reload. The workflow model reloads its own rows on commit.
WORKER_RELOADS: Final[dict[str, WorkerReload]] = {
    "hog_functions": lambda team_id, row_id: reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[row_id]
    ),
}

# Every column that can hold rendered email content, mapped to the timestamp that tracks it.
# `actions`/`inputs` carry both the editable value (html, design) and the compiled hog bytecode the
# executor renders from when an input isn't liquid, so a rewrite has to cover the whole blob -
# fixing only value.html would leave those sends unchanged.
MODEL_TARGETS: Final[dict[str, tuple[type[models.Model], dict[str, str]]]] = {
    "hog_flows": (HogFlow, {"actions": "updated_at", "draft": "draft_updated_at"}),
    "hog_flow_templates": (HogFlowTemplate, {"actions": "updated_at"}),
    "hog_functions": (HogFunction, {"inputs": "updated_at", "draft": "draft_updated_at"}),
}
# Message templates belong to messaging, which finds and rewrites its own rows (content, draft, updated_at).
MESSAGE_TEMPLATES: Final = "message_templates"
TARGETS: Final[tuple[str, ...]] = ("hog_flows", "hog_flow_templates", MESSAGE_TEMPLATES, "hog_functions")


def find_row_ids(target: str, text: str, *, team_ids: list[int] | None, row_id: str | None = None) -> list[Any]:
    """Ids of the target's rows whose email content contains `text`, in id order."""
    if target == MESSAGE_TEMPLATES:
        return find_template_ids_containing(text, team_ids=team_ids, template_id=row_id)
    return list(_matching(target, text, team_ids=team_ids, row_id=row_id).order_by("id").values_list("id", flat=True))


def team_ids_containing(target: str, text: str) -> set[int]:
    """Teams with at least one row of the target whose email content contains `text`."""
    if target == MESSAGE_TEMPLATES:
        return find_template_team_ids_containing(text)
    return set(_matching(target, text, team_ids=None).values_list("team_id", flat=True).distinct())


def _matching(target: str, text: str, *, team_ids: list[int] | None, row_id: str | None = None) -> models.QuerySet:
    # The text casts belong only on the id-matching query, where they stay in the WHERE clause.
    # Loading rows off the un-annotated base queryset avoids the database returning a full text
    # copy of every large JSON column alongside the value we actually rewrite.
    matcher = _base_queryset(target, team_ids=team_ids, row_id=row_id)
    match = models.Q()
    for field in MODEL_TARGETS[target][1]:
        matcher = matcher.annotate(**{f"_text_{field}": Cast(field, models.TextField())})
        match |= models.Q(**{f"_text_{field}__contains": text})
    return matcher.filter(match)


def rewrite_row(target: str, row_id: Any, rewrite: BlobRewrite, *, team_ids: list[int] | None, dry_run: bool) -> int:
    """Apply `rewrite` to every email content column of one row under a row lock. Returns the occurrences replaced,
    or for a dry run the occurrences it would replace."""
    if target == MESSAGE_TEMPLATES:
        return rewrite_template_content(row_id, rewrite, team_ids=team_ids, dry_run=dry_run)

    field_timestamps = MODEL_TARGETS[target][1]
    base_queryset = _base_queryset(target, team_ids=team_ids)
    if dry_run:
        row = base_queryset.get(pk=row_id)
        return sum(rewrite(getattr(row, field))[1] for field in field_timestamps)

    publish_reload = WORKER_RELOADS.get(target)
    # Read the row again under a row lock and rewrite that value, not the one the id scan saw.
    # A customer saving the same workflow in between would otherwise have their edit overwritten
    # by the stale blob this command is holding - the same lost write the API path guards against
    # with select_for_update plus its staleness fence.
    with transaction.atomic():
        row = base_queryset.select_for_update().get(pk=row_id)

        changed_fields: list[str] = []
        occurrences = 0
        for field in field_timestamps:
            new_value, found = rewrite(getattr(row, field))
            if found:
                setattr(row, field, new_value)
                changed_fields.append(field)
                occurrences += found

        if not occurrences:
            return 0

        # Bump the timestamp that tracks each column we touched, so the editor's stale-write
        # detection sees the change instead of letting an open tab save the old URL back.
        # Keeping a draft-only rewrite on draft_updated_at also keeps it out of the live row's
        # history, and lets the post_save receivers skip a worker reload nothing is executing yet.
        timestamp_fields: list[str] = []
        live_change = False
        for field in changed_fields:
            timestamp_field = field_timestamps[field]
            live_change = live_change or timestamp_field == "updated_at"
            if timestamp_field in timestamp_fields:
                continue
            timestamp_fields.append(timestamp_field)
            # updated_at is auto_now, so listing it is enough; the rest need an explicit value.
            if timestamp_field != "updated_at":
                setattr(row, timestamp_field, timezone.now())

        # One row per save, never bulk_update: workers only drop their cached copy when a reload
        # is published for the row, and bulk_update fires no signal at all.
        row.save(update_fields=[*changed_fields, *timestamp_fields])

        # The hog function post_save receiver publishes from inside this transaction, so a worker can re-read
        # the row before the UPDATE commits and cache the old blob for another refresh window.
        # Publishing again on commit is what workers actually act on; the duplicate is harmless.
        # Draft-only rewrites publish nothing, matching the receiver that skips them.
        if live_change and publish_reload is not None:
            team_id, row_pk = row.team_id, str(row.pk)
            transaction.on_commit(lambda: publish_reload(team_id, row_pk))

    return occurrences


def _base_queryset(target: str, *, team_ids: list[int] | None, row_id: str | None = None) -> models.QuerySet:
    model = MODEL_TARGETS[target][0]
    # _default_manager, not .objects: this is generic over the model targets, and Model itself
    # doesn't declare a manager. unscoped() where it exists - a fix like this is deliberately
    # cross-team, so a fail-closed manager would otherwise raise TeamScopeError.
    manager = model._default_manager
    queryset = manager.unscoped() if hasattr(manager, "unscoped") else manager.all()
    if team_ids:
        queryset = queryset.filter(team_id__in=team_ids)
    if row_id:
        queryset = queryset.filter(id=row_id)
    return queryset
