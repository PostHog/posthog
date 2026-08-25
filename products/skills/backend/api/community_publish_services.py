"""Publish a team's LLMSkill to the PostHog/community-skills repo as a pull request.

The heavy lifting (branch + commit + PR) reuses the existing `GitHubIntegration` that already
powers the Tasks product. This module owns the pure rendering of an `LLMSkill` into the repo's
`skills/<slug>/SKILL.md` layout; the GitHub side lives in `publish_skill_to_community`.
"""

from __future__ import annotations

import re
import json
import time
import hashlib
from typing import Any

from django.conf import settings

import jwt
import yaml
import requests
import structlog

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError, github_request
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

from ..marketplace.packaging import SPEC_DESCRIPTION_MAX_LENGTH
from .skill_services import (
    MAX_SKILL_BODY_BYTES,
    MAX_SKILL_FILE_BYTES,
    MAX_SKILL_FILE_COUNT,
    RESERVED_SKILL_NAMES,
    SKILL_NAME_PATTERN,
    check_allowed_tool_name,
    normalize_skill_file_path,
)

logger = structlog.get_logger(__name__)

# Per-subsystem attribution on the shared GitHub egress metrics.
_EGRESS_SOURCE = "community_skills"

MAX_SLUG_LENGTH = 64
# GitHub caps one create-tree request at 7 MB, and commit_files_to_branch inlines every file's
# content in that single request, so a skill above the cap can only ever fail with a 502. Measured
# against the escaped form the request actually carries, and held under the cap for the frontmatter,
# paths and envelope that ride along with it.
MAX_PUBLISH_TREE_BYTES = 5_000_000
# GitHub usernames are alphanumeric with single inner hyphens, up to 39 characters. The handle is
# self-reported and lands in a public PR body and in the listing, so hold it to the shape of a real
# username rather than letting free text through. The pattern alone can't bound the total, since each
# repetition may contribute a hyphen and a character, so the length is checked beside it.
MAX_GITHUB_HANDLE_LENGTH = 39
GITHUB_HANDLE_PATTERN = re.compile(r"^[a-zA-Z0-9](?:-?[a-zA-Z0-9]){0,38}$")
# The API field is optional, so the shape it publishes to clients has to accept an empty string too —
# otherwise generated validators reject the blank the endpoint itself allows.
OPTIONAL_GITHUB_HANDLE_PATTERN = re.compile(f"^$|{GITHUB_HANDLE_PATTERN.pattern}")
# Matches CommunitySkill.name — a longer name publishes and merges, then ingest rejects the entry and
# the skill silently never appears in the catalog.
MAX_DISPLAY_NAME_LENGTH = 64
# The display name is interpolated into the App-authored commit message, the pull request title and
# its Markdown body. A newline in it can forge a commit trailer, so `Co-authored-by:` would make
# GitHub attribute our App's commit to an unrelated account. Hold the name to one printable line.
DISPLAY_NAME_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]*$")
MAX_TAG_LENGTH = 64
SKILLS_DIR = "skills"
# The subtree one publish owns. Rewritten whole on every publish, so a file dropped from the skill
# stops being published rather than surviving on the branch the previous publish left it on.
SKILL_TREE_MODE = "040000"
COMMUNITY_SKILLS_PR_BASE_BRANCH = "main"
COMMUNITY_SKILLS_BRANCH_PREFIX = "community-skill/"


class CommunitySkillPublishError(Exception):
    """Raised when a skill can't be rendered or published to the community repo."""


class CommunitySkillPublishNotConfiguredError(CommunitySkillPublishError):
    """Raised when the community-skills GitHub App installation isn't configured on this instance."""


class CommunitySkillPublishValidationError(CommunitySkillPublishError):
    """Raised when the skill itself can't be published, before anything is written to GitHub.

    Split from the GitHub failures the base class also carries because the two need opposite advice:
    this one is fixed by editing the skill, and republishing it unchanged fails the same way, so the
    endpoint answers it 400 rather than the 502 it answers an unreachable GitHub with.
    """


