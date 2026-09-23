"""Skills store skills attached to a workflow's "Create AI task" node.

The node stores skill names. Every fire resolves them to the latest published version and
lists them in the run's prompt, so the agent knows what is available and fetches a body over
MCP when it reaches work the skill covers. Nothing is written to disk, which is why this is a
renderer and a lookup rather than a packaging step.

Kept out of `workflow_tasks.py` so the skills store is reachable from one file in this product,
and so the renderer stays testable without a database.
"""

import structlog

from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.skills.backend.api.skill_services import skill_name_is_well_formed
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)

MAX_ATTACHED_SKILLS = 10

# Long enough to say when a skill applies, short enough that ten of them stay a small part of
# the prompt. The store allows 4096, and legacy rows use it.
MANIFEST_DESCRIPTION_MAX_CHARS = 300


class WorkflowTaskSkillsInvalid(Exception):
    def __init__(self, message: str, *, invalid_names: list[str] | None = None) -> None:
        self.invalid_names = invalid_names or []
        super().__init__(message)


@frozen
class AttachedSkill:
    """One skill resolved against the store at fire time, ready to name in the prompt."""

    name: str
    version: int
    description: str


def select_skill_names(names: list[str] | None) -> list[str]:
    """The names to resolve, deduplicated in the order the workflow author chose them.

    A repeated name would render twice and read as two skills. The picker cannot produce one,
    but an API or MCP caller can.
    """
    if not names:
        return []
    return list(dict.fromkeys(names))[:MAX_ATTACHED_SKILLS]


def validate_skill_names(team: Team, owner_id: int, names: list[str] | None) -> None:
    """Raise `WorkflowTaskSkillsInvalid` for a name the workflow owner cannot use.

    Called from the workflows product when a "Create AI task" action is saved, so a typo from a
    programmatic author fails at save time instead of quietly shrinking the manifest on every fire.

    An archived skill remains valid when the owner could read one of its versions. The fire path
    drops it and runs anyway, so archiving must not make its workflow unsaveable.
    """
    if not names:
        return
    if len(names) > MAX_ATTACHED_SKILLS:
        raise WorkflowTaskSkillsInvalid(f"Attach at most {MAX_ATTACHED_SKILLS} skills to one task step.")
    requested = set(names)
    valid_names = {name for name in requested if skill_name_is_well_formed(name)}
    owner = User.objects.filter(id=owner_id).first()

    readable_names: set[str] = set()
    if owner is not None and valid_names:
        access_control = UserAccessControl(user=owner, team=team)
        active_candidates = LLMSkill.objects.filter(team=team, name__in=valid_names, deleted=False, is_latest=True)
        active_names = set(active_candidates.values_list("name", flat=True))
        readable_names.update(
            access_control.filter_queryset_by_access_level(active_candidates, resource="llm_skill").values_list(
                "name", flat=True
            )
        )

        archived_only_names = valid_names - active_names
        archived_candidates = LLMSkill.objects.filter(team=team, name__in=archived_only_names, deleted=True)
        readable_names.update(
            access_control.filter_queryset_by_access_level(archived_candidates, resource="llm_skill").values_list(
                "name", flat=True
            )
        )

    unavailable = sorted(requested - readable_names)
    if unavailable:
        raise WorkflowTaskSkillsInvalid(f"Skill(s) not found or unavailable: {unavailable}", invalid_names=unavailable)


def resolve_attached_skills(team: Team, owner: User, names: list[str] | None) -> list[AttachedSkill]:
    """The attached skills that exist and the workflow owner can read, latest version each.

    A name that resolves to nothing is dropped with a warning, never raised. The node fires on
    trigger events with nobody watching the run, so raising would turn one archived skill into a
    failure on every event until someone noticed. A skill is supplementary to a prompt that
    already stands on its own, so a run missing one is still worth doing. This matches
    `load_perspectives_for_run`, which skips a dead perspective for the same reason.

    Access control here keeps the prompt honest rather than enforcing anything: `skill-get`
    checks access itself when the agent calls. Filtering now stops the manifest promising a
    skill the agent will then be refused.
    """
    requested = select_skill_names(names)
    if not requested:
        return []
    wanted = [name for name in requested if skill_name_is_well_formed(name)]

    # Not `get_active_skill_queryset`: it annotates version-history metadata with three
    # correlated subqueries per row, none of which the manifest reads.
    readable = UserAccessControl(user=owner, team=team).filter_queryset_by_access_level(
        LLMSkill.objects.filter(team=team, name__in=wanted, deleted=False, is_latest=True),
        resource="llm_skill",
    )
    live = {
        name: (version, description)
        for name, version, description in readable.values_list("name", "version", "description")
    }

    unresolved = [name for name in requested if name not in live]
    if unresolved:
        logger.warning(
            "workflow_task_skills_unresolved",
            team_id=team.id,
            skills=unresolved,
        )

    # Author order, not database order: the workflow author chose the sequence.
    return [
        AttachedSkill(name=name, version=live[name][0], description=live[name][1] or "")
        for name in wanted
        if name in live
    ]


def _manifest_line(skill: AttachedSkill) -> str:
    # The list gives the model one line per skill, so a description holding a newline would make
    # its tail read as the next skill's name. Collapsing every run of whitespace also folds the
    # tabs and carriage returns that survive a copy and paste into the store.
    description = " ".join(skill.description.split())[:MANIFEST_DESCRIPTION_MAX_CHARS]
    name = " ".join(skill.name.split()).replace("`", "\\`")
    if not description:
        return f"- `{name}` (v{skill.version})"
    return f"- `{name}` (v{skill.version}): {description}"


def render_skills_manifest(skills: list[AttachedSkill]) -> str:
    """The prompt block naming the attached skills and how to read one.

    Versions are pinned to what was latest when the run was created, not to what is latest when
    the agent calls. The prompt is rendered once at fire time and the call happens minutes later,
    so an unpinned fetch could mix two versions of one procedure into a single run.

    The `call <tool> {json}` form is required because the task sandbox mounts the PostHog MCP in
    single-exec mode. It matches the skill stubs the store already ships into task sandboxes.
    """
    if not skills:
        return ""
    listing = "\n".join(_manifest_line(skill) for skill in skills)
    return (
        "This workflow attached the following skills from this project's skills store. Each one is a set\n"
        "of instructions for a specific job, and the text after its name says when it applies.\n\n"
        f"{listing}\n\n"
        "When you reach work one of these covers, read it before you act on it, and not before. Run\n"
        '`call skill-get {"skill_name": "<name>", "version": <version>}` with the PostHog MCP `exec` tool.\n'
        "Pass the version listed above, so a version published while this run is in flight cannot mix two\n"
        "versions into one procedure. If the response has a non-null `body_next_offset`, call `skill-get`\n"
        "again with the same version and `body_offset` set to that value, and append the returned `body`\n"
        "until it comes back null. If the body references bundled files, fetch each one with\n"
        '`call skill-file-get {"skill_name": "<name>", "file_path": "<path>", "version": <version>}`.\n\n'
        "A skill's instructions apply only inside the job it covers. Where a skill and the prompt for this\n"
        "run disagree, follow the prompt. If `skill-get` reports the skill was not found, or the tool is\n"
        "not available in this run, note that in your final output and continue without it."
    )
