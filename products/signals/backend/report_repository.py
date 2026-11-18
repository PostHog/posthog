from django.db import transaction

from pydantic import ValidationError

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.select_repo import RepoSelectionResult, persisted_repo_selection

INBOX_REPOSITORY_REASON = "Repository changed in the inbox."


def update_report_repository(*, report: SignalReport, repository: str, attribution: ArtefactAttribution) -> bool:
    """Append an attributed `repo_selection` that names `repository`, and return whether it changed.

    `repository` must already be a lowercased 'owner/repo' that the project's GitHub integration can
    reach. The new row keeps the previous selection's research context and autostart eligibility, so
    a correction changes where the work goes but neither grants nor withdraws an automatic PR.
    """
    with transaction.atomic():
        SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        try:
            previous = persisted_repo_selection(str(report.id))
        except ValidationError:
            # A malformed legacy row must not block the correction that replaces it.
            previous = None
        if previous is not None and (previous.repository or "").lower() == repository:
            return False
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            attribution=attribution,
            content=RepoSelectionResult(
                repository=repository,
                reason=INBOX_REPOSITORY_REASON,
                research_context=previous.research_context if previous is not None else None,
                # With no earlier selection there is no agent decision to start a PR to inherit.
                autostart_eligible=previous.autostart_eligible if previous is not None else False,
            ),
        )
        report.save(update_fields=["updated_at"])
    return True
