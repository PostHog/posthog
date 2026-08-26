import re
import hashlib
from collections.abc import Iterable
from pathlib import PurePosixPath

from django.db import transaction

import structlog

from posthog.models.integration import GitHubIntegration

from products.web_analytics.backend.models import ContentAutopilotProposal

from .lifecycle import claim_proposals_for_delivery, mark_delivery_failed

logger = structlog.get_logger(__name__)


class ContentAutopilotDeliveryError(Exception):
    pass


def _cleanup_created_branch(
    *,
    github: GitHubIntegration,
    repository: str,
    branch: str,
    commit_result: dict[str, object],
) -> None:
    if commit_result.get("created_branch") is not True:
        return
    try:
        github.delete_branch(repository, branch, expected_sha=str(commit_result.get("commit_sha") or ""))
    except Exception as cleanup_error:
        logger.warning("content_autopilot_branch_cleanup_failed", error=str(cleanup_error), branch=branch)


def _validated_file_path(file_path: str, content_directories: list[str]) -> str:
    if "\\" in file_path or "\0" in file_path or any(part in {"", ".", ".."} for part in file_path.split("/")):
        raise ContentAutopilotDeliveryError("The generated file path is not allowed.")
    path = PurePosixPath(file_path)
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in {".md", ".mdx"}:
        raise ContentAutopilotDeliveryError("The generated file path is not allowed.")

    normalized = path.as_posix()
    allowed_directories: list[str] = []
    for directory in content_directories:
        if (
            "\\" in directory
            or "\0" in directory
            or any(part in {"", ".", ".."} for part in directory.split("/"))
            or PurePosixPath(directory).is_absolute()
        ):
            raise ContentAutopilotDeliveryError("A configured content directory is not allowed.")
        allowed_directories.append(PurePosixPath(directory).as_posix())
    if not allowed_directories or not any(
        normalized == directory or normalized.startswith(f"{directory}/") for directory in allowed_directories
    ):
        raise ContentAutopilotDeliveryError("The generated file is outside the configured content directories.")
    return normalized


def export_proposal(*, proposal: ContentAutopilotProposal) -> tuple[str, str, dict[str, object]]:
    proposals = claim_proposals_for_delivery(team_id=proposal.team_id, proposal_ids=[str(proposal.id)])
    claimed = proposals[0]
    content_package = claimed.content_package
    file_path = str(content_package.get("file_path") or f"{claimed.id}.md")
    filename = PurePosixPath(file_path).name
    markdown = claimed.proposed_markdown or str(content_package.get("markdown") or "")
    if not markdown.strip():
        mark_delivery_failed(team_id=claimed.team_id, proposal_ids=[str(claimed.id)], message="No Markdown to export.")
        raise ContentAutopilotDeliveryError("This proposal does not contain Markdown to export.")

    with transaction.atomic():
        locked = ContentAutopilotProposal.objects.for_team(claimed.team_id).select_for_update().get(id=claimed.id)
        locked.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.EXPORTED
        locked.delivery_state = ContentAutopilotProposal.DeliveryState.DELIVERED
        locked.delivery_reference = filename
        locked.save(update_fields=["lifecycle_status", "delivery_state", "delivery_reference", "updated_at"])
    return filename, markdown, content_package


def open_pull_request(*, team_id: int, proposal_ids: Iterable[str]) -> tuple[str, str]:
    proposals = claim_proposals_for_delivery(team_id=team_id, proposal_ids=proposal_ids)
    ids = [str(proposal.id) for proposal in proposals]
    try:
        profile = proposals[0].run.profile
        repository_path = profile.github_repository.strip()
        if profile.delivery_mode != profile.DeliveryMode.GITHUB or not repository_path:
            raise ContentAutopilotDeliveryError("Configure GitHub delivery before opening a pull request.")

        github = GitHubIntegration.first_for_team_repository(team_id, repository_path, source="content_autopilot")
        if github is None:
            raise ContentAutopilotDeliveryError("PostHog cannot access the configured GitHub repository.")

        owner, repository = repository_path.split("/", 1)
        if owner.lower() != github.organization().lower():
            raise ContentAutopilotDeliveryError("The configured repository does not match the GitHub integration.")

        files: dict[str, str] = {}
        for proposal in proposals:
            file_path = _validated_file_path(
                str(proposal.content_package.get("file_path") or ""), profile.content_directories
            )
            if file_path in files:
                raise ContentAutopilotDeliveryError("Selected proposals must write to different content files.")
            files[file_path] = proposal.proposed_markdown or str(proposal.content_package.get("markdown") or "")
        if any(not content.strip() for content in files.values()):
            raise ContentAutopilotDeliveryError("Every proposal must contain Markdown before delivery.")

        digest = hashlib.sha256(":".join(sorted(ids)).encode()).hexdigest()[:10]
        branch = f"posthog/content-autopilot-{digest}"
        new_content = proposals[0].proposal_type == ContentAutopilotProposal.ProposalType.NEW_CONTENT
        title = proposals[0].title if new_content else "Improve site content from Search & AI insights"
        title = re.sub(r"\s+", " ", title).strip()[:240]
        commit_result = github.commit_files_to_branch(
            repository,
            branch,
            profile.base_branch,
            files,
            "content: apply approved Search & AI proposal",
        )
        if not commit_result.get("success"):
            raise ContentAutopilotDeliveryError(str(commit_result.get("error") or "Could not commit the content."))

        body = "This pull request contains content approved in PostHog's Content autopilot workspace."
        try:
            pull_request_result = github.create_pull_request(repository, title, body, branch, profile.base_branch)
            if not pull_request_result.get("success"):
                raise ContentAutopilotDeliveryError(
                    str(pull_request_result.get("error") or "Could not open the pull request.")
                )
        except Exception:
            _cleanup_created_branch(
                github=github,
                repository=repository,
                branch=branch,
                commit_result=commit_result,
            )
            raise
        pull_request_url = str(pull_request_result["pr_url"])
    except Exception as error:
        failure_message = (
            str(error)
            if isinstance(error, ContentAutopilotDeliveryError)
            else "Could not deliver the selected proposals to GitHub."
        )
        mark_delivery_failed(team_id=team_id, proposal_ids=ids, message=failure_message)
        if isinstance(error, ContentAutopilotDeliveryError):
            raise
        raise ContentAutopilotDeliveryError(failure_message) from error

    with transaction.atomic():
        ContentAutopilotProposal.objects.for_team(team_id).filter(id__in=ids).update(
            lifecycle_status=ContentAutopilotProposal.LifecycleStatus.PR_OPENED,
            delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERED,
            delivery_reference=branch,
            pull_request_url=pull_request_url,
        )
    return pull_request_url, branch
