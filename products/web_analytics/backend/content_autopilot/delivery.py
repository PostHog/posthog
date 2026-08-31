from pathlib import PurePosixPath

from django.utils import timezone

from posthog.dataclasses import frozen

from products.web_analytics.backend.models import ContentAutopilotProposal

from .lifecycle import claim_proposal_for_delivery, mark_delivery_failed


class ContentAutopilotDeliveryError(Exception):
    pass


@frozen
class ExportedProposal:
    filename: str
    markdown: str
    content_package: dict[str, object]


def export_proposal(*, proposal: ContentAutopilotProposal) -> ExportedProposal:
    claimed = claim_proposal_for_delivery(team_id=proposal.team_id, proposal_id=str(proposal.id))
    content_package = claimed.content_package
    filename = PurePosixPath(str(content_package.get("file_path") or f"{claimed.id}.md")).name
    markdown = claimed.proposed_markdown or str(content_package.get("markdown") or "")
    if not markdown.strip():
        mark_delivery_failed(team_id=claimed.team_id, proposal_id=str(claimed.id), message="No Markdown to export.")
        raise ContentAutopilotDeliveryError("This proposal does not contain Markdown to export.")

    ContentAutopilotProposal.objects.for_team(claimed.team_id).filter(id=claimed.id).update(
        lifecycle_status=ContentAutopilotProposal.LifecycleStatus.EXPORTED,
        delivery_state=ContentAutopilotProposal.DeliveryState.DELIVERED,
        delivery_reference=filename,
        updated_at=timezone.now(),
    )
    return ExportedProposal(filename=filename, markdown=markdown, content_package=content_package)
