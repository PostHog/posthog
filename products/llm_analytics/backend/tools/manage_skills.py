"""Max AI tools for managing and using LLM analytics skills.

Skills (Agent Skills spec) are reusable, versioned packages of instructions for AI agents.
These tools let users list, read, create, edit, archive, and duplicate their skills from
the Max chat, and load a skill's content to use it as task-specific guidance.
"""

from typing import Any

from django.db import IntegrityError, transaction

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool

from ..api.skill_serializers import SKILL_NAME_PATTERN, validate_skill_file_path
from ..api.skill_services import (
    MAX_SKILL_BODY_BYTES,
    MAX_SKILL_FILE_COUNT,
    LLMSkillDuplicateNameConflictError,
    LLMSkillEditError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    archive_skill,
    duplicate_skill,
    get_latest_skills_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
)
from ..models.skills import LLMSkill, LLMSkillFile

SKILLS_RESOURCE_READ: list[tuple] = [("llm_analytics", "viewer")]
SKILLS_RESOURCE_WRITE: list[tuple] = [("llm_analytics", "editor")]


# ---------------------------------------------------------------------------
# Shared formatters / helpers
# ---------------------------------------------------------------------------


def _format_skill_summary(skill: LLMSkill, *, files_count: int) -> str:
    lines = [
        f"- {skill.name} (v{skill.version})",
        f"    Description: {skill.description}" if skill.description else "    Description: (none)",
    ]
    if files_count:
        lines.append(f"    Bundled files: {files_count}")
    if skill.allowed_tools:
        lines.append(f"    Allowed tools: {', '.join(skill.allowed_tools)}")
    lines.append(f"    Last updated: {skill.updated_at}")
    return "\n".join(lines)


def _format_skill_detail(skill: LLMSkill, *, files: list[LLMSkillFile]) -> str:
    lines = [
        f"# {skill.name} (v{skill.version})",
        "",
        f"Description: {skill.description or '(none)'}",
    ]
    if skill.license:
        lines.append(f"License: {skill.license}")
    if skill.compatibility:
        lines.append(f"Compatibility: {skill.compatibility}")
    if skill.allowed_tools:
        lines.append(f"Allowed tools: {', '.join(skill.allowed_tools)}")
    if skill.metadata:
        lines.append(f"Metadata: {skill.metadata}")
    lines.append("")
    lines.append("## Body (SKILL.md)")
    lines.append("")
    lines.append(skill.body or "(empty)")

    if files:
        lines.append("")
        lines.append("## Bundled files")
        for f in files:
            lines.append(f"- {f.path} ({f.content_type}, {len(f.content)} chars)")
        lines.append("")
        lines.append("Use `get_llm_skill_file` with the path to load any of the above bundled files on demand.")
    return "\n".join(lines)


def _conflict_message(err: LLMSkillVersionConflictError) -> str:
    return (
        f"This skill changed since you opened it. Current version is {err.current_version}. "
        "Re-fetch the skill with `get_llm_skill` and retry with the latest base_version."
    )


def _validate_skill_name(name: str) -> str | None:
    if not name:
        return "Skill name is required."
    if name.lower() == "new":
        return "'new' is a reserved name. Pick another."
    if len(name) > 64:
        return "Skill name must be 64 characters or fewer."
    if not SKILL_NAME_PATTERN.match(name):
        return (
            "Skill name must use only lowercase letters, numbers, and hyphens. "
            "It must not start or end with a hyphen or contain consecutive hyphens."
        )
    return None


# ---------------------------------------------------------------------------
# Tool 1: list_llm_skills
# ---------------------------------------------------------------------------


LIST_TOOL_DESCRIPTION = """List the LLM analytics skills available in this project.

# When to use this tool:
- The user asks "what skills do I have?", "list my skills", "show my workflows"
- You are deciding whether a relevant skill exists before doing work — check first so the
  user's encoded workflow drives the answer instead of an ad-hoc plan
- The user references a skill by a partial name or fuzzy description

Returns a compact summary of each skill (name, version, description, file count). Use
`get_llm_skill` to load a specific skill's full body and file manifest.
""".strip()


class ListLLMSkillsArgs(BaseModel):
    search: str | None = Field(
        default=None,
        description="Optional substring filter applied to skill names and descriptions.",
    )
    limit: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum number of skills to return (1-100).",
    )


