import posixpath
from typing import Any

from django.db.models import Q

from pydantic import BaseModel, Field

from posthog.schema import AssistantTool

from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from products.skills.backend.api.skill_services import (
    LLMSkillDuplicateNameConflictError,
    LLMSkillEditError,
    LLMSkillFileLimitError,
    LLMSkillFilePathConflictError,
    LLMSkillNotFoundError,
    LLMSkillVersionConflictError,
    LLMSkillVersionLimitError,
    archive_skill,
    create_skill,
    get_latest_skills_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
)
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolFatalError

MAX_LIST_RESULTS = 50


LIST_SKILLS_DESCRIPTION = """List shared agent skills stored for this team.

Returns each skill's name and description. Use the descriptions to decide which skill to fetch — never load every body upfront.

# When to use this tool
- Before tackling a non-trivial task, check whether the team has a stored skill that already covers it (a workflow,
  runbook, or multi-step recipe).
- When the user mentions "skills", "team skills", "shared skills", or asks what skills are available.
- When the user asks you to follow a specific named workflow that may exist as a skill.

# What this tool returns
A list of `name` + `description` pairs, plus an indication of whether more results were truncated. This is the
discovery step in progressive disclosure — load the body with `get_llm_skill` once you have a candidate."""


GET_SKILL_DESCRIPTION = """Fetch a stored agent skill by name. Returns the full SKILL.md body (markdown instructions), metadata, and a
manifest of bundled files (paths only — content is loaded on demand via `get_llm_skill_file`).

# When to use this tool
- After `list_llm_skills` surfaces a skill whose description matches the task.
- When the user names a skill explicitly ("use the make-fractals skill", "follow the onboarding-audit skill").
- When you need to manage a skill (edit / archive) — fetch first to get the current `version` so you can pass
  `base_version` for the next write.

# What this tool returns
The skill body (treat as system instructions for the current task), description, version, optional license /
compatibility / allowed_tools / metadata, and a file manifest (path + content_type only). Read the body, then pull
individual files with `get_llm_skill_file` only when the body references them."""


GET_SKILL_FILE_DESCRIPTION = """Fetch a single bundled file from a stored skill by path.

# When to use this tool
- The skill body references a script, reference doc, or asset and you actually need its content.
- Do NOT preload every file in the manifest — only fetch what the body's decision tree points to.

# What this tool returns
The file `path`, `content`, and `content_type`."""


CREATE_SKILL_DESCRIPTION = """Create a new agent skill (a reusable workflow stored for the whole team).

# When to use this tool
- The user asks to save, store, or remember a workflow, runbook, or multi-step procedure as a shared skill.
- A reusable recipe emerged from the conversation and the user wants it captured.

# Required input
- `name`: kebab-case, lowercase letters/numbers/hyphens, <=64 chars, no leading/trailing/consecutive hyphens.
- `description`: explains what it does AND when to use it (this is the only thing visible at discovery time).
- `body`: the SKILL.md instructions as markdown. Keep under ~500 lines — move long scripts and references into
  `files` so the body stays scannable.

# Optional input
- `license`, `compatibility`, `allowed_tools`, `metadata`: spec fields (see agentskills.io).
- `files`: bundled files (`path`, `content`, `content_type`). Use `scripts/` for executable code, `references/` for
  docs, `assets/` for templates."""


UPDATE_SKILL_DESCRIPTION = """Publish a new version of an existing skill. Any field not provided is carried forward from the current latest.

# When to use this tool
- The user asks to update, edit, or improve an existing skill.
- You spotted an error or improvement opportunity in a skill body and the user approved the change.

# Required input
- `skill_name`: the kebab-case name of the skill.
- `base_version`: the version number returned by the most recent `get_llm_skill`. Required for optimistic
  concurrency — the request fails if someone else published a newer version in the meantime.

# Body changes (pick one)
- `body`: full replacement (good for substantial rewrites).
- `edits`: incremental find/replace (good for small tweaks). Each entry needs `old` (must match exactly once) and
  `new`. Mutually exclusive with `body`.

# Other writable fields
- `description`, `license`, `compatibility`, `allowed_tools`, `metadata`.
- `file_edits`: per-file find/replace patches. Each entry targets one existing file by `path` with its own `edits`
  list. Files not mentioned are carried forward unchanged. Cannot add, remove, or rename files."""


