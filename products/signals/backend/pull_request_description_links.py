"""Link a pull request to the inbox reports its description names, and claim them for its author.

A pull request closed without a merge suppresses the reports it is linked to, and on a public repository anyone can
open a pull request with any description. So only an author whose GitHub account a member of the project's
organization linked, and who can edit the Inbox in that project, can link a report this way.
"""

from collections.abc import Callable
from enum import StrEnum
from functools import cache, partial

from django.db import transaction

import structlog

from posthog.models import Team, User
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalReport
from products.signals.backend.pr_owner_assignments import github_identity_source
from products.signals.backend.pull_requests import (
    apply_report_completion,
    import_report_pull_requests,
    link_pull_request,
)
from products.signals.backend.report_access import may_write_reports
from products.signals.backend.report_assignments import (
    CLAIMABLE_REPORT_STATUSES,
    MAX_PR_NUMBER,
    MAX_REPOSITORY_LENGTH,
    PullRequestDetails,
    ReportClaimConflict,
    _pull_request_details,
    assignment_snapshot,
    claim_report,
    log_assignment_change,
)
from products.signals.backend.report_claims import ReportClaim, get_active_claim, is_claim_of_person
from products.signals.backend.report_content_gates import team_pr_description_auto_link_enabled
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users

logger = structlog.get_logger(__name__)


class _AuthorRejection(StrEnum):
    NOT_A_MEMBER = "author_not_a_member"
    UNVERIFIED_GITHUB_ACCOUNT = "author_github_account_unverified"
    NO_INBOX_ACCESS = "author_without_inbox_access"


class _Outcome(StrEnum):
    CLAIM = "claim"
    LINK = "link"
    ALREADY_LINKED = "already_linked"
    NOT_CLAIMABLE = "not_claimable"
    REPORT_NOT_FOUND = "report_not_found"
    CLAIM_CONFLICT = "claim_conflict"


def _inbox_editor(team: Team, github_login: str, github_id: int) -> User | _AuthorRejection:
    login = github_login.strip().lower()
    member = resolve_org_github_login_to_users(team.id, [login]).get(login)
    if member is None or not member.is_active:
        return _AuthorRejection.NOT_A_MEMBER
    identity = github_identity_source(member, login)
    # Another GitHub account can register a login that a member gave up, so the member's linked account must carry
    # the author's id. A link without an id, such as the installer login on the team integration, proves nothing.
    if identity is None or identity[1] != github_id:
        return _AuthorRejection.UNVERIFIED_GITHUB_ACCOUNT
    has_project_access = team.all_users_with_access(user_uuids=[str(member.uuid)]).exists()
    if not has_project_access or not may_write_reports(user=member, team=team):
        return _AuthorRejection.NO_INBOX_ACCESS
    return member


def _description_link_action(*, linked: bool, status: str, claim: ReportClaim | None, author_id: int) -> _Outcome:
    if linked:
        return _Outcome.ALREADY_LINKED
    if status not in CLAIMABLE_REPORT_STATUSES:
        return _Outcome.NOT_CLAIMABLE
    if claim is None or is_claim_of_person(claim, author_id):
        return _Outcome.CLAIM
    # Another person or a PostHog task holds the claim. The pull request still documents work on the report, but a
    # description is not a request to take that work over.
    return _Outcome.LINK


def _links_pull_request(report: SignalReport, repository: str, number: int) -> bool:
    # Reads task output as well as stored links, so a PostHog task's own pull request is not linked a second time
    # under its author before the task records it.
    prs = fetch_implementation_prs_for_reports([str(report.id)], team_id=report.team_id, using="default")
    for pr in prs.get(str(report.id), []):
        parsed = GitHubIntegrationBase.parse_pull_request_url(pr.url)
        if parsed is not None and parsed.repository.lower() == repository and parsed.number == number:
            return True
    return False