class _CommunitySkillsPublisher(GitHubIntegration):
    """Publisher client whose Integration row is transient and belongs to no team.

    A fresh installation token is minted for every publish, so a 401 is a real failure rather than an
    expiry to heal — and the inherited refresh would try to save a teamless row, which the model's
    team foreign key forbids.
    """

    def refresh_access_token(self) -> None:
        raise GitHubIntegrationError("The community-skills publisher mints a token per publish and cannot refresh.")


@frozen
class RenderedFile:
    """A single file to commit, at its path within the community-skills repo."""

    path: str
    content: str


def publishable_tags(tags: object) -> list[str]:
    """Keep only the entries of a skill's stored tags that the catalog can actually accept.

    `LLMSkill.metadata` is an arbitrary dict, so its `tags` can hold any JSON, while ingest requires
    every tag to be a string within the catalog's cap and drops the whole entry otherwise. Publishing
    the unusable ones would open a pull request that merges and then never appears in the catalog.
    """
    if not isinstance(tags, list):
        return []
    # Stripped, like the serializer's own CharField already gives us for request-supplied tags. Sync
    # only lowercases a tag, and catalog filtering matches it exactly, so a stored `" github "` would
    # publish as a tag no filter can ever select.
    stripped = (tag.strip() for tag in tags if isinstance(tag, str))
    return [tag for tag in stripped if tag and len(tag) <= MAX_TAG_LENGTH]


def publisher_branch_key(publisher_id: str) -> str:
    """Short, stable, opaque branch suffix for one publisher.

    Skill slugs are only unique within a team, but a branch name is global to the community repo, so a
    slug alone would let one team's publish force-update another team's open pull request. Hashing
    keeps the publisher's identifier out of a public branch name.
    """
    return hashlib.sha256(publisher_id.encode()).hexdigest()[:8]


def _validate_slug(slug: str) -> str:
    # The same rule community_skill_sync._validate_entry_shape applies to a registry entry, so a slug
    # that would be dropped on ingest is refused here instead of merging into a catalog that skips
    # it. fullmatch, not match: `$` also matches before a trailing newline.
    if not SKILL_NAME_PATTERN.fullmatch(slug) or "--" in slug or len(slug) > MAX_SLUG_LENGTH:
        raise CommunitySkillPublishValidationError(
            f"'{slug}' is not a valid community skill slug (lowercase letters, numbers, single hyphens)."
        )
    if slug.lower() in RESERVED_SKILL_NAMES:
        raise CommunitySkillPublishValidationError(
            f"'{slug}' is a reserved name and can't be published to the community."
        )
    return slug


def _validate_allowed_tool(tool: object) -> None:
    """Hold one allowed-tool name to the rule ingest applies to a registry entry.

    `create_skill` writes what a tool call passed straight to the model, without the REST
    serializer's `validate_allowed_tool`, and `allowed_tools` is a JSONField, so a stored
    `"Bash Write"` (or a non-string) renders into frontmatter that
    community_skill_sync._validate_entry_shape rejects: the pull request merges and the skill never
    appears in the catalog.
    """
    if not isinstance(tool, str):
        raise CommunitySkillPublishValidationError("Allowed tools must be a list of tool names.")
    try:
        check_allowed_tool_name(tool)
    except ValueError as err:
        raise CommunitySkillPublishValidationError(f"'{tool}' can't be published as a tool name. {err}") from err


