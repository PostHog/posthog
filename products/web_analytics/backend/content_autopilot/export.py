from pathlib import PurePosixPath

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.web_analytics.backend.content_autopilot.lifecycle import ContentAutopilotLifecycleError, lock_proposal
from products.web_analytics.backend.models import ContentAutopilotProposal


class ContentAutopilotExportError(Exception):
    pass


@frozen
class ExportedProposal:
    filename: str
    markdown: str
    content_package: dict[str, object]


MAX_EXPORT_FILENAME_CHARS = 255


def _export_filename(*, file_path: object, proposal_id: str) -> str:
    fallback = f"{proposal_id}.md"
    if not isinstance(file_path, str):
        return fallback

    filename = PurePosixPath(file_path.replace("\\", "/")).name
    if (
        not filename
        or filename == ".."
        or len(filename) > MAX_EXPORT_FILENAME_CHARS
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        return fallback
    return filename


def export_proposal(*, team: Team, proposal_id: str) -> ExportedProposal:
    with transaction.atomic():
        try:
            locked_proposal = lock_proposal(team, proposal_id)
        except ContentAutopilotLifecycleError as error:
            raise ContentAutopilotExportError(str(error)) from error

        if locked_proposal.lifecycle_status != ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW:
            raise ContentAutopilotExportError("Only a proposal ready for review can be exported.")
        if locked_proposal.validation_report.get("passed") is not True:
            raise ContentAutopilotExportError("Resolve the failed validation checks before exporting this proposal.")
        if not locked_proposal.proposed_markdown.strip():
            raise ContentAutopilotExportError("Add Markdown to this proposal before exporting it.")
        if not isinstance(locked_proposal.content_package, dict):
            raise ContentAutopilotExportError(
                "This proposal does not have valid export details. Regenerate it and try again."
            )

        content_package = locked_proposal.content_package
        filename = _export_filename(file_path=content_package.get("file_path"), proposal_id=str(locked_proposal.id))
        locked_proposal.lifecycle_status = ContentAutopilotProposal.LifecycleStatus.EXPORTED
        locked_proposal.save(update_fields=["lifecycle_status", "updated_at"])

        return ExportedProposal(
            filename=filename,
            markdown=locked_proposal.proposed_markdown,
            content_package=content_package,
        )
