"""Spec-compliant SKILL.md serialization and marketplace/zip file-tree assembly.

The single source of truth for turning a skill into Agent Skills spec artifacts
(https://agentskills.io/specification). Three consumers share this core:

- zip export (per-skill ``SKILL.md`` + bundled files)
- the live plugin marketplace (synthesized git repo, served over Smart HTTP)
- plain-HTTP marketplace file serving

It is Django-free on purpose — it operates on the plain dataclasses below, so a thin
model adapter (see ``adapters.py``) is the only place that touches the ORM. That keeps
the spec serialization and tree assembly unit-testable without booting the app.
"""

import io
import re
import json
import zipfile
import mimetypes
from dataclasses import dataclass, field

import yaml

from .git_smart_http import FileTree

# Spec caps (https://agentskills.io/specification). Description is 1024 in the spec
# but stored at 4096 today — export validates rather than silently truncating.
SPEC_DESCRIPTION_MAX_LENGTH = 1024

# Zip-bomb defense for import: bound member count and per-member *decompressed* read so a small
# zip can't inflate into GBs of memory. These are coarse hard stops — the precise per-field/per-file
# size caps are enforced downstream by the import validator. Kept comfortably above legit limits
# (a SKILL.md body / bundled file is capped at ~1 MB each, ≤50 files).
_MAX_ZIP_MEMBERS = 200
_MAX_ZIP_MEMBER_BYTES = 2_000_000
_MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 80_000_000

# Matches a leading YAML frontmatter block: ``---`` line, body until a closing ``---`` line.
_FRONTMATTER_RE = re.compile(r"\A---[^\n]*\n(.*?)\n---[^\n]*\n?(.*)\Z", re.DOTALL)


class SkillImportError(Exception):
    """Raised when an uploaded zip / SKILL.md can't be parsed into a skill."""


@dataclass(frozen=True)
class SkillFileExport:
    path: str
    content: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class SkillExport:
    name: str
    description: str
    body: str
    version: int
    license: str = ""
    compatibility: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    files: list[SkillFileExport] = field(default_factory=list)


def render_frontmatter(skill: SkillExport) -> str:
    """Serialize a skill's spec fields as a YAML frontmatter block (with delimiters).

    Maps storage shape -> spec shape: ``allowed_tools`` (list) becomes the spec's
    hyphenated, space-separated ``allowed-tools`` string, and the platform ``version``
    is parked under ``metadata`` since the spec defines no top-level version field.
    """
    document: dict[str, object] = {"name": skill.name, "description": skill.description}
    if skill.license:
        document["license"] = skill.license
    if skill.compatibility:
        document["compatibility"] = skill.compatibility

    # Spec metadata is a string->string map. Stored metadata first, then the platform version
    # last so it always wins — a user-stored metadata["version"] must not clobber the real one.
    metadata: dict[str, str] = {str(k): str(v) for k, v in skill.metadata.items()}
    metadata["version"] = str(skill.version)
    document["metadata"] = metadata

    if skill.allowed_tools:
        document["allowed-tools"] = " ".join(skill.allowed_tools)

    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def render_skill_md(skill: SkillExport) -> str:
    return render_frontmatter(skill) + "\n" + skill.body


def validate_for_export(skill: SkillExport) -> list[str]:
    """Return spec-compliance problems that should block or warn on export. Empty == clean."""
    problems: list[str] = []
    if len(skill.description) > SPEC_DESCRIPTION_MAX_LENGTH:
        problems.append(
            f"description is {len(skill.description)} characters; the spec maximum is {SPEC_DESCRIPTION_MAX_LENGTH}"
        )
    if not skill.description.strip():
        problems.append("description is required and must be non-empty")
    return problems


# OpenAI Codex reads this optional sidecar for UI metadata + tool deps; every other agent
# ignores it. Generated into the tree so the same artifact is first-class in Codex too.
CODEX_METADATA_PATH = "agents/openai.yaml"


def _humanize_skill_name(name: str) -> str:
    spaced = name.replace("-", " ").strip()
    return spaced[:1].upper() + spaced[1:] if spaced else name


