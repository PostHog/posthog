from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class LearnedRuleKind(models.TextChoices):
    ENCOURAGE = "encourage", "Encourage"
    AVOID = "avoid", "Avoid"


class ReplayVisionLearnedRuleset(TeamScopedRootMixin, UUIDModel):
    """One version of the rules distilled from a team's observation ratings, injected into later scans.

    A row with no scanner holds the project-wide rules; a row with a scanner holds that scanner's own. Rows
    are append-only and the highest version per scope is the current one, so each observation can record
    which version steered it. Never exposed to users: no serializer, no API, no MCP tool.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="learned_rulesets",
    )
    version = models.PositiveIntegerField()
    # Shape: list of `learned_rules.LearnedRule` dicts.
    rules = models.JSONField(default=list)
    model = models.CharField(max_length=64, blank=True, default="")
    trace_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "version"],
                condition=models.Q(scanner__isnull=True),
                name="rvlr_team_version_uniq",
            ),
            models.UniqueConstraint(
                fields=["scanner", "version"],
                condition=models.Q(scanner__isnull=False),
                name="rvlr_scanner_version_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "scanner", "-version"], name="rvlr_team_scanner_ver_idx"),
        ]

    def __str__(self) -> str:
        scope = f"scanner {self.scanner_id}" if self.scanner_id else "project"
        return f"{scope} v{self.version} ({len(self.rules or [])} rules)"
