"""Publish a team's LLMSkill to the PostHog/community-skills repo as a pull request.

The heavy lifting (branch + commit + PR) reuses the existing `GitHubIntegration` that already
powers the Tasks product. This module owns the pure rendering of an `LLMSkill` into the repo's
`skills/<slug>/SKILL.md` layout; the GitHub side lives in `publish_skill_to_community`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import yaml
import structlog

from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)

# Mirror the community-skills repo's slug rule (scripts/build_registry.py) so we never open a PR the
# repo's own validation would reject.
SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
MAX_SLUG_LENGTH = 64
SKILLS_DIR = "skills"
COMMUNITY_SKILLS_PR_BASE_BRANCH = "main"


class CommunitySkillPublishError(Exception):
    """Raised when a skill can't be rendered or published to the community repo."""


class CommunitySkillPublishNotConfiguredError(CommunitySkillPublishError):
    """Raised when the community-skills GitHub App installation isn't configured on this instance."""


@dataclass(frozen=True)
class RenderedFile:
    """A single file to commit, at its path within the community-skills repo."""

    path: str
    content: str


def _validate_slug(slug: str) -> str:
    if not SLUG_PATTERN.match(slug) or "--" in slug or len(slug) > MAX_SLUG_LENGTH:
        raise CommunitySkillPublishError(
            f"'{slug}' is not a valid community skill slug (lowercase letters, numbers, single hyphens)."
        )
    return slug


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
        raise CommunitySkillPublishError("Skill name is required to publish.")
    if not description.strip():
        raise CommunitySkillPublishError("Skill description is required to publish.")

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
    return f"---\n{rendered_frontmatter}---\n\n{body.strip()}\n"


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

    for file in files or []:
        rel_path = file["path"].lstrip("/")
        # Confine writes to the skill directory — a bundled file must never escape skills/<slug>/.
        if rel_path == "SKILL.md" or ".." in rel_path.split("/"):
            raise CommunitySkillPublishError(f"Invalid bundled file path '{file['path']}'.")
        rendered.append(RenderedFile(path=f"{skill_root}/{rel_path}", content=file["content"]))

    return rendered


def get_community_skills_publisher() -> GitHubIntegration | None:
    """Build a GitHubIntegration bound to the central community-skills installation, or None.

    Mints a fresh installation token via the GitHub App JWT (the same flow the per-team integration
    uses) and wraps it in a transient, unsaved Integration — we never persist a teamless central row.
    Returns None when the App or the community-skills installation isn't configured, so callers can
    surface a clean "not configured" error instead of failing.
    """
    installation_id = settings.COMMUNITY_SKILLS_GITHUB_INSTALLATION_ID
    if not installation_id or not settings.GITHUB_APP_CLIENT_ID or not settings.GITHUB_APP_PRIVATE_KEY:
        return None

    info_response = GitHubIntegration.client_request(f"installations/{installation_id}")
    token_response = GitHubIntegration.client_request(f"installations/{installation_id}/access_tokens", method="POST")
    if info_response.status_code != 200 or token_response.status_code != 201:
        logger.warning(
            "community_skills_publisher_unavailable",
            info_status=info_response.status_code,
            token_status=token_response.status_code,
        )
        return None

    account = info_response.json().get("account") or {}
    token = token_response.json().get("token")
    if not token or not account.get("login"):
        return None

    # Transient (never saved) Integration: the write helpers only read the access token + account
    # name and don't trigger a refresh/save, so this avoids polluting the team-scoped Integration table.
    integration = Integration(
        team_id=None,
        kind="github",
        integration_id=str(installation_id),
        config={"account": {"name": account["login"], "type": account.get("type")}},
        sensitive_config={"access_token": token},
    )
    return GitHubIntegration(integration)


def _community_pr_body(*, name: str, slug: str, author_handle: str) -> str:
    # No PostHog user PII here — this PR is public. Attribution is only the GitHub handle the
    # publisher explicitly provided for public sharing.
    credit = f"Published by @{author_handle}" if author_handle else "Published from the PostHog skills marketplace"
    return (
        f"Adds the **{name}** community skill (`skills/{slug}/`).\n\n"
        f"{credit} via the in-product *Publish to community* flow.\n\n"
        "A maintainer should review the instructions for safety before merging; "
        "set `trust_tier` on review. On merge, CI regenerates `registry.json` and PostHog syncs it."
    )


def publish_skill_to_community(
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
) -> dict[str, Any]:
    """Open a PR in PostHog/community-skills adding (or updating) this skill. Returns the PR url/number.

    Reuses the existing GitHubIntegration branch/commit/PR helpers. Raises CommunitySkillPublishError
    when any GitHub step fails, or CommunitySkillPublishNotConfiguredError when publishing is disabled.
    """
    publisher = get_community_skills_publisher()
    if publisher is None:
        raise CommunitySkillPublishNotConfiguredError("Community skill publishing is not configured.")

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

    repo = settings.COMMUNITY_SKILLS_GITHUB_REPO
    base = COMMUNITY_SKILLS_PR_BASE_BRANCH
    branch = f"community-skill/{slug}-{uuid.uuid4().hex[:8]}"

    branch_result = publisher.create_branch(repo, branch, base)
    if not branch_result.get("success"):
        raise CommunitySkillPublishError(f"Failed to create branch: {branch_result.get('error')}")

    for rendered_file in rendered:
        commit_result = publisher.update_file(
            repo, rendered_file.path, rendered_file.content, f"Add {rendered_file.path}", branch
        )
        if not commit_result.get("success"):
            raise CommunitySkillPublishError(f"Failed to commit {rendered_file.path}: {commit_result.get('error')}")

    pr_result = publisher.create_pull_request(
        repo,
        f"Add community skill: {name}",
        _community_pr_body(name=name, slug=slug, author_handle=author_handle),
        branch,
        base,
    )
    if not pr_result.get("success"):
        raise CommunitySkillPublishError(f"Failed to open pull request: {pr_result.get('error')}")

    logger.info("community_skill_published", slug=slug, pr_number=pr_result.get("pr_number"))
    return {"pr_url": pr_result["pr_url"], "pr_number": pr_result["pr_number"], "branch": branch}
