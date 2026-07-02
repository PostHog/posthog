from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import requests
from temporalio import activity

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationBase, GitHubIntegrationError
from posthog.models.scoping import team_scope
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.models import CodePrSnapshot
from products.tasks.backend.temporal.code_workstreams.activities.github_resolution import resolve_github_integration
from products.tasks.backend.temporal.code_workstreams.activities.load_pr_urls import PrRef


@dataclass
class PollTeamPullRequestsInput:
    team_id: int
    prs: list[PrRef]


@dataclass
class PollTeamPullRequestsOutput:
    polled: int
    updated: int
    rate_limited: bool


def _fingerprint(url: str, updated_at: str | None) -> str:
    return hashlib.sha256(f"{url}|{updated_at or ''}".encode()).hexdigest()


def _resolve_integration(ref: PrRef) -> GitHubIntegrationBase | None:
    return resolve_github_integration(ref.github_integration_id, ref.github_user_integration_id)


@activity.defn
@close_db_connections
def poll_team_pull_requests(input: PollTeamPullRequestsInput) -> PollTeamPullRequestsOutput:
    return poll_pull_requests_for_team(input.team_id, input.prs, heartbeat=activity.heartbeat)


def poll_pull_requests_for_team(
    team_id: int,
    prs: list[PrRef],
    *,
    heartbeat: Callable[[int], None] | None = None,
) -> PollTeamPullRequestsOutput:
    integrations: dict[str, GitHubIntegrationBase | None] = {}
    polled = 0
    updated = 0
    rate_limited = False

    for index, ref in enumerate(prs):
        if heartbeat is not None:
            heartbeat(index)

        cache_key = (
            f"i:{ref.github_integration_id}"
            if ref.github_integration_id is not None
            else f"u:{ref.github_user_integration_id}"
        )
        try:
            if cache_key not in integrations:
                integrations[cache_key] = _resolve_integration(ref)
            integration = integrations[cache_key]
        except ObjectDoesNotExist:
            activity.logger.warning("code_workstreams_pr_integration_missing", pr_url=ref.pr_url)
            continue
        except (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException) as e:
            # A token-refresh failure for one PR must not abort the whole activity (which would
            # block the team's rebuild this cycle); skip this PR and move on.
            activity.logger.warning("code_workstreams_pr_integration_unavailable", pr_url=ref.pr_url, error=str(e))
            continue
        if integration is None:
            continue

        try:
            snap = integration.get_pull_request_snapshot(ref.pr_url)
        except GitHubRateLimitError:
            activity.logger.warning("code_workstreams_pr_rate_limited", team_id=team_id, polled=polled)
            rate_limited = True
            break
        except GitHubIntegrationError as e:
            activity.logger.warning("code_workstreams_pr_fetch_failed", pr_url=ref.pr_url, error=str(e))
            continue
        except Exception as e:
            activity.logger.warning("code_workstreams_pr_fetch_error", pr_url=ref.pr_url, error=str(e))
            continue

        polled += 1
        if not snap.get("success"):
            continue

        fingerprint = _fingerprint(ref.pr_url, snap.get("updated_at"))
        with team_scope(team_id):
            existing = CodePrSnapshot.objects.filter(team_id=team_id, pr_url=ref.pr_url).first()
            if existing is not None and existing.fingerprint == fingerprint:
                continue
            CodePrSnapshot.objects.update_or_create(
                team_id=team_id,
                pr_url=ref.pr_url,
                defaults={
                    "github_integration_id": ref.github_integration_id,
                    "number": snap.get("number") or 0,
                    "title": snap.get("title") or "",
                    "state": snap["state"],
                    "ci_status": snap["ci_status"],
                    "review_decision": snap.get("review_decision"),
                    "unresolved_threads": snap.get("unresolved_threads") or 0,
                    "mergeable": snap.get("mergeable"),
                    "author_login": snap.get("author_login"),
                    "head_branch": snap.get("head_branch"),
                    "requested_reviewer_logins": snap.get("requested_reviewer_logins") or [],
                    "pr_updated_at": parse_datetime(snap["updated_at"]) if snap.get("updated_at") else None,
                    "fingerprint": fingerprint,
                    "fetched_at": timezone.now(),
                },
            )
            updated += 1

    return PollTeamPullRequestsOutput(polled=polled, updated=updated, rate_limited=rate_limited)
