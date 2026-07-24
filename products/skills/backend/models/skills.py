from django.db import models
from django.db.models import Count, DateTimeField, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import UUIDModel

# Server-owned grouping stamped on every create path (REST serializer, MCP tool, import): the Skills
# page's category tabs (SKILL_CATEGORY_TABS in llmSkillsLogic.ts) filter on `category`, and the
# generic create flows are how custom scouts and review-hog skills are authored — without the stamp
# they'd never surface beside their canonical siblings. Values mirror SCOUT_SKILL_CATEGORY /
# REVIEW_HOG_SKILL_CATEGORY (products can't import each other, so they're duplicated here exactly
# like the frontend tab map duplicates them).
CATEGORY_BY_NAME_PREFIX: tuple[tuple[str, str], ...] = (
    ("signals-scout-", "scout"),
    ("review-hog-", "review_hog"),
)


def category_for_skill_name(name: str) -> str:
    return next((category for prefix, category in CATEGORY_BY_NAME_PREFIX if name.startswith(prefix)), "")


class LLMSkill(UUIDModel):
    class Meta:
        db_table = "llm_analytics_llmskill"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name", "version"],
                condition=Q(deleted=False),
                name="unique_llm_skill_version_per_team",
            ),
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=Q(deleted=False, is_latest=True),
                name="unique_llm_skill_latest_per_team",
            ),
        ]

    # Required by Agent Skills spec (https://agentskills.io/specification)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=4096)

    # The SKILL.md body content (markdown instructions)
    body = models.TextField()

    # Optional Agent Skills spec fields
    license = models.CharField(max_length=255, blank=True, default="")
    compatibility = models.CharField(max_length=500, blank=True, default="")
    allowed_tools = models.JSONField(blank=True, default=list)
    metadata = models.JSONField(blank=True, default=dict)

    # Generic classification, decoupled from the skill name. Empty for an ordinary skill; a known
    # value (e.g. "scout") groups the skill into its own surface in the UI. Producers own the value
    # (the Signals harness stamps "scout"); the skills product treats it as an opaque string.
    category = models.CharField(max_length=64, blank=True, default="", db_default="")

    # Versioning (same pattern as LLMPrompt)
    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    deleted = models.BooleanField(default=False)


class LLMSkillFile(UUIDModel):
    class Meta:
        db_table = "llm_analytics_llmskillfile"
        constraints = [
            models.UniqueConstraint(
                fields=["skill", "path"],
                name="unique_skill_file_path",
            ),
        ]

    skill = models.ForeignKey(LLMSkill, on_delete=models.CASCADE, related_name="files")
    path = models.CharField(max_length=500)
    content = models.TextField()
    content_type = models.CharField(max_length=100, default="text/plain")


class LLMSkillOwner(UUIDModel):
    """A human who owns a skill, keyed on the *logical* skill `(team, name)` — not a version row.

    Ownership is version-independent by construction: each skill version is its own `LLMSkill`
    row keyed `(team, name, version)`, so anything hung off a version row drifts every time the
    body is edited. Keying owners on `(team, skill_name)` means editing a skill can never touch
    who owns it. Owners are a list, so removing one (its row is dropped) leaves the rest — unlike
    a per-version `created_by`, whose `SET_NULL` on user deletion silently hands ownership to the
    first surviving editor.

    This is the durable answer to "who should review reports about this scout?": the reviewer
    path prefers these owners over reconstructing authorship from mutable version history.

    Scoped to the *exact* environment team, matching `LLMSkill` (a plain `UUIDModel` queried by
    `team=<environment>`) — deliberately NOT `TeamScopedRootMixin`, whose `save()`/`for_team()`
    canonicalize the team to the parent project. If owners were project-canonical while skills are
    environment-scoped, two sibling environments with a same-named skill would share one owner set,
    letting an edit in one environment overwrite the routing (and expose owner profiles) of the
    other. `objects = TeamScopedManager()` keeps it fail-closed against ambient access; every read
    and write goes through `for_team(team.id, canonical=True)`, which filters on the exact team id
    without the child→parent resolution.
    """

    objects = TeamScopedManager()

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): a real FK
    # constraint would take a lock on the parent when this table's rows are created. Enforcement
    # is app-level; the unique constraint below is a plain index and unaffected.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # Logical skill identity, not a version FK — see the class docstring.
    skill_name = models.CharField(max_length=64)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "llm_analytics_llmskillowner"
        constraints = [
            # Its leading (team, skill_name) columns also serve the reviewer path's lookup of all
            # owners for one logical skill, so no separate index is needed.
            models.UniqueConstraint(
                fields=["team", "skill_name", "user"],
                name="unique_llm_skill_owner",
            ),
        ]


def annotate_llm_skill_version_history_metadata(queryset: QuerySet[LLMSkill]) -> QuerySet[LLMSkill]:
    active_versions = LLMSkill.objects.filter(team_id=OuterRef("team_id"), name=OuterRef("name"), deleted=False)

    version_count = Subquery(
        active_versions.values("name").annotate(count=Count("id")).values("count")[:1],
        output_field=IntegerField(),
    )
    latest_version = Subquery(
        active_versions.order_by("-version", "-created_at", "-id").values("version")[:1],
        output_field=IntegerField(),
    )
    first_version_created_at = Subquery(
        active_versions.filter(version=1).order_by("created_at", "id").values("created_at")[:1],
        output_field=DateTimeField(),
    )
    return queryset.annotate(
        version_count=version_count,
        latest_version=latest_version,
        first_version_created_at=first_version_created_at,
    )