def render_codex_openai_yaml(skill: SkillExport) -> str:
    """Codex's ``agents/openai.yaml`` — UI metadata derived from the skill's spec fields."""
    document = {
        "interface": {
            "display_name": _humanize_skill_name(skill.name),
            "short_description": skill.description,
        }
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)


def build_skill_tree(skill: SkillExport) -> FileTree:
    """Files for one skill relative to its own root: ``SKILL.md`` + Codex sidecar + bundled files.

    The bundled file ``path`` already encodes its ``scripts/`` / ``references/`` /
    ``assets/`` subdirectory, so it maps straight through.
    """
    tree: FileTree = {
        "SKILL.md": render_skill_md(skill),
        # Generated first so a user-bundled file at the same path overrides it below.
        CODEX_METADATA_PATH: render_codex_openai_yaml(skill),
    }
    for skill_file in skill.files:
        tree[skill_file.path] = skill_file.content
    return tree


def build_skill_zip(skill: SkillExport) -> bytes:
    """A spec-compliant skill directory zipped under a top-level folder named after the skill.

    The ``<name>/`` top directory satisfies the spec's "name must match the parent
    directory" rule for the unpacked result.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel_path, content in build_skill_tree(skill).items():
            archive.writestr(f"{skill.name}/{rel_path}", content)
    return buffer.getvalue()


def parse_skill_md(content: str) -> dict:
    """Parse a SKILL.md string into spec fields (inverse of ``render_skill_md``).

    Returns the frontmatter fields mapped to storage shape (``allowed-tools`` space-string ->
    list, the platform-owned ``metadata.version`` dropped) plus the markdown ``body``.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise SkillImportError("SKILL.md is missing its YAML frontmatter block.")
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as err:
        raise SkillImportError(f"SKILL.md frontmatter is not valid YAML: {err}")
    if not isinstance(frontmatter, dict):
        raise SkillImportError("SKILL.md frontmatter must be a key/value mapping.")

    name = frontmatter.get("name")
    if not name or not isinstance(name, str):
        raise SkillImportError("SKILL.md frontmatter is missing a 'name'.")

    body = match.group(2)
    if body.startswith("\n"):  # render_skill_md joins frontmatter and body with a single newline
        body = body[1:]

    raw_metadata = frontmatter.get("metadata")
    metadata = (
        {str(k): str(v) for k, v in raw_metadata.items() if str(k) != "version"}
        if isinstance(raw_metadata, dict)
        else {}
    )
    allowed = frontmatter.get("allowed-tools", "")
    allowed_tools = allowed.split() if isinstance(allowed, str) else [str(x) for x in (allowed or [])]

    return {
        "name": name,
        "description": str(frontmatter.get("description") or ""),
        "license": str(frontmatter.get("license") or ""),
        "compatibility": str(frontmatter.get("compatibility") or ""),
        "metadata": metadata,
        "allowed_tools": allowed_tools,
        "body": body,
    }