def render_skill_md(
    *,
    name: str,
    description: str,
    body: str,
    tags: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    license: str = "",
    compatibility: str = "",
    author_handle: str = "",
) -> str:
    """Render an LLMSkill's fields into community-skills `SKILL.md` content (frontmatter + body).

    Output parses cleanly under the repo's `build_registry.py` frontmatter regex and field rules:
    `name` and `description` are required; `trust_tier` defaults to `community` (maintainers set
    `official`/`verified` on review); optional fields are omitted when empty.
    """
    if not name.strip():
        raise CommunitySkillPublishValidationError("Skill name is required to publish.")
    if len(name.strip()) > MAX_DISPLAY_NAME_LENGTH:
        raise CommunitySkillPublishValidationError(f"Skill name must be {MAX_DISPLAY_NAME_LENGTH} characters or fewer.")
    if not DISPLAY_NAME_PATTERN.match(name.strip()):
        raise CommunitySkillPublishValidationError("Skill name must be one line, with no line breaks.")
    if not description.strip():
        raise CommunitySkillPublishValidationError("Skill description is required to publish.")
    # LLMSkill.description holds 4096, and the Agent Skills spec stops at 1024. A longer one
    # publishes, syncs and installs, and then validate_for_export refuses the installed skill, so the
    # publisher hands someone a skill they can never export.
    if len(description.strip()) > SPEC_DESCRIPTION_MAX_LENGTH:
        raise CommunitySkillPublishValidationError(
            f"Skill description must be {SPEC_DESCRIPTION_MAX_LENGTH} characters or fewer to publish."
        )
    # The same rule install_community_skill applies on the way back in, where a blank body is refused
    # as having no instructions. Without it the publish succeeds, the entry merges into the catalog,
    # and the listing is one nobody can install.
    if not body.strip():
        raise CommunitySkillPublishValidationError("Skill instructions are required to publish.")
    if author_handle.strip() and (
        len(author_handle.strip()) > MAX_GITHUB_HANDLE_LENGTH or not GITHUB_HANDLE_PATTERN.match(author_handle.strip())
    ):
        raise CommunitySkillPublishValidationError(f"'{author_handle}' is not a valid GitHub username.")
    for tool in allowed_tools or []:
        _validate_allowed_tool(tool)

    frontmatter: dict[str, Any] = {
        "name": name.strip(),
        "description": description.strip(),
        "trust_tier": "community",
    }
    if tags:
        frontmatter["tags"] = list(tags)
    if author_handle.strip():
        frontmatter["author_handle"] = author_handle.strip()
    if license.strip():
        frontmatter["license"] = license.strip()
    if compatibility.strip():
        frontmatter["compatibility"] = compatibility.strip()
    if allowed_tools:
        frontmatter["allowed_tools"] = list(allowed_tools)

    # sort_keys=False keeps the human-friendly field order above; default_flow_style=False emits
    # block-style YAML (lists as `- item`) that the repo's yaml.safe_load round-trips.
    rendered_frontmatter = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False, allow_unicode=True)
    # rstrip, not strip: leading whitespace is content. A body that opens with an indented code block
    # becomes an ordinary paragraph once it's trimmed, so the published skill would instruct
    # differently from the skill it was published from.
    return f"---\n{rendered_frontmatter}---\n\n{body.rstrip()}\n"


def render_community_skill_files(
    *,
    slug: str,
    name: str,
    description: str,
    body: str,
    files: list[dict[str, str]] | None = None,
    tags: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    license: str = "",
    compatibility: str = "",
    author_handle: str = "",
) -> list[RenderedFile]:
    """Render the full set of files to commit for a skill: SKILL.md plus any bundled files.

    Bundled files keep their skill-relative path under `skills/<slug>/` (e.g. a skill file at
    `references/playbook.md` becomes `skills/<slug>/references/playbook.md`).
    """
    _validate_slug(slug)
    _validate_entry_caps(body=body, files=files or [])
    skill_root = f"{SKILLS_DIR}/{slug}"

    rendered: list[RenderedFile] = [
        RenderedFile(
            path=f"{skill_root}/SKILL.md",
            content=render_skill_md(
                name=name,
                description=description,
                body=body,
                tags=tags,
                allowed_tools=allowed_tools,
                license=license,
                compatibility=compatibility,
                author_handle=author_handle,
            ),
        )
    ]

    seen_paths = {rendered[0].path.lower()}
    for file in files or []:
        # Canonical and confined to the skill directory, by the same rule ingest applies. A bundled
        # file must never escape skills/<slug>/, and `create_skill` stores a tool-supplied path
        # verbatim, so `references\guide.md` and `references/guide.md` arrive here as two distinct
        # paths that community_skill_sync._validate_entry_within_caps then folds into one and
        # rejects as a duplicate: the pull request merges and the skill never appears in the catalog.
        rel_path = _publishable_file_path(file["path"])
        path = f"{skill_root}/{rel_path}"
        # Case-insensitive, matching community_skill_sync._validate_entry_within_caps: two paths
        # differing only by case pass every check on this side, and then ingest rejects the whole
        # entry, so the pull request merges and the skill never appears in the catalog. Seeding the
        # set with SKILL.md is also what stops a bundled file from overwriting the rendered one.
        if path.lower() in seen_paths:
            raise CommunitySkillPublishValidationError(f"Duplicate bundled file path '{file['path']}'.")
        seen_paths.add(path.lower())
        rendered.append(RenderedFile(path=path, content=file["content"]))

    _reject_blob_directory_collisions(seen_paths)
    _validate_publishable_tree_size(rendered)
    return rendered


