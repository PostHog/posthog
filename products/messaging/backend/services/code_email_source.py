"""Find the file that sends a code email by searching the team's GitHub installations for its key.

Detection links a key only when the strict search finds exactly one call site and every installation
answered in full. Anything less leaves the key for a person to link, who can run the same search and pick a file.
"""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import UUID

import structlog
import posthoganalytics
from requests import RequestException

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.event_usage import groups
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.integration.github import GitHubInstallationAccessFetchError
from posthog.models.integration.github_code_search import (
    MAX_LITERAL_LENGTH,
    ExactCodeMatch,
    ExactCodeSearchResult,
    GitHubExactCodeSearch,
    MatchedLine,
)
from posthog.models.team import Team

from products.messaging.backend.facade.contracts import (
    CodeEmailSourceCandidate,
    CodeEmailSourceCandidates,
    CodeEmailSourceOrigin,
    CodeEmailSourceSearchUnavailable,
)
from products.messaging.backend.models import TransactionalEmailKey

logger = structlog.get_logger(__name__)

SOURCE_DETECTION_FLAG = "workflows-code-email-source-detection"
SOURCE_DETECTED_EVENT = "transactional email source detected"

SourceDetectionOutcome = Literal["linked", "several", "none", "incomplete", "budget"]
# Outcomes another search can change: code pushed minutes before the first send, an index GitHub had not finished,
# or a budget that has refilled.
RETRIED_OUTCOMES: frozenset[SourceDetectionOutcome] = frozenset({"none", "incomplete", "budget"})

_SKIPPED_DIRECTORIES = frozenset(
    {
        "test",
        "tests",
        "__tests__",
        "spec",
        "fixtures",
        "mocks",
        "__mocks__",
        "stories",
        "e2e",
        "node_modules",
        "vendor",
        "dist",
        "build",
    }
)
_SKIPPED_FILE_NAME_PARTS = (".test.", ".spec.", "_test.", ".stories.")
# The send calls of PostHog's SDKs, and the raw API route. A matched line's context holds up to five lines on
# either side, so a key passed a few lines below the call still counts.
_SEND_CALL = re.compile(
    r"emails\.send|emails\(\)(?:\.|->)send|Emails\(\)\.Send|Emails\.SendAsync|Emails\.send|send/email"
)


@frozen
class CallSite:
    repository: str
    path: str
    line: int

    @property
    def url(self) -> str:
        return _file_url(self.repository, self.path, self.line)


def _file_url(repository: str, path: str, line: int) -> str:
    # GitHub resolves HEAD to the repository's default branch, which is the branch code search indexes.
    return f"https://github.com/{repository}/blob/HEAD/{quote(path)}#L{line}"


@frozen
class _InstallationSearches:
    # An installation that failed is in ``results`` as an empty, incomplete search. A shed one is left out.
    results: list[ExactCodeSearchResult]
    shed: bool
    answered: int


@frozen
class SourceDetection:
    outcome: SourceDetectionOutcome
    call_site: CallSite | None
    # Matched files left after test and build paths are dropped.
    candidate_files: int


def rank_call_sites(results: Sequence[ExactCodeSearchResult], *, shed: bool) -> SourceDetection:
    """Pick the one call site to link from each installation's search.

    ``shed`` is True when the egress budget refused an installation's search, so that installation has no result.
    """
    candidates = _kept_matches(results)
    call_sites = [
        CallSite(repository=match.repository, path=match.path, line=line.number)
        for match in candidates
        for line in match.lines
        if _is_call_site(line)
    ]
    # The link names a file, so a key passed twice in one send block still has one source.
    if len({(site.repository, site.path) for site in call_sites}) > 1:
        outcome: SourceDetectionOutcome = "several"
    elif shed:
        outcome = "budget"
    elif not all(result.complete for result in results):
        outcome = "incomplete"
    else:
        outcome = "linked" if call_sites else "none"
    return SourceDetection(
        outcome=outcome,
        call_site=call_sites[0] if outcome == "linked" else None,
        candidate_files=len(candidates),
    )


def _kept_matches(results: Sequence[ExactCodeSearchResult]) -> list[ExactCodeMatch]:
    return [match for result in results for match in result.matches if not _is_skipped_path(match.path)]


def _is_call_site(line: MatchedLine) -> bool:
    return bool(_SEND_CALL.search(line.context))


