"""Pydantic schemas for the scaffold stage.

Two-step pipeline:
1. `generate_scaffold` — render the LandingPageBuildSpec into a {path: contents} file map,
   stored on `FounderProject.scaffold.files`.
2. `publish_scaffold` — push that file map to a new GitHub repository, storing the result
   on `FounderProject.scaffold.repo`.

Splitting the stages lets the founder preview the generated tree before committing to a
real repo, and keeps the (slow, error-prone) GitHub API call out of the generation hot path.
"""

from pydantic import BaseModel, ConfigDict, Field

from products.founder_mode.backend.logic.envelope import StageStatus


class RepoLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_url: str = Field(description="API URL of the repository (`https://api.github.com/repos/<owner>/<name>`).")
    html_url: str = Field(description="Browseable URL of the repository the founder can open in their browser.")
    default_branch: str = Field(description="The default branch the initial commit landed on (typically `main`).")
    commit_sha: str = Field(description="SHA of the initial commit containing every generated file.")
    file_count: int = Field(description="How many files were pushed in the initial commit.")


class PagesLink(BaseModel):
    """GitHub Pages site metadata returned after enablement + provisioning."""

    model_config = ConfigDict(extra="forbid")

    html_url: str = Field(description="Live URL the static page is served at, e.g. https://owner.github.io/repo/")
    pages_status: str = Field(
        description=(
            "GitHub Pages build state at the time of polling: `built`, `building`, `queued`, "
            "`errored`, or `not_provisioned` if we gave up polling before it went live."
        )
    )
    source_branch: str = Field(description="Branch GitHub Pages serves from (e.g. `main`).")
    source_path: str = Field(description="Path within the branch the site is served from (e.g. `/`).")


class ScaffoldEnvelope(BaseModel):
    """API-facing envelope for the `scaffold` JSON column."""

    status: StageStatus | None = Field(default=None, description="Lifecycle state of the most recent scaffold action.")
    files: dict[str, str] | None = Field(
        default=None,
        description=(
            "Generated file tree as `{path: contents}`. Populated by `run_scaffold`. Paths are "
            "POSIX-style relative paths (no leading slash). Null while pending or before the "
            "first generation run."
        ),
    )
    file_count: int | None = Field(default=None, description="Number of files in `files`.")
    total_bytes: int | None = Field(default=None, description="Total size of all file contents combined.")
    repo: RepoLink | None = Field(
        default=None,
        description="Populated by `publish_scaffold` once the file tree has been pushed to GitHub.",
    )
    pages: PagesLink | None = Field(
        default=None,
        description=(
            "Populated by `publish_scaffold` after enabling GitHub Pages on the new repo. "
            "`pages.html_url` is the live URL the founder can share."
        ),
    )
    started_at: str | None = Field(default=None, description="ISO timestamp when the most recent action kicked off.")
    completed_at: str | None = Field(default=None, description="ISO timestamp when the most recent action succeeded.")
    failed_at: str | None = Field(default=None, description="ISO timestamp when the most recent action failed.")
    trace_id: str | None = Field(default=None, description="Trace id linking to the underlying operation.")
    error: str = Field(default="", description="Human-readable error message when `status='failed'`. Empty otherwise.")


class PublishScaffoldRequest(BaseModel):
    """Body for the `publish_scaffold` action."""

    model_config = ConfigDict(extra="forbid")

    github_token: str | None = Field(
        default=None,
        description=(
            "GitHub personal access token with `repo` scope. Used once to create the repo and "
            "push the initial commit, then discarded — not persisted. If omitted, the server "
            "falls back to the `FOUNDER_MODE_GITHUB_PAT` env var (local-dev convenience)."
        ),
    )
    repo_name: str = Field(
        description="Name for the new repository on the authenticated user's account.",
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    visibility: str = Field(
        default="private",
        description="Repository visibility. `public` or `private`. Defaults to private.",
        pattern=r"^(public|private)$",
    )
    description: str = Field(
        default="",
        description="Optional one-line repo description.",
        max_length=350,
    )
