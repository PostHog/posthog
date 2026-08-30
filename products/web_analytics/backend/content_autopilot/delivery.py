import re
import hashlib
from collections.abc import Iterable
from pathlib import PurePosixPath

from django.db import transaction
from django.utils import timezone

from posthog.models.integration import GitHubIntegration

from products.web_analytics.backend.models import ContentAutopilotProposal

from .lifecycle import claim_proposals_for_delivery, mark_delivery_failed

COMMIT_MESSAGE = "content: apply approved web analytics proposal"
PULL_REQUEST_BODY = "This pull request contains content approved in PostHog's Content autopilot workspace."


class ContentAutopilotDeliveryError(Exception):
    pass


def _normalized_directory(directory: str) -> str:
    if (
        "\\" in directory
        or "\0" in directory
        or any(part in {"", ".", ".."} for part in directory.split("/"))
        or PurePosixPath(directory).is_absolute()
    ):
        raise ContentAutopilotDeliveryError("A configured content directory is not allowed.")
    return PurePosixPath(directory).as_posix()


def _validated_file_path(file_path: str, allowed_directories: list[str]) -> str:
    if (
        "\\" in file_path
        or "\0" in file_path
        or any(part in {"", ".", ".."} for part in file_path.split("/"))
        or PurePosixPath(file_path).suffix.lower() not in {".md", ".mdx"}
    ):
        raise ContentAutopilotDeliveryError("The generated file path is not allowed.")

    normalized = PurePosixPath(file_path).as_posix()
    directories = [_normalized_directory(directory) for directory in allowed_directories]
    if not any(normalized == directory or normalized.startswith(f"{directory}/") for directory in directories):
        raise ContentAutopilotDeliveryError("The generated file is outside the configured content directories.")
    return normalized


def _markdown_for(proposal: ContentAutopilotProposal) -> str:
    return proposal.proposed_markdown or str(proposal.content_package.get("markdown") or "")


def export_proposal(*, proposal: ContentAutopilotProposal) -> tuple[str, str, dict[str, object]]:
    claimed = claim_proposals_for_delivery(team_id=proposal.team_id, proposal_ids=[str(proposal.id)])[0]
    content_package = claimed.content_package
    filename = PurePosixPath(str(content_package.get("file_path") or f"{claimed.id}.md")).name
    markdown = _markdown_for(claimed)
    if not markdown.strip():
        mark_delivery_failed(team_id=claimed.team_id, proposal_ids=[str(claimed.id)], message="No Markdown to export.")
        raise ContentAutopilotDeliveryError("This proposal does not contain Markdown to export.")

    ContentAutopilotProposal.objects.for_team(claimed.team_id).filter(id=claimed.id).update(
        lifecycle_status=ContentAutopilotProposal.LifecycleStatus.EXPORTED,
        delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERED,
        delivery_reference=filename,
        updated_at=timezone.now(),
    )
    return filename, markdown, content_package


def _resolve_delivery_target(proposal: ContentAutopilotProposal) -> tuple[str, str, list[str]]:
    profile = proposal.run.profile
    snapshot = proposal.run.input_snapshot
    delivery_mode = str(snapshot.get("delivery_mode") or profile.delivery_mode)
    repository_path = str(snapshot.get("github_repository") or profile.github_repository).strip()
    base_branch = str(snapshot.get("base_branch") or profile.base_branch).strip()
    content_directories = snapshot.get("content_directories") or profile.content_directories

    if not isinstance(content_directories, list) or not all(isinstance(path, str) for path in content_directories):
        raise ContentAutopilotDeliveryError("The saved content directory settings are invalid.")
    if not content_directories:
        raise ContentAutopilotDeliveryError("Configure at least one content directory before opening a pull request.")
    if delivery_mode != profile.DeliveryMode.GITHUB or not repository_path:
        raise ContentAutopilotDeliveryError("Configure GitHub delivery before opening a pull request.")
    return repository_path, base_branch, content_directories


def _collect_files(proposals: list[ContentAutopilotProposal], content_directories: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for proposal in proposals:
        file_path = _validated_file_path(str(proposal.content_package.get("file_path") or ""), content_directories)
        if file_path in files:
            raise ContentAutopilotDeliveryError("Selected proposals must write to different content files.")
        markdown = _markdown_for(proposal)
        if not markdown.strip():
            raise ContentAutopilotDeliveryError("Every proposal must contain Markdown before delivery.")
        files[file_path] = markdown
    return files


def _deliver(*, team_id: int, proposals: list[ContentAutopilotProposal], ids: list[str]) -> tuple[str, str]:
    repository_path, base_branch, content_directories = _resolve_delivery_target(proposals[0])

    github = GitHubIntegration.first_for_team_repository(team_id, repository_path, source="content_autopilot")
    if github is None:
        raise ContentAutopilotDeliveryError(
            "Connect a GitHub integration with access to the configured repository, then try again."
        )

    owner, repository = repository_path.split("/", 1)
    if owner.lower() != github.organization().lower():
        raise ContentAutopilotDeliveryError(
            "Select a repository owned by the organization connected through the GitHub integration."
        )

    files = _collect_files(proposals, content_directories)
    branch = f"posthog/content-autopilot-{hashlib.sha256(':'.join(sorted(ids)).encode()).hexdigest()[:10]}"

    commit_result = github.commit_files_to_branch(repository, branch, base_branch, files, COMMIT_MESSAGE)
    if not commit_result.get("success"):
        raise ContentAutopilotDeliveryError(str(commit_result.get("error") or "Could not commit the content."))

    is_new_content = proposals[0].proposal_type == ContentAutopilotProposal.ProposalType.NEW_CONTENT
    raw_title = proposals[0].title if is_new_content else "Improve site content from web analytics insights"
    title = re.sub(r"\s+", " ", raw_title).strip()[:240]

    pull_request_result = github.create_pull_request(repository, title, PULL_REQUEST_BODY, branch, base_branch)
    if not pull_request_result.get("success"):
        raise ContentAutopilotDeliveryError(str(pull_request_result.get("error") or "Could not open the pull request."))
    return str(pull_request_result["pr_url"]), branch


def open_pull_request(*, team_id: int, proposal_ids: Iterable[str]) -> tuple[str, str]:
    proposals = claim_proposals_for_delivery(team_id=team_id, proposal_ids=proposal_ids)
    ids = [str(proposal.id) for proposal in proposals]
    try:
        pull_request_url, branch = _deliver(team_id=team_id, proposals=proposals, ids=ids)
    except Exception as error:
        message = (
            str(error)
            if isinstance(error, ContentAutopilotDeliveryError)
            else "Could not deliver the selected proposals to GitHub."
        )
        mark_delivery_failed(team_id=team_id, proposal_ids=ids, message=message)
        if isinstance(error, ContentAutopilotDeliveryError):
            raise
        raise ContentAutopilotDeliveryError(message) from error

    with transaction.atomic():
        ContentAutopilotProposal.objects.for_team(team_id).filter(id__in=ids).update(
            lifecycle_status=ContentAutopilotProposal.LifecycleStatus.PR_OPENED,
            delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERED,
            delivery_reference=branch,
            pull_request_url=pull_request_url,
            updated_at=timezone.now(),
        )
    return pull_request_url, branch