ARCHIVE_SKILL_DESCRIPTION = """Archive every active version of a skill by name. This hides the skill from default lists and cannot be
undone. Use `get_llm_skill` first if you need to inspect the skill before archiving it."""


class ListSkillsArgs(BaseModel):
    search: str | None = Field(
        default=None,
        description="Optional case-insensitive substring filter applied to name and description.",
    )


class GetSkillArgs(BaseModel):
    skill_name: str = Field(description="The kebab-case name of the skill to fetch.")
    version: int | None = Field(
        default=None,
        description="Optional specific version to fetch. Defaults to the latest active version.",
    )


class GetSkillFileArgs(BaseModel):
    skill_name: str = Field(description="The kebab-case name of the skill that owns the file.")
    file_path: str = Field(description="The path of the bundled file as it appears in the skill's file manifest.")
    version: int | None = Field(
        default=None,
        description="Optional specific skill version. Defaults to the latest active version.",
    )


class CreateSkillArgs(BaseModel):
    name: str = Field(description="Kebab-case skill name. <=64 chars. Must be unique within the team.")
    description: str = Field(
        description="Short summary explaining what the skill does and when agents should pick it. <=4096 chars.",
    )
    body: str = Field(description="SKILL.md instructions as markdown. Treated as system instructions when invoked.")
    license: str | None = Field(default=None, description="Optional license string (e.g. 'MIT').")
    compatibility: str | None = Field(
        default=None,
        description="Optional compatibility notes (e.g. 'Requires Python 3.10+ with Pillow').",
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Optional list of tool names the skill is permitted to invoke.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional free-form metadata dict (author, category, etc.).",
    )
    files: list[dict[str, str]] | None = Field(
        default=None,
        description=(
            "Optional bundled files. Each item: {path, content, content_type?}. "
            "Use scripts/, references/, or assets/ subdirs by convention."
        ),
    )


class UpdateSkillArgs(BaseModel):
    skill_name: str = Field(description="The kebab-case name of the skill to update.")
    base_version: int = Field(
        description="The version observed at fetch time. Required for optimistic concurrency.",
    )
    body: str | None = Field(default=None, description="Full replacement body. Mutually exclusive with 'edits'.")
    edits: list[dict[str, str]] | None = Field(
        default=None,
        description=(
            "Incremental find/replace edits applied sequentially to the current body. "
            "Each entry: {old, new}. 'old' must match exactly once. Mutually exclusive with 'body'."
        ),
    )
    description: str | None = Field(default=None, description="Optional new description.")
    license: str | None = Field(default=None, description="Optional new license.")
    compatibility: str | None = Field(default=None, description="Optional new compatibility string.")
    allowed_tools: list[str] | None = Field(default=None, description="Optional replacement for allowed_tools.")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional replacement for metadata.")
    file_edits: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Per-file find/replace edits. Each entry: {path, edits: [{old, new}, ...]}. "
            "Files not mentioned are carried forward unchanged. Cannot add, remove, or rename files."
        ),
    )


class ArchiveSkillArgs(BaseModel):
    skill_name: str = Field(description="The kebab-case name of the skill to archive.")


def _format_skill_summary(skill: LLMSkill) -> str:
    description = (skill.description or "").strip() or "(no description)"
    return f"- {skill.name} (v{skill.version}): {description}"