def _publishable_file_path(raw_path: str) -> str:
    try:
        return normalize_skill_file_path(raw_path)
    except ValueError as err:
        raise CommunitySkillPublishValidationError(f"'{raw_path}' can't be published as a file path. {err}") from err


def _encoded_payload_bytes(content: str) -> int:
    """Size this content adds to the one create-tree request GitHub caps at 7 MB.

    What counts against that cap is the escaped form, because commit_files_to_branch inlines every
    file's content in a single JSON body: a newline costs two bytes there and one here, and a control
    character costs six. Counting raw bytes instead lets a body of newlines clear a 5 MB check and
    still blow the limit, which fails the publish with a 502 nobody can act on. `json.dumps` defaults
    match what `requests` serializes the body with, escaping included.
    """
    return len(json.dumps(content).encode("utf-8"))


def _validate_entry_caps(*, body: str, files: list[dict[str, str]]) -> None:
    """Hold a publish to ingest's own per-entry caps, which it measures on the stored bytes.

    These are `community_skill_sync._validate_entry_within_caps`, where breaching one drops the whole
    entry: the pull request merges and the skill never appears in the catalog. The file count is
    checked here rather than after rendering so an absurd manifest never gets rendered at all.
    """
    if len(body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise CommunitySkillPublishValidationError(
            f"The skill body must be under {MAX_SKILL_BODY_BYTES // 1_000_000} MB."
        )
    if len(files) > MAX_SKILL_FILE_COUNT:
        raise CommunitySkillPublishValidationError(f"A skill can publish at most {MAX_SKILL_FILE_COUNT} files.")
    for file in files:
        if len(file["content"].encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise CommunitySkillPublishValidationError(
                f"'{file['path']}' must be under {MAX_SKILL_FILE_BYTES // 1_000_000} MB."
            )


def _validate_publishable_tree_size(rendered: list[RenderedFile]) -> None:
    """Hold the whole manifest to GitHub's cap on the create-tree request that writes it.

    Measured on what is actually sent, which is why it runs on the rendered files rather than the
    fields they came from: SKILL.md carries frontmatter as well as the body, and neither the tag list
    nor `allowed_tools` has a count cap, so the difference is not a rounding error. Breaching the cap
    fails the write with a 502 nobody can act on.
    """
    total = sum(_encoded_payload_bytes(file.content) + len(file.path.encode("utf-8")) for file in rendered)
    if total > MAX_PUBLISH_TREE_BYTES:
        raise CommunitySkillPublishValidationError(
            f"This skill is too large to publish. Trim it to under "
            f"{MAX_PUBLISH_TREE_BYTES // 1_000_000} MB of body and files, then publish again."
        )


def _reject_blob_directory_collisions(paths: set[str]) -> None:
    """Refuse a manifest where one path is a file and also a directory in another path.

    A git tree can't hold `references` as both a blob and a tree, so GitHub rejects the whole tree
    and the skill can't be published at all. Saying which path collides beats the API's error.
    """
    directories = {parent for path in paths for parent in _parent_directories(path)}
    collisions = sorted(directories & paths)
    if collisions:
        raise CommunitySkillPublishValidationError(
            f"'{collisions[0].split('/', 2)[-1]}' is used as both a file and a folder. Rename one of them."
        )


def _parent_directories(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


# The publish only writes files and opens a pull request, in one repository. An unscoped mint would
# hand this transient token every repository and every optional permission the installation holds, so
# it is requested down to what a publish uses. A permission the installation lacks fails the mint,
# which is the same 502 an unusable installation would produce on the first write anyway.
PUBLISHER_TOKEN_PERMISSIONS = {"contents": "write", "pull_requests": "write", "metadata": "read"}
# Statuses that mean the App isn't installed here or its credentials are rejected: unauthenticated,
# not permitted, or no such installation. Rate limits never reach this set — the transport raises
# them, including the 403 spellings.
PUBLISHER_NOT_CONFIGURED_STATUSES = frozenset({401, 403, 404})


def _publisher_token_request_body() -> dict[str, Any]:
    # The `repositories` field takes bare names; the setting is normally one already, but accept an
    # `owner/repo` spelling rather than scoping the token to a repository that doesn't exist.
    repo = (settings.COMMUNITY_SKILLS_GITHUB_REPO or "").split("/")[-1]
    body: dict[str, Any] = {"permissions": dict(PUBLISHER_TOKEN_PERMISSIONS)}
    if repo:
        body["repositories"] = [repo]
    return body


def _publisher_app_jwt() -> str | None:
    """Sign a short-lived App JWT for the dedicated community-skills publisher App, or None.

    ``iat`` is backdated to tolerate clock skew against GitHub, and ``exp`` stays inside GitHub's
    10-minute maximum. Returns None when the App is unconfigured, and also when its private key
    cannot sign: a key GitHub would reject is a deployment nobody can retry their way out of, so it
    has to read as "this instance cannot publish" rather than as a GitHub outage.
    """
    client_id = settings.COMMUNITY_SKILLS_GITHUB_APP_CLIENT_ID
    private_key = settings.COMMUNITY_SKILLS_GITHUB_APP_PRIVATE_KEY
    if not client_id or not private_key:
        return None

    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(client_id)},
            # Environment variables commonly carry the PEM with its newlines escaped.
            private_key.replace("\\n", "\n").strip(),
            algorithm="RS256",
        )
    except Exception:
        logger.error("community_skills_publisher_key_unusable", exc_info=True)
        return None


def _publisher_app_request(
    path: str,
    *,
    app_jwt: str,
    telemetry_endpoint: str,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    """Call the GitHub App API as the publisher App, through the shared egress transport.

    Identity-blind on purpose: App-JWT calls are metered per App rather than per installation, so
    there is no installation budget to gate them under, but volume telemetry still counts.
    """
    return github_request(
        method,
        f"https://api.github.com/app/{path}",
        source=_EGRESS_SOURCE,
        headers={"Authorization": f"Bearer {app_jwt}"},
        endpoint=telemetry_endpoint,
        timeout=10,
        # requests omits the body entirely when json is None
        json=json_body,
    )


def get_community_skills_publisher() -> GitHubIntegration | None:
    """Build a GitHubIntegration bound to the central community-skills installation, or None.

    Mints a fresh installation token from the dedicated publisher App, downscoped to the publish
    repository and the permissions a publish needs, and wraps it in a transient, unsaved Integration,
    because we never persist a teamless central row. Returns None when that App or its
    community-skills installation isn't configured, so callers can surface a clean "not configured"
    error instead of failing.

    Raises CommunitySkillPublishError when GitHub can't be reached to mint the token: an outage here
    is the same failure as an outage on the write that follows, and must not read as "not configured".
    """
    installation_id = settings.COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID
    app_jwt = _publisher_app_jwt()
    if not installation_id or app_jwt is None:
        return None

    try:
        info_response = _publisher_app_request(
            f"installations/{installation_id}",
            app_jwt=app_jwt,
            telemetry_endpoint="/app/installations/{installation_id}",
        )
        token_response = _publisher_app_request(
            f"installations/{installation_id}/access_tokens",
            app_jwt=app_jwt,
            telemetry_endpoint="/app/installations/{installation_id}/access_tokens",
            method="POST",
            json_body=_publisher_token_request_body(),
        )
    except (requests.RequestException, GitHubIntegrationError, GitHubRateLimitError) as err:
        # The transport hands a timeout back raw. Without this the publish path answers a GitHub
        # outage with an unhandled 500.
        logger.warning("community_skills_publisher_unreachable", exc_info=True)
        raise CommunitySkillPublishError(
            "Could not reach GitHub to publish this skill. Try again in a few minutes."
        ) from err

    failed_statuses = [
        response.status_code
        for response, expected in ((info_response, 200), (token_response, 201))
        if response.status_code != expected
    ]
    if failed_statuses:
        logger.warning(
            "community_skills_publisher_unavailable",
            info_status=info_response.status_code,
            token_status=token_response.status_code,
        )
        # A missing installation or App credentials GitHub refuses are settings nobody can retry
        # their way out of, which is the 503 this returns None for. Any other status is GitHub
        # failing a call we were entitled to make, and has to read as a gateway error instead —
        # answering a transient 500 with "not configured" sends the publisher to the manual path
        # for an outage that clears on its own.
        if all(status in PUBLISHER_NOT_CONFIGURED_STATUSES for status in failed_statuses):
            return None
        raise CommunitySkillPublishError("Could not reach GitHub to publish this skill. Try again in a few minutes.")

    account = info_response.json().get("account") or {}
    token = token_response.json().get("token")
    if not token or not account.get("login"):
        return None

    # Transient (never saved) Integration, left unattached to any team: the write helpers only read
    # the access token + account name and don't trigger a refresh/save, so this avoids polluting the
    # team-scoped Integration table.
    integration = Integration(
        kind="github",
        integration_id=str(installation_id),
        config={"account": {"name": account["login"], "type": account.get("type")}},
        sensitive_config={"access_token": token},
    )
    # The same source as the App-JWT calls above, so every publish request lands under one label.
    return _CommunitySkillsPublisher(integration, source=_EGRESS_SOURCE)


def _community_pr_body(*, name: str, slug: str, author_handle: str) -> str:
    # No PostHog user PII here — this PR is public. Attribution is only the GitHub handle the
    # publisher explicitly provided for public sharing.
    # The handle is self-reported, so say so: a maintainer must not read it as a verified identity.
    credit = (
        f"Published from the PostHog skills marketplace. The publisher gave @{author_handle} as the author handle"
        if author_handle
        else "Published from the PostHog skills marketplace"
    )
    return (
        f"Adds the **{name}** community skill (`skills/{slug}/`).\n\n"
        f"{credit} via the in-product *Publish to community* flow.\n\n"
        "A maintainer should review the instructions for safety before merging; "
        "set `trust_tier` on review. On merge, CI regenerates `registry.json` and PostHog syncs it."
    )


def publish_skill_to_community(
    *,
    slug: str,
    publisher_id: str,
    name: str,
    description: str,
    body: str,
    files: list[dict[str, str]] | None = None,
    tags: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    license: str = "",
    compatibility: str = "",
    author_handle: str = "",
) -> dict[str, Any]:
    """Open a PR in PostHog/community-skills adding (or updating) this skill. Returns the PR url/number.

    One open PR per skill per publisher: the branch is derived from the slug and ``publisher_id``, so
    re-publishing rewrites that branch and returns the pull request already open for it instead of
    opening a second one. Every file lands in a single commit, and a failure after the branch write
    deletes the branch again, since this repo is public and a half-written skill or an unreviewed
    branch must not survive a failed publish. A failure that may still have opened a pull request is
    reconciled against GitHub first, so cleanup can never remove a branch under live review.

    ``publisher_id`` identifies the publishing team and is required. Leaving the branch keyed on the
    slug alone would let one team's publish force-update another team's open pull request, because a
    skill slug is only unique within a team.

    Raises CommunitySkillPublishError when any GitHub step fails, or
    CommunitySkillPublishNotConfiguredError when publishing is disabled.
    """
    # Rendering is pure and deterministic, so it runs before the publisher is acquired: a skill the
    # publisher has to edit gets the 400 that says so, rather than a 502 or 503 about GitHub that
    # sends them away to retry a publish that would never have succeeded.
    rendered = render_community_skill_files(
        slug=slug,
        name=name,
        description=description,
        body=body,
        files=files,
        tags=tags,
        allowed_tools=allowed_tools,
        license=license,
        compatibility=compatibility,
        author_handle=author_handle,
    )

    publisher = get_community_skills_publisher()
    if publisher is None:
        raise CommunitySkillPublishNotConfiguredError("Community skill publishing is not configured.")

    branch = f"{COMMUNITY_SKILLS_BRANCH_PREFIX}{slug}-{publisher_branch_key(publisher_id)}"
    try:
        return _write_branch_and_pull_request(
            publisher, rendered=rendered, slug=slug, name=name, author_handle=author_handle, branch=branch
        )
    except (GitHubIntegrationError, GitHubRateLimitError) as err:
        # The client only ever sees this class of failure as "GitHub is unreachable", so the detail
        # has to reach the logs here or it is lost.
        logger.warning("community_skill_publish_github_unavailable", slug=slug, branch=branch, exc_info=True)
        raise CommunitySkillPublishError(
            "Could not reach GitHub to publish this skill. Try again in a few minutes."
        ) from err


def _write_branch_and_pull_request(
    publisher: GitHubIntegration,
    *,
    rendered: list[RenderedFile],
    slug: str,
    name: str,
    author_handle: str,
    branch: str,
) -> dict[str, Any]:
    repo = settings.COMMUNITY_SKILLS_GITHUB_REPO
    base = COMMUNITY_SKILLS_PR_BASE_BRANCH

    # Read the open PR before writing, so a failed write doesn't get blamed on a PR that predates it.
    existing_pr = publisher.get_open_pull_request_for_head(repo, branch)
    if existing_pr is not None:
        _require_publishable_base(existing_pr, base=base)

    commit_result = publisher.commit_files_to_branch(
        repo,
        branch,
        base,
        {rendered_file.path: rendered_file.content for rendered_file in rendered},
        f"{'Update' if existing_pr else 'Add'} community skill: {name}",
        # The skill's directory is rewritten whole rather than merged onto whatever main already
        # holds there. Merged, a bundled file the skill has since dropped keeps being published, and
        # a rename that only changes case leaves both spellings, which ingest folds together and
        # rejects: the pull request merges and the skill disappears from the catalog.
        replace_directory=f"{SKILLS_DIR}/{slug}",
    )
    if not commit_result.get("success"):
        raise CommunitySkillPublishError(f"Failed to commit skill files: {commit_result.get('error')}")
    commit_sha = commit_result.get("commit_sha")

    if existing_pr is not None:
        # Re-read rather than trusting the lookup from before the write. A maintainer merging or
        # closing that review in between would otherwise leave our commit on a public branch with no
        # open review, reported as a success pointing at a pull request that no longer takes it.
        still_open = _reconcile_open_pr(publisher, repo=repo, slug=slug, branch=branch, base=base)
        if still_open is not None:
            logger.info("community_skill_publish_updated_open_pr", slug=slug, pr_number=still_open["pr_number"])
            return still_open
        logger.info("community_skill_publish_reopening_after_review_ended", slug=slug, pr_number=existing_pr["number"])

    try:
        pr_result = publisher.create_pull_request(
            repo,
            f"Add community skill: {name}",
            _community_pr_body(name=name, slug=slug, author_handle=author_handle),
            branch,
            base,
        )
    except (GitHubIntegrationError, GitHubRateLimitError):
        # A transport failure on this POST is ambiguous: GitHub may still have opened the pull
        # request, and api_request doesn't retry a POST. Reconcile before cleaning up, so a timeout
        # can't delete a branch that now heads a live review.
        logger.warning("community_skill_publish_pr_create_ambiguous", slug=slug, branch=branch, exc_info=True)
        reconciled = _reconcile_open_pr(publisher, repo=repo, slug=slug, branch=branch, base=base)
        if reconciled is not None:
            return reconciled
        _delete_publish_branch(publisher, repo=repo, slug=slug, branch=branch, commit_sha=commit_sha)
        raise

    if pr_result.get("success"):
        logger.info("community_skill_published", slug=slug, pr_number=pr_result.get("pr_number"))
        return {"pr_url": pr_result["pr_url"], "pr_number": pr_result["pr_number"], "branch": branch}

    error = str(pr_result.get("error") or "")
    # A branch that already heads a pull request means a concurrent publish won the race. Our commit
    # is on that branch and so inside that review, so return it rather than reporting a failure for
    # content that is already public. Cleanup would belong to that review's branch, not to us.
    if "already exists" in error.lower():
        reconciled = _reconcile_open_pr(publisher, repo=repo, slug=slug, branch=branch, base=base)
        if reconciled is not None:
            return reconciled
        raise CommunitySkillPublishError("A pull request for this skill is already open for review.")

    _delete_publish_branch(publisher, repo=repo, slug=slug, branch=branch, commit_sha=commit_sha)
    # GitHub refuses a pull request with an empty diff, which is what an unchanged skill produces.
    if "no commits between" in error.lower():
        raise CommunitySkillPublishError(
            "This skill already matches what's published, so there's nothing to send. "
            "Edit the skill, then publish again."
        )
    raise CommunitySkillPublishError(f"Failed to open pull request: {error}")


def _require_publishable_base(pull: dict[str, Any], *, base: str) -> None:
    """Refuse a pull request on our branch that no longer targets the branch the catalog is built from.

    Merging a retargeted pull request writes to that other branch, so the skill would never reach the
    catalog even though publishing reported success. Its branch is also under live review, which is
    why this runs before the commit: we neither force-update that branch nor delete it.
    """
    if pull.get("base") == base:
        return
    raise CommunitySkillPublishError(
        f"Pull request #{pull['number']} for this skill is open against "
        f"'{pull.get('base') or 'another branch'}' instead of '{base}'. "
        "Ask a maintainer to retarget or close it, then publish again."
    )


def _reconcile_open_pr(
    publisher: GitHubIntegration, *, repo: str, slug: str, branch: str, base: str
) -> dict[str, Any] | None:
    """Re-read the pull request open for ``branch`` after an ambiguous create, or None if there is none.

    A None here means "found nothing", not "the branch has no pull request": the lookup is
    best-effort and answers None for most failures. It still raises when GitHub rate-limits the read,
    which is caught here so a caller cleaning up after a failure isn't handed a second one.

    A pull request retargeted away from ``base`` raises instead of returning: it is not ours to
    report as this publish's destination, and the raise also keeps the caller from deleting a branch
    that is under review.
    """
    try:
        pull = publisher.get_open_pull_request_for_head(repo, branch)
    except (GitHubIntegrationError, GitHubRateLimitError):
        logger.warning("community_skill_publish_pr_lookup_failed", slug=slug, branch=branch, exc_info=True)
        return None
    if pull is None or not pull.get("url"):
        return None
    _require_publishable_base(pull, base=base)
    logger.info("community_skill_publish_reconciled_open_pr", slug=slug, pr_number=pull["number"])
    return {"pr_url": pull["url"], "pr_number": pull["number"], "branch": branch}


def _delete_publish_branch(
    publisher: GitHubIntegration, *, repo: str, slug: str, branch: str, commit_sha: str | None
) -> None:
    """Remove a branch this publish created. Cleanup failure is logged, never raised over the cause.

    This also runs while handling a GitHub failure, where a raise here would replace the error that
    actually explains the publish with one about the tidy-up after it.

    The delete is conditional on ``commit_sha``: the branch name is shared by every publish of this
    skill from this team, so an unconditional delete could take out a concurrent publisher's commit,
    which they cannot recover the way the publisher who wrote it can.
    """
    try:
        cleanup_result = publisher.delete_branch(repo, branch, expected_sha=commit_sha)
    except (GitHubIntegrationError, GitHubRateLimitError):
        logger.warning("community_skill_publish_branch_cleanup_failed", slug=slug, branch=branch, exc_info=True)
        return
    if not cleanup_result.get("success"):
        logger.warning(
            "community_skill_publish_branch_cleanup_failed",
            slug=slug,
            branch=branch,
            error=cleanup_result.get("error"),
        )
