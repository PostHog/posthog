"""Find the file that sends a code email by searching the team's GitHub installations for its key.

Detection links a key only when the strict search finds exactly one call site and every installation
answered in full. Anything less leaves the key for a person to link.
"""

import re
from collections.abc import Sequence
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
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.integration.github import GitHubInstallationAccessFetchError
from posthog.models.integration.github_code_search import (
    MAX_LITERAL_LENGTH,
    ExactCodeSearchResult,
    GitHubExactCodeSearch,
    MatchedLine,
)
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.messaging.backend.facade.contracts import CodeEmailSourceOrigin
from products.messaging.backend.models import TransactionalEmailKey

logger = structlog.get_logger(__name__)

SOURCE_DETECTION_FLAG = "workflows-code-email-source-detection"
SOURCE_DETECTED_EVENT = "transactional email source detected"

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


_UNTOUCHED = Q(source_url__isnull=True, source_origin__isnull=True)


@frozen
class CallSite:
    repository: str
    path: str
    line: int

    @property
    def url(self) -> str:
        # GitHub resolves HEAD to the repository's default branch, which is the branch code search indexes.
        return f"https://github.com/{self.repository}/blob/HEAD/{quote(self.path)}#L{self.line}"


@frozen
class SourceDetection:
    outcome: SourceDetectionOutcome
    call_site: CallSite | None
    candidate_files: int


def rank_call_sites(results: Sequence[ExactCodeSearchResult], key: str, *, shed: bool) -> SourceDetection:
    """Pick the one call site to link from each installation's search.

    ``shed`` is True when the egress budget refused an installation's search, so that installation has no result.
    """
    # The matched line must pass the key as the template key's value. Without this, a key used for something else
    # near or inside a send call, such as the subject of a send of another key, links that other email's file.
    key_argument = re.compile(rf"""(?<![\w-])(?i:template[_-]?key)['"]?\s*(?::|=>|=)\s*['"`]{re.escape(key)}['"`]""")
    candidates = [match for result in results for match in result.matches if not _is_skipped_path(match.path)]
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


def _sends_key(line: MatchedLine, key_argument: re.Pattern[str]) -> bool:
    argument = key_argument.search(line.text)
    context = line.context.split("\n")
    if argument is None or line.text not in context:
        return False
    before_key = "\n".join([*context[: context.index(line.text)], line.text[: argument.start()]])
    return any(_still_open(before_key[call.end() :]) for call in _SEND_CALL.finditer(before_key))


def _still_open(after_call: str) -> bool:
    """Whether the call a send-call match belongs to is still open at the end of ``after_call``.

    ``emails.send(`` opens its own call, which must not close again. A raw ``send/email`` URL sits inside a call
    that opened before it, which must not close either.
    """
    depth = 0
    opened = False
    for char in after_call:
        if char == "(":
            depth += 1
            opened = True
        elif char == ")":
            depth -= 1
            if depth < 0 or (opened and depth == 0):
                return False
    return True


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
    person, too long to search, or the team has no GitHub installation.
    """
    team = Team.objects.filter(id=team_id).first()
    if team is None or not _detection_enabled(team):
        return None
    keys = TransactionalEmailKey.objects.for_team(team_id, canonical=True)
    key = keys.filter(_UNTOUCHED, id=key_id).values_list("key", flat=True).first()
    if key is None or len(key) > MAX_LITERAL_LENGTH:
        return None
    integrations = IntegrationManager.github.oauth.list(team_id)
    if not integrations:
        return None

    results: list[ExactCodeSearchResult] = []
    shed = False
    for integration in integrations:
        github = GitHubIntegration(integration, source="transactional_email_source", priority=Priority.BATCH)
        try:
            results.append(GitHubExactCodeSearch(github).find(key))
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

    detection = rank_call_sites(results, key, shed=shed)
    if detection.call_site is not None:
        # A person may link or unlink the key while the search runs, and their choice wins.
        written = keys.filter(_UNTOUCHED, id=key_id, team_id=team_id).update(
            source_url=detection.call_site.url, source_origin=CodeEmailSourceOrigin.DETECTED
        )
        if not written:
            detection = replace(detection, outcome="kept", call_site=None)
    _report(team, detection, attempt=attempt, installations=len(integrations))
    return detection


def source_detection_enabled(team_id: int) -> bool:
    team = Team.objects.filter(id=team_id).first()
    return team is not None and _detection_enabled(team)


def _detection_enabled(team: Team) -> bool:
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