class ListLLMSkillsTool(MaxTool):
    name: str = AssistantTool.LIST_LLM_SKILLS.value
    description: str = LIST_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ListLLMSkillsArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_READ

    async def _arun_impl(self, search: str | None = None, limit: int = 25) -> tuple[str, None]:
        formatted = await database_sync_to_async(self._fetch_and_format)(search, limit)
        return (formatted, None)

    def _fetch_and_format(self, search: str | None, limit: int) -> str:
        from django.db.models import Count, Q

        queryset = get_latest_skills_queryset(self._team).annotate(_files_count=Count("files"))
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        skills = list(queryset.order_by("-updated_at", "-id")[:limit])

        if not skills:
            if search:
                return f"No skills found matching '{search}'. Try a different search or list all with no search term."
            return (
                "No skills found in this project. You can create one with `create_llm_skill` to "
                "encode a common workflow."
            )

        header = f"Found {len(skills)} skill(s):" if len(skills) != 1 else "Found 1 skill:"
        return "\n".join([header, *(_format_skill_summary(s, files_count=s._files_count) for s in skills)])


# ---------------------------------------------------------------------------
# Tool 2: get_llm_skill
# ---------------------------------------------------------------------------


GET_TOOL_DESCRIPTION = """Load a single LLM analytics skill by name.

# When to use this tool:
- You found a relevant skill via `list_llm_skills` and want to load its instructions
- The user names a skill they want you to "use" or "follow" for the current task
- You need the current `version` before calling `update_llm_skill` (publish needs base_version)

Returns the skill's full SKILL.md body, metadata, and the list of bundled files. Use
`get_llm_skill_file` to load any bundled file content (progressive disclosure).
""".strip()


class GetLLMSkillArgs(BaseModel):
    name: str = Field(description="Name of the skill to fetch (kebab-case, e.g. 'investigate-metric').")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Specific version to load. Omit to load the latest version.",
    )


class GetLLMSkillTool(MaxTool):
    name: str = AssistantTool.GET_LLM_SKILL.value
    description: str = GET_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = GetLLMSkillArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_READ

    async def _arun_impl(self, name: str, version: int | None = None) -> tuple[str, None]:
        formatted = await database_sync_to_async(self._fetch_and_format)(name, version)
        return (formatted, None)

    def _fetch_and_format(self, name: str, version: int | None) -> str:
        skill = get_skill_by_name_from_db(self._team, name, version)
        if skill is None:
            return f"Skill '{name}' not found."
        files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
        return _format_skill_detail(skill, files=files)


# ---------------------------------------------------------------------------
# Tool 3: get_llm_skill_file
# ---------------------------------------------------------------------------


GET_FILE_TOOL_DESCRIPTION = """Load the contents of a bundled file inside a skill.

# When to use this tool:
- A skill's manifest references a bundled file (e.g. `scripts/setup.sh`, `references/schema.md`)
  and the user's task needs that file's content
- Follow the progressive disclosure pattern: load files only when needed, not pre-emptively
""".strip()


class GetLLMSkillFileArgs(BaseModel):
    name: str = Field(description="Skill name.")
    path: str = Field(description="Bundled file path inside the skill (e.g. 'scripts/setup.sh').")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Specific skill version to read the file from. Omit for the latest version.",
    )


class GetLLMSkillFileTool(MaxTool):
    name: str = AssistantTool.GET_LLM_SKILL_FILE.value
    description: str = GET_FILE_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = GetLLMSkillFileArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_READ

    async def _arun_impl(self, name: str, path: str, version: int | None = None) -> tuple[str, None]:
        try:
            validate_skill_file_path(path)
        except Exception as e:
            return (f"Invalid file path: {e}", None)

        result = await database_sync_to_async(self._fetch_file)(name, path, version)
        if isinstance(result, str):
            return (result, None)
        skill_file: LLMSkillFile = result
        return (
            f"File '{skill_file.path}' from skill '{name}' ({skill_file.content_type}):\n\n{skill_file.content}",
            None,
        )

    def _fetch_file(self, name: str, path: str, version: int | None) -> "LLMSkillFile | str":
        skill = get_skill_by_name_from_db(self._team, name, version)
        if skill is None:
            return f"Skill '{name}' not found."
        skill_file = LLMSkillFile.objects.filter(skill=skill, path=path).first()
        if skill_file is None:
            return f"File '{path}' not found in skill '{name}'."
        return skill_file


