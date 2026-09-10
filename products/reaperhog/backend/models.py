import uuid

from django.db import models
from django.utils.functional import Promise

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from products.reaperhog.backend.facade.enums import (
    ArtefactType,
    BlockedReason,
    ClusterRank,
    ClusterStatus,
    InventoryStatus,
    RootKind,
)
from products.reaperhog.backend.logic.artefacts import ArtefactContent, artefact_type_for


def reaper_artefact_type_choices() -> list[tuple[str, str | Promise]]:
    return [(t.value, t.value) for t in ArtefactType]


class ReaperInventory(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    repository = models.CharField(max_length=255)
    scope = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in InventoryStatus],
        default=InventoryStatus.IDLE.value,
    )
    run_count = models.IntegerField(default=0)
    last_scan_sha = models.CharField(max_length=64, null=True, blank=True)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repository", "scope"], name="uniq_reaper_inventory_scope"),
        ]


class ReaperCluster(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    inventory = models.ForeignKey(ReaperInventory, on_delete=models.CASCADE, related_name="clusters")
    hash = models.CharField(max_length=16)
    root_kind = models.CharField(max_length=32, choices=[(k.value, k.value) for k in RootKind])
    root = models.CharField(max_length=512)
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in ClusterStatus],
        default=ClusterStatus.CANDIDATE.value,
    )
    rank = models.CharField(max_length=8, choices=[(r.value, r.value) for r in ClusterRank])
    blocked_reason = models.CharField(
        max_length=16, choices=[(b.value, b.value) for b in BlockedReason], null=True, blank=True
    )
    scouts = models.JSONField(default=list)
    files = models.JSONField(default=list)
    reference_count = models.IntegerField(default=0)
    line_count = models.IntegerField(default=0)
    owner = models.CharField(max_length=255, null=True, blank=True)
    task_id = models.UUIDField(null=True, blank=True)
    pr_url = models.TextField(null=True, blank=True)
    pr_number = models.IntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_sha = models.CharField(max_length=64, null=True, blank=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["inventory", "hash"], name="uniq_reaper_cluster_hash"),
        ]
        indexes = [
            models.Index(fields=["inventory", "status"], name="reaper_cluster_inv_status_idx"),
        ]


class ReaperArtefact(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    inventory = models.ForeignKey(ReaperInventory, on_delete=models.CASCADE, related_name="artefacts")
    cluster = models.ForeignKey(
        ReaperCluster, on_delete=models.CASCADE, related_name="artefacts", null=True, blank=True
    )
    type = models.CharField(max_length=32, choices=reaper_artefact_type_choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["cluster", "type", "-created_at"], name="reaper_art_cluster_type_idx"),
            models.Index(fields=["inventory", "type", "-created_at"], name="reaper_art_inv_type_idx"),
        ]

    @classmethod
    def append(
        cls,
        *,
        team_id: int,
        inventory_id: uuid.UUID,
        content: ArtefactContent,
        cluster_id: uuid.UUID | None = None,
    ) -> "ReaperArtefact":
        return cls.objects.for_team(team_id).create(
            team_id=team_id,
            inventory_id=inventory_id,
            cluster_id=cluster_id,
            type=artefact_type_for(content),
            content=content.model_dump_json(),
        )
