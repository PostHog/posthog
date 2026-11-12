"""Find the file that sends a code email by searching the team's GitHub installations for its key.

Detection links a key only when the strict search finds exactly one call site and every installation
answered in full. Anything less leaves the key for a person to link, who can run the same search and pick a file.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from django.db.models import Q

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
    CONTEXT_LINES,
    ExactCodeMatch,
    ExactCodeSearchResult,
    GitHubExactCodeSearch,
    MatchedLine,
    is_searchable_literal,
)
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.messaging.backend.facade.contracts import (
    CodeEmailSourceCandidate,
    CodeEmailSourceCandidates,
    CodeEmailSourceKeyUnsearchable,
    CodeEmailSourceOrigin,
    CodeEmailSourceSearchUnavailable,
)
from products.messaging.backend.models import TransactionalEmailKey

logger = structlog.get_logger(__name__)

# Target it by organization: detection checks it for a team with no person, and the picker's button for a person.
SOURCE_DETECTION_FLAG = "workflows-code-email-source-detection"
SOURCE_DETECTED_EVENT = "transactional email source detected"
# After this, the picker's search starts no new GitHub request. One already running finishes, so a slow GitHub can add
# that request's timeout and its retry.
SOURCE_SEARCH_SECONDS = 15

# "kept" means the search found one call site, but a person linked or unlinked the key before detection could write it.
SourceDetectionOutcome = Literal["linked", "kept", "several", "none", "incomplete", "budget"]
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
_SKIPPED_FILE_NAME_PREFIXES = ("test_",)
_SKIPPED_FILE_NAME_SUFFIXES = ("_spec.rb",)
# The send calls of PostHog's SDKs, and the raw API route. A matched line's context holds up to five lines on
# either side, so a key passed a few lines below the call still counts.
_SEND_CALL = re.compile(
    r"emails\.send|emails\(\)(?:\.|->)send|Emails\(\)\.Send|Emails\.SendAsync|Emails\.send|send/email"
)
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|/?\*)")
_TEMPLATE_KEY_NAME = r"""(?<![\w-])(?i:template[_-]?key)['"]?\s*(?::|=>|=)"""
_TEMPLATE_KEY_ARGUMENT = re.compile(_TEMPLATE_KEY_NAME)


_UNTOUCHED = Q(source_url__isnull=True, source_origin__isnull=True)


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
    # A failed or timed-out installation is in ``results`` as an empty, incomplete search. A shed one is left out.
    results: list[ExactCodeSearchResult]
    shed: bool
    answered: int


@frozen
class SourceDetection:
    outcome: SourceDetectionOutcome
    call_site: CallSite | None
    candidate_files: int


def rank_call_sites(results: Sequence[ExactCodeSearchResult], key: str, *, shed: bool) -> SourceDetection:
    """Pick the one call site to link from each installation's search.

    ``shed`` is True when the egress budget refused an installation's search, so that installation has no result.
    """
    key_argument = _key_argument(key)
    candidates = _kept_matches(results)
    call_sites = [
        CallSite(repository=match.repository, path=match.path, line=line.number)
        for match in candidates
        for line in match.lines
        if _sends_key(line, key_argument)
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


def _key_argument(key: str) -> re.Pattern[str]:
    # The matched line must pass the key as the template key's value. Without this, a key used for something else
    # near or inside a send call, such as the subject of a send of another key, links that other email's file.
    return re.compile(rf"""{_TEMPLATE_KEY_NAME}\s*['"`]{re.escape(key)}['"`]""")


def _sends_key(line: MatchedLine, key_argument: re.Pattern[str]) -> bool:
    """Whether the key is the template key of the nearest send call above it.

    A template key argument between that call and the key belongs to that send, so the key belongs to something
    after it, such as an event. Nothing here reads parentheses or quotes, which a few lines of context can't parse.
    """
    argument = key_argument.search(line.text)
    context = line.context.split("\n")
    # By position, not text: an identical line above it, such as the key in a tags object, would shadow it.
    position = min(line.number - 1, CONTEXT_LINES)
    if argument is None or position >= len(context) or context[position] != line.text or _COMMENT_LINE.match(line.text):
        return False
    code_above = [text for text in context[:position] if not _COMMENT_LINE.match(text)]
    before_key = "\n".join([*code_above, line.text[: argument.start()]])
    calls = list(_SEND_CALL.finditer(before_key))
    return bool(calls) and _TEMPLATE_KEY_ARGUMENT.search(before_key, calls[-1].end()) is None


def _is_skipped_path(path: str) -> bool:
    *directories, name = PurePosixPath(path.lower()).parts
    return (
        bool(_SKIPPED_DIRECTORIES.intersection(directories))
        or any(part in name for part in _SKIPPED_FILE_NAME_PARTS)
        or name.startswith(_SKIPPED_FILE_NAME_PREFIXES)
        or name.endswith(_SKIPPED_FILE_NAME_SUFFIXES)
    )


def detect_code_email_source(team_id: int, key_id: UUID, *, attempt: int) -> SourceDetection | None:
    """Search the team's GitHub installations for a key and link the one file that sends it.

    Returns None when detection does not apply: the flag is off, the key is gone, already linked or unlinked by a
    person, a key GitHub can't search, or the team has no GitHub installation.
    """
    team = Team.objects.filter(id=team_id).first()
    if team is None or not _detection_enabled(team):
        return None
    keys = TransactionalEmailKey.objects.for_team(team_id, canonical=True)
    key = keys.filter(_UNTOUCHED, id=key_id).values_list("key", flat=True).first()
    if key is None or not is_searchable_literal(key):
        return None
    integrations = IntegrationManager.github.oauth.list(team_id)
    if not integrations:
        return None

    searches = _search_installations(team_id, integrations, key, priority=Priority.BATCH)
    detection = rank_call_sites(searches.results, key, shed=searches.shed)
    if detection.call_site is not None:
        # A person may link or unlink the key while the search runs, and their choice wins.
        written = keys.filter(_UNTOUCHED, id=key_id, team_id=team_id).update(
            source_url=detection.call_site.url, source_origin=CodeEmailSourceOrigin.DETECTED
        )
        if not written:
            detection = replace(detection, outcome="kept", call_site=None)
    _report(team, detection, attempt=attempt, installations=len(integrations))
    return detection


def find_source_candidates(
    team: Team, key: str, *, readable: Callable[[IntegrationRecord], bool]
) -> CodeEmailSourceCandidates:
    """Search the team's GitHub installations that ``readable`` lets the person see for a key, one candidate per file.

    Files with a send call come first. A search that runs out of time returns what it read, marked incomplete.
    Raises ``CodeEmailSourceKeyUnsearchable`` for a key GitHub can't search, and
    ``CodeEmailSourceSearchUnavailable`` when no installation answered.
    """
    if not is_searchable_literal(key):
        raise CodeEmailSourceKeyUnsearchable()
    integrations = [
        integration for integration in IntegrationManager.github.oauth.list(team.id) if readable(integration)
    ]
    if not integrations:
        return CodeEmailSourceCandidates(candidates=(), complete=True)
    searches = _search_installations(
        team.id, integrations, key, priority=Priority.NORMAL, deadline=time.monotonic() + SOURCE_SEARCH_SECONDS
    )
    if not searches.answered:
        raise CodeEmailSourceSearchUnavailable(shed=searches.shed)
    key_argument = _key_argument(key)
    candidates = [_candidate(match, key_argument) for match in _kept_matches(searches.results)]
    return CodeEmailSourceCandidates(
        candidates=tuple(sorted(candidates, key=lambda candidate: not candidate.call_site)),
        complete=not searches.shed and all(result.complete for result in searches.results),
    )


def _candidate(match: ExactCodeMatch, key_argument: re.Pattern[str]) -> CodeEmailSourceCandidate:
    line = next((line for line in match.lines if _sends_key(line, key_argument)), match.lines[0])
    return CodeEmailSourceCandidate(
        repository=match.repository,
        path=match.path,
        line=line.number,
        url=_file_url(match.repository, match.path, line.number),
        call_site=_sends_key(line, key_argument),
    )


def _search_installations(
    team_id: int,
    integrations: Sequence[IntegrationRecord],
    key: str,
    *,
    priority: Priority,
    deadline: float | None = None,
) -> _InstallationSearches:
    results: list[ExactCodeSearchResult] = []
    shed = False
    answered = 0
    for integration in integrations:
        if deadline is not None and time.monotonic() >= deadline:
            results.append(ExactCodeSearchResult(matches=[], complete=False))
            continue
        github = GitHubIntegration(integration, source="transactional_email_source", priority=priority)
        try:
            results.append(GitHubExactCodeSearch(github).find(key, deadline=deadline))
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


def source_detection_enabled(team_id: int, *, only_locally: bool = False) -> bool:
    team = Team.objects.filter(id=team_id).first()
    return team is not None and _detection_enabled(team, only_locally=only_locally)


def _detection_enabled(team: Team, *, only_locally: bool = False) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            SOURCE_DETECTION_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            send_feature_flag_events=False,
            only_evaluate_locally=only_locally,
        )
    )


def _report(team: Team, detection: SourceDetection, *, attempt: int, installations: int) -> None:
    try:
        with ph_scoped_capture() as capture:
            capture(
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