# ---------------------------------------------------------------------------
# Tool 4: create_llm_skill
# ---------------------------------------------------------------------------


CREATE_TOOL_DESCRIPTION = """Create a new LLM analytics skill (version 1) to encode a reusable workflow.

# When to use this tool:
- The user asks "save this as a skill", "encode this workflow", "make this a skill"
- You've helped the user develop a multi-step process they'll want to repeat

# Format:
- `name`: kebab-case, lowercase letters/numbers/hyphens, max 64 chars (e.g. 'investigate-metric-drop')
- `description`: short one-liner explaining when to use the skill
- `body`: the SKILL.md content — a markdown document giving instructions an agent should follow
  when this skill applies. Keep it focused.
- `allowed_tools` (optional): names of tools the skill is allowed to call when followed

Returns the created skill so the user can confirm it. Use `update_llm_skill` to publish a
new version later.
""".strip()


class CreateSkillFileInput(BaseModel):
    path: str = Field(description="Relative path of the bundled file (e.g. 'scripts/setup.sh').")
    content: str = Field(description="Text contents of the bundled file.")
    content_type: str = Field(default="text/plain", description="MIME type. Defaults to text/plain.")


class CreateLLMSkillArgs(BaseModel):
    name: str = Field(description="Kebab-case skill name (max 64 chars).")
    description: str = Field(description="Short description of when to use this skill.", max_length=4096)
    body: str = Field(description="SKILL.md markdown body — the instructions an agent will follow.")
    license: str | None = Field(default=None, description="Optional license string.")
    compatibility: str | None = Field(default=None, description="Optional compatibility note.")
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Optional list of tool names this skill is allowed to call.",
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Optional arbitrary metadata.")
    files: list[CreateSkillFileInput] | None = Field(
        default=None,
        description=f"Optional bundled files (max {MAX_SKILL_FILE_COUNT}).",
    )


