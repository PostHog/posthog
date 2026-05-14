"""Service-layer orchestrators for the scaffold pipeline.

Thin wrappers around `codegen.render_spec_to_files` and `publish.push_to_github` so the
Celery task and any future cross-product caller share one entry point.
"""

import uuid
from typing import Any

from .codegen import render_spec_to_files
from .publish import enable_github_pages, push_to_github
from .schemas import PagesLink, RepoLink


def generate_scaffold(*, spec: dict[str, Any], project_name: str) -> tuple[dict[str, str], str]:
    """Render the spec into a file tree. Returns (files, trace_id)."""
    trace_id = str(uuid.uuid4())
    files = render_spec_to_files(spec=spec, project_name=project_name)
    return files, trace_id


def publish_scaffold(
    *,
    files: dict[str, str],
    github_token: str,
    repo_name: str,
    visibility: str,
    description: str,
) -> tuple[RepoLink, PagesLink, str]:
    """Push the file tree to a new GitHub repo AND enable GitHub Pages on it.

    Returns (repo_link, pages_link, trace_id). The static site is a single HTML page +
    assets, so we always enable Pages — the founder gets a live URL the moment publish
    completes.
    """
    trace_id = str(uuid.uuid4())
    repo = push_to_github(
        github_token=github_token,
        repo_name=repo_name,
        files=files,
        visibility=visibility,
        description=description,
    )
    # Extract owner from html_url (https://github.com/<owner>/<repo>) — saves a /user call.
    owner = repo.html_url.rstrip("/").split("/")[-2]
    pages = enable_github_pages(
        github_token=github_token,
        owner=owner,
        repo=repo_name,
        branch=repo.default_branch,
        path="/",
    )
    return repo, pages, trace_id