def _is_skipped_path(path: str) -> bool:
    parts = PurePosixPath(path.lower()).parts
    return bool(_SKIPPED_DIRECTORIES.intersection(parts[:-1])) or any(
        part in parts[-1] for part in _SKIPPED_FILE_NAME_PARTS
    )


def detect_code_email_source(team_id: int, key_id: UUID, *, attempt: int) -> SourceDetection | None:
    """Search the team's GitHub installations for a key and link the one file that sends it.

    Returns None when detection does not apply: the flag is off, the key is gone, already linked or too long to
    search, or the team has no GitHub installation.
    """
    team = Team.objects.filter(id=team_id).first()
    if team is None or not source_detection_enabled(team):
        return None
    keys = TransactionalEmailKey.objects.for_team(team_id, canonical=True)
    key = keys.filter(id=key_id, source_url__isnull=True).values_list("key", flat=True).first()
    if key is None or len(key) > MAX_LITERAL_LENGTH:
        return None
    integrations = IntegrationManager.github.oauth.list(team_id)
    if not integrations:
        return None

    searches = _search_installations(team_id, integrations, key, priority=Priority.BATCH)
    detection = rank_call_sites(searches.results, shed=searches.shed)
    if detection.call_site is not None:
        # A person may link the key while the search runs, and their link wins.
        keys.filter(id=key_id, team_id=team_id, source_url__isnull=True).update(
            source_url=detection.call_site.url, source_origin=CodeEmailSourceOrigin.DETECTED
        )
    _report(team, detection, attempt=attempt, installations=len(integrations))
    return detection


def find_source_candidates(team: Team, key: str) -> CodeEmailSourceCandidates:
    """Search the team's GitHub installations for a key while a person waits, one candidate per file.

    Files with a send call come first. Raises ``CodeEmailSourceSearchUnavailable`` when no installation answered,
    and ``ValueError`` for a key GitHub can't search.
    """
    integrations = IntegrationManager.github.oauth.list(team.id)
    if not integrations:
        return CodeEmailSourceCandidates(candidates=(), complete=True)
    searches = _search_installations(team.id, integrations, key, priority=Priority.NORMAL)
    if not searches.answered:
        raise CodeEmailSourceSearchUnavailable(shed=searches.shed)
    candidates = [_candidate(match) for match in _kept_matches(searches.results)]
    return CodeEmailSourceCandidates(
        # sorted is stable, so each group keeps GitHub's order.
        candidates=tuple(sorted(candidates, key=lambda candidate: not candidate.call_site)),
        complete=not searches.shed and all(result.complete for result in searches.results),
    )


def _candidate(match: ExactCodeMatch) -> CodeEmailSourceCandidate:
    line = next((line for line in match.lines if _is_call_site(line)), match.lines[0])
    return CodeEmailSourceCandidate(
        repository=match.repository,
        path=match.path,
        line=line.number,
        url=_file_url(match.repository, match.path, line.number),
        call_site=_is_call_site(line),
    )


def _search_installations(
    team_id: int, integrations: Sequence[IntegrationRecord], key: str, *, priority: Priority
) -> _InstallationSearches:
    results: list[ExactCodeSearchResult] = []
    shed = False
    answered = 0
    for integration in integrations:
        github = GitHubIntegration(integration, source="transactional_email_source", priority=priority)
        try:
            results.append(GitHubExactCodeSearch(github).find(key))
            answered += 1
        except GitHubEgressBudgetExhausted:
            shed = True
        except (
            GitHubIntegrationError,
            GitHubRateLimitError,
            GitHubInstallationAccessFetchError,
            RequestException,
        ) as error:
            logger.warning("code_email_source_search_failed", team_id=team_id, error=str(error))
            results.append(ExactCodeSearchResult(matches=[], complete=False))
    return _InstallationSearches(results=results, shed=shed, answered=answered)


def source_detection_enabled(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            SOURCE_DETECTION_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
        )
    )


def _report(team: Team, detection: SourceDetection, *, attempt: int, installations: int) -> None:
    try:
        posthoganalytics.capture(
            distinct_id=str(team.uuid),
            event=SOURCE_DETECTED_EVENT,
            properties={
                "team_id": team.id,
                "outcome": detection.outcome,
                "attempt": attempt,
                "installations": installations,
                "candidate_files": detection.candidate_files,
            },
            groups=groups(team=team),
        )
    except Exception as e:
        logger.warning("code_email_source_report_failed", team_id=team.id, error=str(e))