class CreateLLMSkillTool(MaxTool):
    name: str = AssistantTool.CREATE_LLM_SKILL.value
    description: str = CREATE_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateLLMSkillArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_WRITE

    async def _arun_impl(
        self,
        name: str,
        description: str,
        body: str,
        license: str | None = None,
        compatibility: str | None = None,
        allowed_tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        files: list[CreateSkillFileInput] | None = None,
    ) -> tuple[str, None]:
        validation_error = _validate_skill_name(name)
        if validation_error:
            return (validation_error, None)

        if len(body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
            return (f"Skill body exceeds the {MAX_SKILL_BODY_BYTES} byte size limit.", None)

        normalized_files: list[dict[str, str]] = []
        if files:
            if len(files) > MAX_SKILL_FILE_COUNT:
                return (f"A skill may contain at most {MAX_SKILL_FILE_COUNT} files.", None)
            seen: set[str] = set()
            for file_input in files:
                try:
                    validate_skill_file_path(file_input.path)
                except Exception as e:
                    return (f"Invalid file path '{file_input.path}': {e}", None)
                if file_input.path in seen:
                    return (f"Duplicate file path '{file_input.path}' in input.", None)
                seen.add(file_input.path)
                normalized_files.append(
                    {
                        "path": file_input.path,
                        "content": file_input.content,
                        "content_type": file_input.content_type or "text/plain",
                    }
                )

        try:
            result = await database_sync_to_async(self._create_skill_and_format)(
                name=name,
                description=description,
                body=body,
                license=license or "",
                compatibility=compatibility or "",
                allowed_tools=allowed_tools or [],
                metadata=metadata or {},
                files=normalized_files,
            )
        except IntegrityError as err:
            err_str = str(err)
            if "unique_llm_skill_latest_per_team" in err_str or "unique_llm_skill_version_per_team" in err_str:
                return (
                    f"A skill named '{name}' already exists. Pick a different name or update the existing skill.",
                    None,
                )
            raise

        return (result, None)

    def _create_skill_and_format(
        self,
        *,
        name: str,
        description: str,
        body: str,
        license: str,
        compatibility: str,
        allowed_tools: list[str],
        metadata: dict[str, Any],
        files: list[dict[str, str]],
    ) -> str:
        with transaction.atomic():
            skill = LLMSkill.objects.create(
                team=self._team,
                created_by=self._user,
                name=name,
                description=description,
                body=body,
                license=license,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                metadata=metadata,
                version=1,
                is_latest=True,
            )
            if files:
                LLMSkillFile.objects.bulk_create(
                    [
                        LLMSkillFile(
                            skill=skill,
                            path=f["path"],
                            content=f["content"],
                            content_type=f["content_type"],
                        )
                        for f in files
                    ]
                )
        saved_files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
        return f"Created skill '{skill.name}' (v{skill.version}).\n\n{_format_skill_detail(skill, files=saved_files)}"


# ---------------------------------------------------------------------------
# Tool 5: update_llm_skill
# ---------------------------------------------------------------------------


UPDATE_TOOL_DESCRIPTION = """Publish a new version of an existing LLM analytics skill.

# When to use this tool:
- The user wants to edit a skill's instructions, description, or metadata
- The user wants to add, change, or remove bundled files

# Optimistic concurrency:
You MUST pass `base_version` — the version number you read most recently via `get_llm_skill`.
If the skill has changed since, the call fails with a conflict and you should re-fetch.

# Body updates: two options (don't combine):
- `body`: replace the whole SKILL.md body
- `edits`: a list of `{old, new}` find-and-replace patches applied sequentially. Each `old`
  must occur exactly once in the current body — supply enough context to make it unique.

Any field you omit carries forward unchanged.
""".strip()


class SkillBodyEditInput(BaseModel):
    old: str = Field(description="Exact text to replace in the current body. Must occur exactly once.")
    new: str = Field(description="Replacement text.")


class UpdateLLMSkillArgs(BaseModel):
    name: str = Field(description="Skill name to update.")
    base_version: int = Field(
        ge=1,
        description="The current version you observed before editing — used for optimistic concurrency.",
    )
    body: str | None = Field(
        default=None,
        description="New full SKILL.md body. Mutually exclusive with `edits`.",
    )
    edits: list[SkillBodyEditInput] | None = Field(
        default=None,
        description="Sequential find/replace edits to apply to the current body. Mutually exclusive with `body`.",
    )
    description: str | None = Field(default=None, description="New description.")
    license: str | None = Field(default=None, description="New license string.")
    compatibility: str | None = Field(default=None, description="New compatibility note.")
    allowed_tools: list[str] | None = Field(default=None, description="Replacement list of allowed tools.")
    metadata: dict[str, Any] | None = Field(default=None, description="Replacement metadata dict.")


class UpdateLLMSkillTool(MaxTool):
    name: str = AssistantTool.UPDATE_LLM_SKILL.value
    description: str = UPDATE_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = UpdateLLMSkillArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_WRITE

    async def _arun_impl(
        self,
        name: str,
        base_version: int,
        body: str | None = None,
        edits: list[SkillBodyEditInput] | None = None,
        description: str | None = None,
        license: str | None = None,
        compatibility: str | None = None,
        allowed_tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, None]:
        if body is not None and edits is not None:
            return ("Pass either `body` or `edits`, not both.", None)

        edits_payload: list[dict[str, str]] | None = (
            [{"old": e.old, "new": e.new} for e in edits] if edits is not None else None
        )

        try:
            result = await database_sync_to_async(self._publish_and_format)(
                name=name,
                body=body,
                edits_payload=edits_payload,
                description=description,
                license=license,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                metadata=metadata,
                base_version=base_version,
            )
        except LLMSkillNotFoundError:
            return (f"Skill '{name}' not found.", None)
        except LLMSkillVersionConflictError as err:
            return (_conflict_message(err), None)
        except LLMSkillVersionLimitError as err:
            return (
                f"Skill '{name}' has reached the maximum of {err.max_version} versions. "
                "Archive it and create a new one to keep iterating.",
                None,
            )
        except LLMSkillEditError as err:
            return (f"Failed to apply edit: {err.message}", None)

        return (result, None)

    def _publish_and_format(
        self,
        *,
        name: str,
        body: str | None,
        edits_payload: list[dict[str, str]] | None,
        description: str | None,
        license: str | None,
        compatibility: str | None,
        allowed_tools: list[str] | None,
        metadata: dict[str, Any] | None,
        base_version: int,
    ) -> str:
        updated = publish_skill_version(
            self._team,
            user=self._user,
            skill_name=name,
            body=body,
            edits=edits_payload,
            description=description,
            license=license,
            compatibility=compatibility,
            allowed_tools=allowed_tools,
            metadata=metadata,
            base_version=base_version,
        )
        files = list(LLMSkillFile.objects.filter(skill=updated).order_by("path"))
        return f"Published v{updated.version} of '{updated.name}'.\n\n{_format_skill_detail(updated, files=files)}"


# ---------------------------------------------------------------------------
# Tool 6: archive_llm_skill
# ---------------------------------------------------------------------------


ARCHIVE_TOOL_DESCRIPTION = """Archive an LLM analytics skill (soft-delete all of its versions).

# When to use this tool:
- The user explicitly asks to delete, archive, or remove a skill

This operation is irreversible from the UI — archived skills are no longer listed and cannot
be published to. Always confirm with the user before calling.
""".strip()


class ArchiveLLMSkillArgs(BaseModel):
    name: str = Field(description="Name of the skill to archive.")


class ArchiveLLMSkillTool(MaxTool):
    name: str = AssistantTool.ARCHIVE_LLM_SKILL.value
    description: str = ARCHIVE_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = ArchiveLLMSkillArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_WRITE

    async def is_dangerous_operation(self, **kwargs) -> bool:
        return True

    async def format_dangerous_operation_preview(self, name: str, **kwargs) -> str:
        return f"Archive skill '{name}' (all versions). This is irreversible from the UI."

    async def _arun_impl(self, name: str) -> tuple[str, None]:
        try:
            versions = await database_sync_to_async(archive_skill)(self._team, name)
        except LLMSkillNotFoundError:
            return (f"Skill '{name}' not found.", None)

        return (
            f"Archived skill '{name}' ({len(versions)} version(s): {versions}).",
            None,
        )


# ---------------------------------------------------------------------------
# Tool 7: duplicate_llm_skill
# ---------------------------------------------------------------------------


DUPLICATE_TOOL_DESCRIPTION = """Duplicate an existing skill to a new name (starts at v1).

# When to use this tool:
- The user asks to "copy", "clone", or "fork" a skill
- You want to derive a new skill from an existing one as a starting point

The copy includes the body, metadata, and all bundled files of the source skill's latest version.
""".strip()


class DuplicateLLMSkillArgs(BaseModel):
    source_name: str = Field(description="Name of the skill to duplicate.")
    new_name: str = Field(description="Name for the new skill (kebab-case, must not exist).")


class DuplicateLLMSkillTool(MaxTool):
    name: str = AssistantTool.DUPLICATE_LLM_SKILL.value
    description: str = DUPLICATE_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = DuplicateLLMSkillArgs

    def get_required_resource_access(self):
        return SKILLS_RESOURCE_WRITE

    async def _arun_impl(self, source_name: str, new_name: str) -> tuple[str, None]:
        validation_error = _validate_skill_name(new_name)
        if validation_error:
            return (validation_error, None)

        try:
            result = await database_sync_to_async(self._duplicate_and_format)(source_name, new_name)
        except LLMSkillNotFoundError:
            return (f"Source skill '{source_name}' not found.", None)
        except LLMSkillDuplicateNameConflictError:
            return (f"A skill named '{new_name}' already exists.", None)

        return (result, None)

    def _duplicate_and_format(self, source_name: str, new_name: str) -> str:
        new_skill = duplicate_skill(
            self._team,
            user=self._user,
            source_name=source_name,
            new_name=new_name,
        )
        files = list(LLMSkillFile.objects.filter(skill=new_skill).order_by("path"))
        return (
            f"Duplicated '{source_name}' to '{new_name}' (v{new_skill.version}).\n\n"
            f"{_format_skill_detail(new_skill, files=files)}"
        )


__all__ = [
    "ListLLMSkillsTool",
    "GetLLMSkillTool",
    "GetLLMSkillFileTool",
    "CreateLLMSkillTool",
    "UpdateLLMSkillTool",
    "ArchiveLLMSkillTool",
    "DuplicateLLMSkillTool",
]
