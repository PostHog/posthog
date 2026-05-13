from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.utils import generate_short_id


class MindMapPostIt(ModelActivityMixin, RootTeamMixin, UUIDTModel):
    class Color(models.TextChoices):
        YELLOW = "yellow", "Yellow"
        PINK = "pink", "Pink"
        BLUE = "blue", "Blue"
        GREEN = "green", "Green"
        PURPLE = "purple", "Purple"
        ORANGE = "orange", "Orange"
        GRAY = "gray", "Gray"

    short_id = models.CharField(max_length=12, default=generate_short_id, blank=True)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.CharField(max_length=256)
    body = models.TextField(blank=True, default="")
    color = models.CharField(max_length=16, choices=Color.choices, default=Color.YELLOW)
    emoji = models.CharField(max_length=8, blank=True, default="")
    position_x = models.FloatField(default=0.0)
    position_y = models.FloatField(default=0.0)
    notebook_short_id = models.CharField(max_length=12, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_mindmap_postits"
    )
    last_modified_at = models.DateTimeField(auto_now=True)
    last_modified_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="modified_mindmap_postits"
    )
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "posthog_mindmap_postit"
        constraints = [
            models.UniqueConstraint(fields=["team", "short_id"], name="mindmap_postit_unique_short_id"),
        ]
        indexes = [
            models.Index(fields=["team", "deleted"], name="mm_postit_team_deleted_idx"),
        ]


class MindMapEdge(ModelActivityMixin, RootTeamMixin, UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source = models.ForeignKey(MindMapPostIt, on_delete=models.CASCADE, related_name="outgoing_edges")
    target = models.ForeignKey(MindMapPostIt, on_delete=models.CASCADE, related_name="incoming_edges")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_mindmap_edges"
    )

    class Meta:
        db_table = "posthog_mindmap_edge"
        constraints = [
            models.UniqueConstraint(fields=["source", "target"], name="mindmap_edge_unique_pair"),
            models.CheckConstraint(
                check=~models.Q(source=models.F("target")),
                name="mindmap_edge_no_self_loop",
            ),
        ]
        indexes = [
            models.Index(fields=["team"], name="mindmap_edge_team_idx"),
        ]