def _format_skill_detail(skill: LLMSkill, files: list[LLMSkillFile]) -> str:
    lines = [
        f"# {skill.name} (v{skill.version})",
        "",
        f"Description: {skill.description}",
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
    if files:
        lines.append("Bundled files (use `get_llm_skill_file` to load content):")
        for skill_file in files:
            lines.append(f"  - {skill_file.path} ({skill_file.content_type})")
    else:
        lines.append("Bundled files: (none)")
    lines.append("")
    lines.append("--- BODY ---")
    lines.append(skill.body or "")
    return "\n".join(lines)


def _publish_error_message(err: Exception, skill_name: str) -> str:
    if isinstance(err, LLMSkillNotFoundError):
        return f"Skill '{skill_name}' was not found. Use `list_llm_skills` to discover available skills."
    if isinstance(err, LLMSkillVersionConflictError):
        return (
            f"Skill '{skill_name}' was modified by another writer (current version: {err.current_version}). "
            "Refetch with `get_llm_skill` and retry the update with the new base_version."
        )
    if isinstance(err, LLMSkillVersionLimitError):
        return (
            f"Skill '{skill_name}' has reached the maximum of {err.max_version} versions. "
            "Archive and recreate the skill to continue publishing."
        )
    if isinstance(err, LLMSkillFileLimitError):
        return f"Skill '{skill_name}' has reached the maximum of {err.max_count} bundled files."
    if isinstance(err, LLMSkillEditError):
        detail = err.message
        if err.edit_index is not None:
            detail = f"{detail} (edit index: {err.edit_index})"
        if err.file_path is not None:
            detail = f"{detail} (file: {err.file_path})"
        return detail
    return str(err)


class ListLLMSkillsTool(MaxTool):
    name: str = AssistantTool.LIST_LLM_SKILLS.value
    description: str = LIST_SKILLS_DESCRIPTION
    args_schema: type[BaseModel] = ListSkillsArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "viewer")]

    async def _arun_impl(self, search: str | None = None) -> tuple[str, None]:
        skills = await database_sync_to_async(self._list_skills)(search)
        if not skills:
            empty_msg = "No shared skills are stored for this team yet."
            if search:
                empty_msg = f"No shared skills matched the search query '{search}'."
            return empty_msg, None

        truncated = len(skills) > MAX_LIST_RESULTS
        visible = skills[:MAX_LIST_RESULTS]
        lines = [f"Found {len(visible)} skill(s):", ""]
        lines.extend(_format_skill_summary(s) for s in visible)
        if truncated:
            lines.append("")
            lines.append(
                f"(Truncated to {MAX_LIST_RESULTS} results — pass a `search` term to narrow the list if needed.)"
            )
        return "\n".join(lines), None

    def _list_skills(self, search: str | None) -> list[LLMSkill]:
        queryset = get_latest_skills_queryset(self._team)
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        # Fetch one extra row so we can distinguish "exactly at the cap" from "truncated".
        return list(queryset.order_by("name")[: MAX_LIST_RESULTS + 1])


class GetLLMSkillTool(MaxTool):
    name: str = AssistantTool.GET_LLM_SKILL.value
    description: str = GET_SKILL_DESCRIPTION
    args_schema: type[BaseModel] = GetSkillArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "viewer")]

    async def _arun_impl(self, skill_name: str, version: int | None = None) -> tuple[str, None]:
        skill, files = await database_sync_to_async(self._fetch_skill_with_files)(skill_name, version)
        if skill is None:
            return (
                f"Skill '{skill_name}' was not found. Use `list_llm_skills` to discover available skills.",
                None,
            )
        return _format_skill_detail(skill, files), None

    def _fetch_skill_with_files(
        self, skill_name: str, version: int | None
    ) -> tuple[LLMSkill | None, list[LLMSkillFile]]:
        skill = get_skill_by_name_from_db(self._team, skill_name, version)
        if skill is None:
            return None, []
        files = list(LLMSkillFile.objects.filter(skill=skill).order_by("path"))
        return skill, files


class GetLLMSkillFileTool(MaxTool):
    name: str = AssistantTool.GET_LLM_SKILL_FILE.value
    description: str = GET_SKILL_FILE_DESCRIPTION
    args_schema: type[BaseModel] = GetSkillFileArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "viewer")]

    async def _arun_impl(
        self,
        skill_name: str,
        file_path: str,
        version: int | None = None,
    ) -> tuple[str, None]:
        # Normalize so that `scripts/../foo.py` collapses to `foo.py` before we filter on the
        # exact stored path — the DB lookup itself only matches literal strings, so the guard
        # has to do the work of resolving `..` segments rather than just checking for them.
        cleaned = file_path.replace("\\", "/").rstrip("/")
        if not cleaned:
            return f"Invalid file path '{file_path}'.", None
        normalized = posixpath.normpath(cleaned)
        if posixpath.isabs(normalized) or normalized == ".." or normalized.startswith("../"):
            return f"Invalid file path '{file_path}'.", None

        skill_file = await database_sync_to_async(self._fetch_skill_file)(skill_name, normalized, version)
        if skill_file is None:
            return (
                f"File '{file_path}' was not found in skill '{skill_name}'. "
                "Fetch the skill again with `get_llm_skill` to refresh the file manifest.",
                None,
            )

        return (
            f"# {skill_name} / {skill_file.path}\nContent-Type: {skill_file.content_type}\n\n{skill_file.content}",
            None,
        )

    def _fetch_skill_file(self, skill_name: str, file_path: str, version: int | None) -> LLMSkillFile | None:
        skill = get_skill_by_name_from_db(self._team, skill_name, version)
        if skill is None:
            return None
        return LLMSkillFile.objects.filter(skill=skill, path=file_path).first()


