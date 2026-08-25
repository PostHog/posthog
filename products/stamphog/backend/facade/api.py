"""
Facade for stamphog.

The ONLY module other products are allowed to import.
Accept ids / frozen dataclasses, call into models, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypeVar, overload

from django.db import IntegrityError
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from ..logic.review_trigger import derive_review_trigger
from ..models import DigestRun, PullRequest, ReviewRun, StamphogRepoConfig
from . import contracts
from .enums import (
    TERMINAL_STATUSES,
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewMode,
    ReviewRunStatus,
    ReviewTrigger,
    ReviewVerdict,
)

logger = structlog.get_logger(__name__)

_DTO = TypeVar("_DTO")


class LazyDTOList(Sequence[_DTO]):
    """DTOs backed by a queryset, converted only for the rows a caller actually slices.

    A paginating view sizes the collection and then slices it, so a list endpoint reads one page
    out of the database rather than converting every matching row. Nothing but DTOs leaves the
    facade. Sizing goes through ``__len__``, which is a COUNT rather than a fetch.
    """

    def __init__(self, queryset: QuerySet, to_dto: Callable[[Any], _DTO]) -> None:
        self._queryset = queryset
        self._to_dto = to_dto

    def __len__(self) -> int:
        return self._queryset.count()

    def __iter__(self) -> Iterator[_DTO]:
        # Explicit: the Sequence mixin would iterate by index, one query per row.
        return (self._to_dto(row) for row in self._queryset)

    @overload
    def __getitem__(self, index: int) -> _DTO: ...

    @overload
    def __getitem__(self, index: slice) -> list[_DTO]: ...

    def __getitem__(self, index: int | slice) -> _DTO | list[_DTO]:
        rows = self._queryset[index]
        if isinstance(index, slice):
            return [self._to_dto(row) for row in rows]
        return self._to_dto(rows)


def _repo_config_to_dto(obj: StamphogRepoConfig) -> contracts.RepoConfigDTO:
    return contracts.RepoConfigDTO(
        id=obj.id,
        team_id=obj.team_id,
        provider=obj.provider,
        repository=obj.repository,
        enabled=obj.enabled,
        installation_id=obj.installation_id,
        digest_enabled=obj.digest_enabled,
        review_mode=obj.review_mode,
        trigger_label=obj.trigger_label,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _pull_request_to_dto(obj: PullRequest) -> contracts.PullRequestDTO:
    return contracts.PullRequestDTO(
        id=obj.id,
        team_id=obj.team_id,
        repo_config_id=obj.repo_config_id,
        repository=obj.repo_config.repository,
        pr_number=obj.pr_number,
        pr_url=obj.pr_url,
        title=obj.title,
        author_login=obj.author_login,
        head_branch=obj.head_branch,
        body_excerpt=obj.body_excerpt,
        additions=obj.additions,
        deletions=obj.deletions,
        changed_files=obj.changed_files,
        merge_commit_sha=obj.merge_commit_sha,
        merged_at=obj.merged_at,
        posted_comment_id=obj.posted_comment_id,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _digest_run_to_dto(obj: DigestRun) -> contracts.DigestRunDTO:
    return contracts.DigestRunDTO(
        id=obj.id,
        team_id=obj.team_id,
        audience_key=obj.audience_key,
        slack_channel_id=obj.slack_channel_id,
        slack_channel_name=obj.slack_channel_name,
        resolution_source=ChannelResolutionSource(obj.resolution_source),
        status=DigestRunStatus(obj.status),
        pr_count=obj.pr_count,
        summary=obj.summary,
        slack_message_ts=obj.slack_message_ts,
        error=obj.error,
        created_at=obj.created_at,
        posted_at=obj.posted_at,
    )


# A run dispatched from the inbox records its provenance on `output`. Both writers in tasks.py
# either omit the key or write a populated dict, so testing for the key and testing for truthiness
# agree — which is what lets the filter below stay in step with the derivation above it.
_SELF_DRIVING = Q(output__has_key="inbox_review")

# Preserves the caller's queryset type, so a team-scoped queryset stays team-scoped through the filter.
_RunQS = TypeVar("_RunQS", bound=QuerySet)


def _derive_trigger(obj: ReviewRun) -> ReviewTrigger:
    """Why stamphog looked at this PR. The rule itself lives in logic/review_trigger.py, because
    the reviewer invocation has to answer the same question before a run exists to read."""
    return derive_review_trigger(
        has_inbox_review=bool((obj.output or {}).get("inbox_review")),
        review_mode=obj.pull_request.repo_config.review_mode,
    )


def _filter_by_trigger(qs: _RunQS, trigger: str) -> _RunQS:
    """Narrow to one trigger, mirroring _derive_trigger in SQL.

    The trigger is not a column, so the precedence has to be spelled out twice. Keep the two in
    step: a run that reads as self-driving in the list must be reachable by that filter, or the
    filter quietly hides rows the caller just saw. An unrecognized value narrows to nothing rather
    than falling through to the unfiltered list.
    """
    if trigger == ReviewTrigger.SELF_DRIVING:
        return qs.filter(_SELF_DRIVING)
    if trigger == ReviewTrigger.LABEL:
        return qs.exclude(_SELF_DRIVING).filter(pull_request__repo_config__review_mode=ReviewMode.LABEL)
    if trigger == ReviewTrigger.ALL:
        return qs.exclude(_SELF_DRIVING).filter(pull_request__repo_config__review_mode=ReviewMode.ALL)
    return qs.none()


def _review_run_to_dto(obj: ReviewRun) -> contracts.ReviewRunDTO:
    return contracts.ReviewRunDTO(
        id=obj.id,
        team_id=obj.team_id,
        pull_request_id=obj.pull_request_id,
        repository=obj.pull_request.repo_config.repository,
        pr_number=obj.pull_request.pr_number,
        pr_url=obj.pull_request.pr_url,
        head_branch=obj.pull_request.head_branch,
        head_sha=obj.head_sha,
        status=ReviewRunStatus(obj.status),
        verdict=ReviewVerdict(obj.verdict),
        trigger=_derive_trigger(obj),
        title=obj.pull_request.title,
        author_login=obj.pull_request.author_login,
        delivery_id=obj.delivery_id,
        gate_result=obj.gate_result,
        output=obj.output,
        error=obj.error,
        posted_review_id=obj.posted_review_id,
        verdict_posted_at=obj.verdict_posted_at,
        approval_dismissed_at=obj.approval_dismissed_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        completed_at=obj.completed_at,
    )


def get_repo_config(team_id: int, repository: str) -> contracts.RepoConfigDTO | None:
    obj = StamphogRepoConfig.objects.for_team(team_id).filter(repository=repository).first()
    return _repo_config_to_dto(obj) if obj is not None else None


def has_reviewable_repo_config(team_id: int) -> bool:
    """Whether the team has at least one enabled repo config that hosted reviews can run on.

    The config must have been bound through the authenticated sync flow: a non-blank
    installation_id and a connecting user, because the sandbox LLM credential is minted under
    that user and reviews fail closed without one. The Code review scene disables its Stamphog
    inbox toggle when this is false, since the toggle would have nothing to act on.
    """
    return (
        StamphogRepoConfig.objects.for_team(team_id)
        .filter(enabled=True, connected_by_user_id__isnull=False)
        .exclude(installation_id="")
        .exists()
    )


def get_review_run(team_id: int, review_run_id: str) -> contracts.ReviewRunDTO | None:
    obj = (
        ReviewRun.objects.for_team(team_id).filter(id=review_run_id).select_related("pull_request__repo_config").first()
    )
    return _review_run_to_dto(obj) if obj is not None else None


def create_review_run(
    *,
    team_id: int,
    pull_request_id: str,
    head_sha: str,
    delivery_id: str | None = None,
) -> contracts.ReviewRunDTO:
    # Resolve the PR through the team scope rather than trusting the raw FK id: a caller passing
    # another team's pull_request_id would otherwise create a run whose reads follow the FK across
    # the tenant boundary (get_review_run would surface the other team's repo and PR details).
    pull_request = PullRequest.objects.for_team(team_id).get(id=pull_request_id)
    obj = ReviewRun.objects.for_team(team_id).create(
        team_id=team_id,
        pull_request=pull_request,
        head_sha=head_sha,
        delivery_id=delivery_id,
    )
    return _review_run_to_dto(obj)


def get_digest_run(team_id: int, digest_run_id: str) -> contracts.DigestRunDTO | None:
    obj = DigestRun.objects.for_team(team_id).filter(id=digest_run_id).first()
    return _digest_run_to_dto(obj) if obj is not None else None


def get_pull_request(team_id: int, pull_request_id: str) -> contracts.PullRequestDTO | None:
    obj = PullRequest.objects.for_team(team_id).filter(id=pull_request_id).select_related("repo_config").first()
    return _pull_request_to_dto(obj) if obj is not None else None


# --- Repo configs ---


def list_repo_configs(team_id: int) -> LazyDTOList[contracts.RepoConfigDTO]:
    qs = StamphogRepoConfig.objects.for_team(team_id).order_by("repository")
    return LazyDTOList(qs, _repo_config_to_dto)


def create_repo_config(
    team_id: int,
    *,
    provider: str = "github",
    repository: str,
    enabled: bool = True,
    digest_enabled: bool = False,
    review_mode: str | None = None,
    trigger_label: str | None = None,
) -> contracts.RepoConfigDTO:
    """Create a repo config, refusing a repository another team already owns.

    installation_id is never accepted here: only the verified sync flow may bind one, so a manual
    config carries a blank installation and won't resolve webhooks until synced. A blank
    installation proves no ownership, so it never claims a repo across teams — which is why the
    cross-team check (and the DB constraint behind it) only applies to non-empty installations.
    """
    fields: dict[str, object] = {"provider": provider, "repository": repository, "enabled": enabled}
    fields["digest_enabled"] = digest_enabled
    if review_mode is not None:
        fields["review_mode"] = review_mode
    if trigger_label is not None:
        fields["trigger_label"] = trigger_label
    # unique_stamphog_installation_repo backs this at the DB level, so a race that slips past the
    # read still fails closed on the create below and surfaces as the same domain error.
    try:
        obj = StamphogRepoConfig.objects.for_team(team_id).create(team_id=team_id, **fields)
    except IntegrityError:
        raise contracts.RepoAlreadyClaimedError(repository)
    return _repo_config_to_dto(obj)


def update_repo_config(team_id: int, config_id: str, **fields: object) -> contracts.RepoConfigDTO:
    """Apply an update, superseding in-flight runs when the repo goes from enabled to disabled.

    provider and repository are the config's identity — they resolve inbound webhooks and anchor
    every PullRequest/ReviewRun FK — so they are never updatable here.
    """
    fields.pop("provider", None)
    fields.pop("repository", None)
    fields.pop("installation_id", None)
    obj = StamphogRepoConfig.objects.for_team(team_id).get(id=config_id)
    was_enabled = obj.enabled
    for name, value in fields.items():
        setattr(obj, name, value)
    obj.save()
    if was_enabled and not obj.enabled:
        _supersede_active_runs(team_id, obj)
    return _repo_config_to_dto(obj)


def disable_repo_config(team_id: int, config_id: str) -> None:
    """Soft-disable rather than hard-delete (same tombstone pattern as digest channels).

    A hard delete cascades away the PRs and review runs — including posted_review_id — so a push to
    a previously approved PR could no longer resolve the config or dismiss the stale approval,
    leaving it satisfying required reviews forever. A disabled row keeps webhooks resolvable, and
    the disabled-repo skip path retracts standing approvals on the next head change.
    """
    obj = StamphogRepoConfig.objects.for_team(team_id).get(id=config_id)
    obj.enabled = False
    obj.digest_enabled = False
    obj.save(update_fields=["enabled", "digest_enabled", "updated_at"])
    _supersede_active_runs(team_id, obj)


def _supersede_active_runs(team_id: int, config: StamphogRepoConfig) -> None:
    # Disabling (or tombstone-deleting) a repo must also stop reviews already in flight: their
    # workflows never re-check enabled, so a queued/reviewing run could still post an approval
    # after an admin removed stamphog from the repo. Every workflow step bails on SUPERSEDED.
    superseded = (
        ReviewRun.objects.for_team(team_id)
        .filter(pull_request__repo_config=config)
        .exclude(status__in=TERMINAL_STATUSES)
        .update(status=ReviewRunStatus.SUPERSEDED, updated_at=timezone.now())
    )
    if superseded:
        logger.info("stamphog_repo_disable_superseded_runs", repository=config.repository, superseded=superseded)


# --- Read lists for the product's own views ---


def list_review_runs(
    team_id: int,
    *,
    repository: str | None = None,
    pr_number: int | None = None,
    status: str | None = None,
    trigger: str | None = None,
) -> LazyDTOList[contracts.ReviewRunDTO]:
    qs = ReviewRun.objects.for_team(team_id).select_related("pull_request__repo_config").order_by("-created_at")
    if repository:
        qs = qs.filter(pull_request__repo_config__repository=repository)
    if pr_number is not None:
        qs = qs.filter(pull_request__pr_number=pr_number)
    if status:
        qs = qs.filter(status=status)
    if trigger:
        qs = _filter_by_trigger(qs, trigger)
    return LazyDTOList(qs, _review_run_to_dto)


def list_pull_requests(
    team_id: int,
    *,
    pr_number: int | None = None,
    merged: bool | None = None,
) -> LazyDTOList[contracts.PullRequestDTO]:
    qs = PullRequest.objects.for_team(team_id).select_related("repo_config").order_by("-created_at")
    if pr_number is not None:
        qs = qs.filter(pr_number=pr_number)
    if merged is not None:
        qs = qs.filter(merged_at__isnull=not merged)
    return LazyDTOList(qs, _pull_request_to_dto)


# --- Digest runs ---


def list_digest_runs(team_id: int, *, slack_channel_id: str | None = None) -> LazyDTOList[contracts.DigestRunDTO]:
    qs = DigestRun.objects.for_team(team_id).order_by("-created_at")
    if slack_channel_id is not None:
        qs = qs.filter(slack_channel_id=slack_channel_id)
    return LazyDTOList(qs, _digest_run_to_dto)
