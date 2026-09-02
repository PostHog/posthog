"""
Django models for docs.

Keep models thin — business logic belongs in logic/.
"""

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from .facade.enums import DocKind, DocStatus


def doc_status_choices() -> list[tuple[str, str]]:
    return [(status.value, status.value) for status in DocStatus]


def doc_kind_choices() -> list[tuple[str, str]]:
    return [(kind.value, kind.value) for kind in DocKind]


class Doc(TeamScopedRootMixin, UUIDModel):
    """A collaborative rich-text document filed in a channel (a "space" in PostHog Desktop).

    ``content`` is a ProseMirror document and ``version`` is the collab version that
    produced it. Live editing runs through the Redis transport in ``posthog/collab``;
    this row is the durable copy every client reloads from.

    Blocks inside the content hold references — a task id, a PostHog object kind and id —
    never the values behind them, so a status change never rewrites the document.
    """

    # db_constraint=False: a real FK constraint to the hot posthog_team table
    # takes a parent lock during migration; scoping is enforced app-side.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # Channels are the tasks product's model; every doc belongs to one space.
    channel = models.ForeignKey("tasks.Channel", on_delete=models.CASCADE, db_constraint=False, related_name="docs")

    title = models.CharField(max_length=400, blank=True, default="")
    status = models.CharField(max_length=16, choices=doc_status_choices, default=DocStatus.DRAFT)
    # One doc per space is its context notes: edited like any page, compiled into the
    # space's wiki page every agent reads. It never shows in the space's tab row.
    kind = models.CharField(max_length=16, choices=doc_kind_choices, default=DocKind.PAGE)
    position = models.IntegerField(default=0)

    content = models.JSONField(null=True, blank=True)
    # Plain-text mirror of `content`, written on every save so search never parses JSON.
    text_content = models.TextField(blank=True, null=True)
    version = models.IntegerField(default=0)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "docs_doc"
        indexes = [
            models.Index(fields=["channel", "position"], name="docs_channel_position"),
        ]

    def __str__(self) -> str:
        return self.title or "Untitled"