class CreateLLMSkillTool(MaxTool):
    name: str = AssistantTool.CREATE_LLM_SKILL.value
    description: str = CREATE_SKILL_DESCRIPTION
    args_schema: type[BaseModel] = CreateSkillArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "editor")]

    async def _arun_impl(
        self,
        name: str,
        description: str,
        body: str,
        license: str | None = None,
        compatibility: str | None = None,
        allowed_tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        files: list[dict[str, str]] | None = None,
    ) -> tuple[str, None]:
        try:
            skill = await database_sync_to_async(create_skill)(
                self._team,
                user=self._user,
                name=name,
                description=description,
                body=body,
                license=license,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                metadata=metadata,
                files=files,
            )
        except LLMSkillDuplicateNameConflictError:
            raise MaxToolFatalError(f"A skill named '{name}' already exists.")
        except LLMSkillFilePathConflictError:
            raise MaxToolFatalError("Duplicate file paths are not allowed in `files`.")
        except LLMSkillFileLimitError as err:
            raise MaxToolFatalError(f"Cannot attach more than {err.max_count} bundled files to a skill.")

        return (
            f"Created skill '{skill.name}' at v{skill.version}. It is now discoverable via `list_llm_skills`.",
            None,
        )


class UpdateLLMSkillTool(MaxTool):
    name: str = AssistantTool.UPDATE_LLM_SKILL.value
    description: str = UPDATE_SKILL_DESCRIPTION
    args_schema: type[BaseModel] = UpdateSkillArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "editor")]

    async def _arun_impl(
        self,
        skill_name: str,
        base_version: int,
        body: str | None = None,
        edits: list[dict[str, str]] | None = None,
        description: str | None = None,
        license: str | None = None,
        compatibility: str | None = None,
        allowed_tools: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        file_edits: list[dict[str, Any]] | None = None,
    ) -> tuple[str, None]:
        if body is not None and edits is not None:
            raise MaxToolFatalError("Pass either `body` or `edits`, not both.")

        try:
            skill = await database_sync_to_async(publish_skill_version)(
                self._team,
                user=self._user,
                skill_name=skill_name,
                body=body,
                edits=edits,
                description=description,
                license=license,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                metadata=metadata,
                files=None,
                file_edits=file_edits,
                base_version=base_version,
            )
        except (
            LLMSkillNotFoundError,
            LLMSkillVersionConflictError,
            LLMSkillVersionLimitError,
            LLMSkillFileLimitError,
            LLMSkillEditError,
        ) as err:
            raise MaxToolFatalError(_publish_error_message(err, skill_name))

        return f"Updated skill '{skill.name}' — new version v{skill.version}.", None


class ArchiveLLMSkillTool(MaxTool):
    name: str = AssistantTool.ARCHIVE_LLM_SKILL.value
    description: str = ARCHIVE_SKILL_DESCRIPTION
    args_schema: type[BaseModel] = ArchiveSkillArgs

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("llm_skill", "editor")]

    async def _arun_impl(self, skill_name: str) -> tuple[str, None]:
        try:
            versions = await database_sync_to_async(archive_skill)(self._team, skill_name)
        except LLMSkillNotFoundError:
            raise MaxToolFatalError(
                f"Skill '{skill_name}' was not found. Use `list_llm_skills` to discover available skills."
            )

        return (
            f"Archived skill '{skill_name}' ({len(versions)} version(s) hidden). This cannot be undone.",
            None,
        )