def parse_skill_zip(data: bytes) -> SkillExport:
    """Parse a spec-compliant skill zip (the inverse of ``build_skill_zip``) into a SkillExport.

    Finds the single ``SKILL.md`` (at the zip root or one directory deep), parses its frontmatter,
    and collects sibling files under the same directory as bundled files (content type guessed
    from the path). Text (UTF-8) content only — bundled files are stored as text.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SkillImportError("The uploaded file is not a valid zip archive.")

    with archive:
        infos = archive.infolist()
        # Reject zip-bombs up front using the archive's declared sizes (no decompression yet):
        # too many members, or a total uncompressed size that would blow up memory.
        if len(infos) > _MAX_ZIP_MEMBERS:
            raise SkillImportError(f"The zip contains too many files (max {_MAX_ZIP_MEMBERS}).")
        if sum(info.file_size for info in infos) > _MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
            raise SkillImportError("The zip's uncompressed contents are too large.")

        members = [n for n in archive.namelist() if not n.endswith("/")]
        skill_md_members = [n for n in members if n.rsplit("/", 1)[-1] == "SKILL.md"]
        if not skill_md_members:
            raise SkillImportError("The zip does not contain a SKILL.md file.")
        if len(skill_md_members) > 1:
            raise SkillImportError("The zip contains multiple SKILL.md files; expected exactly one.")

        skill_md_name = skill_md_members[0]
        prefix = skill_md_name[: -len("SKILL.md")]  # "" (root) or "<dir>/"

        fields = parse_skill_md(_read_zip_text(archive, skill_md_name, "SKILL.md"))

        files: list[SkillFileExport] = []
        for member in members:
            if member == skill_md_name or not member.startswith(prefix):
                continue
            # Normalize backslashes to "/" so a zip member like `references\guide.md` becomes a
            # nested file, not a flat entry, matching how the write path stores bundled paths.
            rel_path = member[len(prefix) :].replace("\\", "/")
            if rel_path == CODEX_METADATA_PATH:
                continue  # generated Codex sidecar — regenerated on export, not a stored file
            content = _read_zip_text(archive, member, rel_path)
            content_type = mimetypes.guess_type(rel_path)[0] or "text/plain"
            files.append(SkillFileExport(path=rel_path, content=content, content_type=content_type))

    return SkillExport(version=1, files=files, **fields)


def _read_zip_text(archive: zipfile.ZipFile, member: str, label: str) -> str:
    # Bounded decompression: read one byte past the cap so an over-large (or size-spoofed,
    # decompress-bomb) member is rejected without materializing its full inflated content.
    with archive.open(member) as handle:
        raw = handle.read(_MAX_ZIP_MEMBER_BYTES + 1)
    if len(raw) > _MAX_ZIP_MEMBER_BYTES:
        raise SkillImportError(f"'{label}' is too large.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SkillImportError(f"'{label}' must be UTF-8 text; binary files are not supported.")


def compute_plugin_version(latest_change_epoch_millis: int) -> str:
    """Content-derived, monotonic plugin version so auto-update fires on any change.

    Keyed off the most recent change time (in epoch milliseconds) across all of a team's skill
    rows (see ``adapters._team_plugin_version``): publishes and file edits add/refresh a row's
    ``updated_at``, and archive bumps it too, so this advances on every change and never
    regresses. Millisecond resolution keeps two edits within the same second distinct. Whether
    Claude Code re-pulls on any version *difference* vs. strictly-greater is the open question
    the auto-update spike answers — this scheme is safe for either.
    """
    return f"1.0.{latest_change_epoch_millis}"


def build_marketplace_tree(
    *,
    plugin_name: str,
    plugin_description: str,
    plugin_version: str,
    owner_name: str,
    marketplace_name: str,
    skills: list[SkillExport],
) -> FileTree:
    """Assemble the full Claude Code plugin-marketplace file tree for one plugin.

    Layout (skills are auto-discovered from the ``skills/`` directory; we don't emit an
    explicit skills array, matching the known-working reference implementation)::

        .claude-plugin/marketplace.json
        plugins/<plugin>/.claude-plugin/plugin.json
        plugins/<plugin>/skills/<name>/SKILL.md
        plugins/<plugin>/skills/<name>/<bundled file path>
    """
    tree: FileTree = {}

    tree[".claude-plugin/marketplace.json"] = json.dumps(
        {
            "name": marketplace_name,
            "owner": {"name": owner_name},
            "plugins": [
                {
                    "name": plugin_name,
                    "source": f"./plugins/{plugin_name}",
                    "description": plugin_description,
                    "version": plugin_version,
                }
            ],
        },
        indent=2,
    )

    prefix = f"plugins/{plugin_name}"
    tree[f"{prefix}/.claude-plugin/plugin.json"] = json.dumps(
        {"name": plugin_name, "version": plugin_version, "description": plugin_description},
        indent=2,
    )

    for skill in skills:
        skill_prefix = f"{prefix}/skills/{skill.name}"
        for rel_path, content in build_skill_tree(skill).items():
            tree[f"{skill_prefix}/{rel_path}"] = content

    return tree