def _link_without_claim(report: SignalReport, details: PullRequestDetails, author: User) -> _Outcome:
    with transaction.atomic():
        locked = (
            SignalReport.objects.select_for_update(no_key=True).filter(team_id=report.team_id, id=report.id).first()
        )
        if locked is None:
            return _Outcome.REPORT_NOT_FOUND
        import_report_pull_requests(locked, notify_reviewers=True)
        claim = get_active_claim(team_id=locked.team_id, report_id=locked.id)
        action = _description_link_action(
            linked=_links_pull_request(locked, details.repository, details.number),
            status=locked.effective_status,
            claim=claim,
            author_id=author.id,
        )
        if action != _Outcome.LINK:
            return action
        before = assignment_snapshot(locked, claim)
        link_pull_request(report=locked, details=details, actor=ArtefactAttribution.from_user(author.id), claim_id=None)
        apply_report_completion(locked)
        log_assignment_change(locked, before, assignment_snapshot(locked, claim), user=author, was_impersonated=False)
        return _Outcome.LINK


def _link_report(
    report: SignalReport,
    *,
    pr_url: str,
    repository: str,
    number: int,
    author: User,
    details: Callable[[], PullRequestDetails],
) -> _Outcome:
    action = _description_link_action(
        linked=_links_pull_request(report, repository, number),
        status=report.effective_status,
        claim=get_active_claim(team_id=report.team_id, report_id=report.id),
        author_id=author.id,
    )
    if action == _Outcome.LINK:
        # The read above holds no lock, so the link decides again under the report lock.
        action = _link_without_claim(report, details(), author)
    if action != _Outcome.CLAIM:
        return action
    from products.signals.backend.report_claim_follow_up import (  # noqa: PLC0415 - it reaches the scout harness, which imports the tasks module that imports this one
        record_report_claimed,
    )

    actor = ArtefactAttribution.from_user(author.id)
    try:
        claim_report(
            report=report,
            actor=actor,
            user=author,
            was_impersonated=False,
            pull_requests=[pr_url],
            on_new_claim=partial(
                record_report_claimed,
                team_id=report.team_id,
                report_id=str(report.id),
                actor=actor,
                scoped_team_ids=None,
                was_impersonated=False,
            ),
        )
    except ReportClaimConflict:
        return _Outcome.CLAIM_CONFLICT
    return _Outcome.CLAIM


def link_described_reports(
    *, team_id: int, pr_url: str, author_login: str, author_github_id: int, report_ids: list[str]
) -> None:
    """Link the pull request to each report, and claim the report for the author when nobody else holds it.

    The author takes the claim only when the report has none or the author already holds it, directly or through
    their agent. A report that already links the pull request is left alone, so a repeated delivery writes nothing.
    """
    log = logger.bind(team_id=team_id, pr_url=pr_url)
    if not team_pr_description_auto_link_enabled(team_id):
        log.info("signals.pr_description_link.skipped", reason="flag_disabled")
        return
    parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
    if parsed is None or not 0 < parsed.number <= MAX_PR_NUMBER or len(parsed.repository) > MAX_REPOSITORY_LENGTH:
        log.info("signals.pr_description_link.skipped", reason="invalid_pr_url")
        return
    team = Team.objects.get(id=team_id)
    author = _inbox_editor(team, author_login, author_github_id)
    if isinstance(author, _AuthorRejection):
        log.info("signals.pr_description_link.skipped", reason=author.value)
        return

    details = cache(partial(_pull_request_details, team_id, pr_url))
    for report in SignalReport.objects.filter(team_id=team_id, id__in=report_ids).order_by("id"):
        outcome = _link_report(
            report,
            pr_url=pr_url,
            repository=parsed.repository.lower(),
            number=parsed.number,
            author=author,
            details=details,
        )
        if outcome in (_Outcome.CLAIM, _Outcome.LINK):
            log.info(
                "signals.pr_description_link.linked",
                report_id=str(report.id),
                user_id=author.id,
                claimed=outcome == _Outcome.CLAIM,
            )
        else:
            log.info("signals.pr_description_link.skipped", report_id=str(report.id), reason=outcome.value)
