"""Publish a team's LLMSkill to the PostHog/community-skills repo as a pull request.

The heavy lifting (branch + commit + PR) reuses the existing `GitHubIntegration` that already
powers the Tasks product. This module owns the pure rendering of an `LLMSkill` into the repo's
`skills/<slug>/SKILL.md` layout; the GitHub side lives in `publish_skill_to_community`.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import yaml
import structlog

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration, Integration

logger = structlog.get_logger(__name__)

# Mirror the community-skills repo's slug rule (scripts/build_registry.py) so we never open a PR the
# repo's own validation would reject.
SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
MAX_SLUG_LENGTH = 64
# GitHub usernames are alphanumeric with single inner hyphens, up to 39 characters. The handle is
# self-reported and lands in a public PR body and in the listing, so hold it to the shape of a real
# username rather than letting free text through.
GITHUB_HANDLE_PATTERN = re.compile(r"^[a-zA-Z0-9](?:-?[a-zA-Z0-9]){0,38}$")
# The API field is optional, so the shape it publishes to clients has to accept an empty string too —
# otherwise generated validators reject the blank the endpoint itself allows.
OPTIONAL_GITHUB_HANDLE_PATTERN = re.compile(f"^$|{GITHUB_HANDLE_PATTERN.pattern}")
# Matches CommunitySkill.name — a longer name publishes and merges, then ingest rejects the entry and
# the skill silently never appears in the catalog.
MAX_DISPLAY_NAME_LENGTH = 64
MAX_TAG_LENGTH = 64
SKILLS_DIR = "skills"
COMMUNITY_SKILLS_PR_BASE_BRANCH = "main"
COMMUNITY_SKILLS_BRANCH_PREFIX = "community-skill/"


class CommunitySkillPublishError(Exception):
    """Raised when a skill can't be rendered or published to the community repo."""


class CommunitySkillPublishNotConfiguredError(CommunitySkillPublishError):
    """Raised when the community-skills GitHub App installation isn't configured on this instance."""


class _CommunitySkillsPublisher(GitHubIntegration):
    """Publisher client whose Integration row is transient and belongs to no team.

    A fresh installation token is minted for every publish, so a 401 is a real failure rather than an
    expiry to heal — and the inherited refresh would try to save a teamless row, which the model's
    team foreign key forbids.
    """

    def refresh_access_token(self) -> None:
        raise GitHubIntegrationError("The community-skills publisher mints a token per publish and cannot refresh.")


@dataclass(frozen=True)
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
    return [tag for tag in tags if isinstance(tag, str) and tag.strip() and len(tag) <= MAX_TAG_LENGTH]


def publisher_branch_key(publisher_id: str) -> str:
    """Short, stable, opaque branch suffix for one publisher.

    Skill slugs are only unique within a team, but a branch name is global to the community repo, so a
    slug alone would let one team's publish force-update another team's open pull request. Hashing
    keeps the publisher's identifier out of a public branch name.
    """
    return hashlib.sha256(publisher_id.encode()).hexdigest()[:8]


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
    if len(name.strip()) > MAX_DISPLAY_NAME_LENGTH:
        raise CommunitySkillPublishError(f"Skill name must be {MAX_DISPLAY_NAME_LENGTH} characters or fewer.")
    if not description.strip():
        raise CommunitySkillPublishError("Skill description is required to publish.")
    if author_handle.strip() and not GITHUB_HANDLE_PATTERN.match(author_handle.strip()):
        raise CommunitySkillPublishError(f"'{author_handle}' is not a valid GitHub username.")

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

    # Transient (never saved) Integration, left unattached to any team: the write helpers only read
    # the access token + account name and don't trigger a refresh/save, so this avoids polluting the
    # team-scoped Integration table.
    integration = Integration(
        kind="github",
        integration_id=str(installation_id),
        config={"account": {"name": account["login"], "type": account.get("type")}},
        sensitive_config={"access_token": token},
    )
    return _CommunitySkillsPublisher(integration)


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
    deletes the branch again — this repo is public, so a half-written skill or an unreviewed branch
    must not survive a failed publish.

    ``publisher_id`` identifies the publishing team and is required. Leaving the branch keyed on the
    slug alone would let one team's publish force-update another team's open pull request, because a
    skill slug is only unique within a team.

    Raises CommunitySkillPublishError when any GitHub step fails, or
    CommunitySkillPublishNotConfiguredError when publishing is disabled.
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

    commit_result = publisher.commit_files_to_branch(
        repo,
        branch,
        base,
        {rendered_file.path: rendered_file.content for rendered_file in rendered},
        f"{'Update' if existing_pr else 'Add'} community skill: {name}",
    )
    if not commit_result.get("success"):
        raise CommunitySkillPublishError(f"Failed to commit skill files: {commit_result.get('error')}")

    if existing_pr is not None:
        pr_url = existing_pr.get("url")
        if not pr_url:
            raise CommunitySkillPublishError("A pull request for this skill is already open for review.")
        logger.info("community_skill_publish_updated_open_pr", slug=slug, pr_number=existing_pr["number"])
        return {"pr_url": pr_url, "pr_number": existing_pr["number"], "branch": branch}

    pr_result = publisher.create_pull_request(
        repo,
        f"Add community skill: {name}",
        _community_pr_body(name=name, slug=slug, author_handle=author_handle),
        branch,
        base,
    )
    if pr_result.get("success"):
        logger.info("community_skill_published", slug=slug, pr_number=pr_result.get("pr_number"))
        return {"pr_url": pr_result["pr_url"], "pr_number": pr_result["pr_number"], "branch": branch}

    error = str(pr_result.get("error") or "")
    # Cleanup is for debris this call just created. A branch that already heads a pull request (a
    # concurrent publish won the race) belongs to that review, so leave it alone.
    if "already exists" not in error.lower():
        cleanup_result = publisher.delete_branch(repo, branch)
        if not cleanup_result.get("success"):
            logger.warning(
                "community_skill_publish_branch_cleanup_failed",
                slug=slug,
                branch=branch,
                error=cleanup_result.get("error"),
            )
    # GitHub refuses a pull request with an empty diff, which is what an unchanged skill produces.
    if "no commits between" in error.lower():
        raise CommunitySkillPublishError(
            "This skill already matches what's published, so there's nothing to send. "
            "Edit the skill, then publish again."
        )
    raise CommunitySkillPublishError(f"Failed to open pull request: {error}")
