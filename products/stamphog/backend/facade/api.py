"""
Facade for stamphog.

The ONLY module other products are allowed to import.
Accept ids / frozen dataclasses, call into models, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import Any, TypeVar, overload
from uuid import UUID

from django.db import IntegrityError, router, transaction
from django.db.models import (
    BooleanField,
    Count,
    Exists,
    ExpressionWrapper,
    F,
    Func,
    JSONField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.utils import timezone

import structlog

from ..logic.change_summary import ReviewedSummary, split_clauses
from ..logic.installations import reset_unverified_review_policy
from ..logic.merge_approval import approved_at_head, retained_at_head
from ..logic.review_trigger import derive_review_trigger
from ..logic.reviewer import parse_reviewer_output
from ..logic.routing.claims import is_stale_claim
from ..logic.routing.fork_labels import fork_labels
from ..logic.routing.owners_file import owners_file_status
from ..logic.scrubbing import neutralize_active_markdown, scrub_credentials
from ..models import (
    DigestRun,
    PullRequest,
    ReviewRun,
    RoutingRun,
    RoutingRunOwner,
    StamphogInstallation,
    StamphogRepoConfig,
)
from . import contracts
from .enums import (
    TERMINAL_STATUSES,
    ChannelResolutionSource,
    DigestRunStatus,
    LlmSkipReason,
    OwnerKind,
    OwnersFileStatus,
    PinReason,
    ReviewMode,
    ReviewRunStatus,
    ReviewTrigger,
    ReviewVerdict,
    RoutingMode,
    RoutingOwnerOutcome,
    RoutingOwnerReason,
    RoutingRunOrdering,
    RoutingScope,
    RoutingStatus,
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
        routing_mode=obj.routing_mode,
        routing_fork_labels=fork_labels(obj),
        review_on_clean_external_review=obj.review_on_clean_external_review,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _record_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _routing_to_dto(record: object) -> contracts.PullRequestRoutingDTO | None:
    """An allowlist of the routing record's scalars. The plan, the pins and the comment stay internal."""
    if not isinstance(record, dict):
        return None
    try:
        status = RoutingStatus(str(record.get("status")))
        mode = RoutingMode(str(record.get("mode")))
        scope = RoutingScope(record["scope"]) if record.get("scope") else None
    except ValueError:
        return None
    claimed = status in (RoutingStatus.ROUTING, RoutingStatus.REQUESTED)
    return contracts.PullRequestRoutingDTO(
        status=status,
        head_sha=str(record.get("head_sha") or ""),
        mode=mode,
        trigger=str(record.get("trigger") or ""),
        scope=scope,
        claim_expired=claimed and is_stale_claim(record),
        waiting_since=_record_time(record.get("waiting_since")),
        claimed_at=_record_time(record.get("claimed_at")),
        routed_at=_record_time(record.get("routed_at")),
        full_routed_head=str(record.get("full_routed_head") or ""),
        pinned_routed_head=str(record.get("pinned_routed_head") or ""),
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
        routing_mode=RoutingMode(obj.repo_config.routing_mode),
        routing=_routing_to_dto(obj.routing),
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
# Same shape for a manual request: request_manual_review writes a populated dict or no key at all.
_MANUAL = Q(output__has_key="manual_review")
# A silent run has no provenance dict. Its stamped trigger is the only record. Containment, not key
# equality: equality is NULL for a run without the key, and an exclude() would then drop that run.
_SILENT = Q(output__contains={"review_trigger": ReviewTrigger.REVIEWHOG_CLEAN.value})

# Preserves the caller's queryset type, so a team-scoped queryset stays team-scoped through the filter.
_RunQS = TypeVar("_RunQS", bound=QuerySet)


def _derive_trigger(
    obj: ReviewRun, *, has_inbox_review: bool, has_manual_review: bool, stamped_trigger: str | None
) -> ReviewTrigger:
    """Why stamphog looked at this PR. The rule itself lives in logic/review_trigger.py, because
    the reviewer invocation has to answer the same question before a run exists to read.

    Of the stamped triggers only a silent one is read, because ``_SILENT`` matches it in SQL. Every
    other trigger is derived, for the reason ``trigger_for_run`` gives.
    """
    if not (has_inbox_review or has_manual_review) and stamped_trigger == ReviewTrigger.REVIEWHOG_CLEAN:
        return ReviewTrigger.REVIEWHOG_CLEAN
    return derive_review_trigger(
        has_inbox_review=has_inbox_review,
        has_manual_review=has_manual_review,
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
    if trigger == ReviewTrigger.MANUAL:
        return qs.exclude(_SELF_DRIVING).filter(_MANUAL)
    if trigger == ReviewTrigger.REVIEWHOG_CLEAN:
        return qs.exclude(_SELF_DRIVING | _MANUAL).filter(_SILENT)
    if trigger == ReviewTrigger.LABEL:
        return qs.exclude(_SELF_DRIVING | _MANUAL | _SILENT).filter(
            pull_request__repo_config__review_mode=ReviewMode.LABEL
        )
    if trigger == ReviewTrigger.ALL:
        return qs.exclude(_SELF_DRIVING | _MANUAL | _SILENT).filter(
            pull_request__repo_config__review_mode=ReviewMode.ALL
        )
    return qs.none()


def _build_review_run_dto(obj: ReviewRun, *, output: dict[str, Any], trigger: ReviewTrigger) -> contracts.ReviewRunDTO:
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
        trigger=trigger,
        title=obj.pull_request.title,
        author_login=obj.pull_request.author_login,
        delivery_id=obj.delivery_id,
        gate_result=obj.gate_result,
        output=output,
        error=obj.error,
        posted_review_id=obj.posted_review_id,
        verdict_posted_at=obj.verdict_posted_at,
        approval_dismissed_at=obj.approval_dismissed_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
        completed_at=obj.completed_at,
    )


def _review_run_to_dto(obj: ReviewRun) -> contracts.ReviewRunDTO:
    output = obj.output or {}
    trigger = _derive_trigger(
        obj,
        has_inbox_review=bool(output.get("inbox_review")),
        has_manual_review=bool(output.get("manual_review")),
        stamped_trigger=output.get("review_trigger"),
    )
    return _build_review_run_dto(obj, output=output, trigger=trigger)


# Retrieve also parses the reviewer's reasoning out of its raw stdout.
_RETRIEVE_OUTPUT_KEYS = (*contracts.REVIEW_RUN_OUTPUT_SUMMARY_KEYS, "reviewer_raw")


def _slim_review_runs(qs: _RunQS, output_keys: tuple[str, ...]) -> _RunQS:
    """Skip the `output` column and read only `output_keys` and the trigger's provenance flags from it."""
    return qs.defer("output").annotate(
        **{f"slim_output_{key}": KeyTransform(key, "output") for key in output_keys},
        slim_has_inbox_review=ExpressionWrapper(_SELF_DRIVING, output_field=BooleanField()),
        slim_has_manual_review=ExpressionWrapper(_MANUAL, output_field=BooleanField()),
        slim_review_trigger=KeyTextTransform("review_trigger", "output"),
    )


def _slim_review_run_to_dto(obj: ReviewRun, output_keys: tuple[str, ...]) -> contracts.ReviewRunDTO:
    output = {key: value for key in output_keys if (value := getattr(obj, f"slim_output_{key}")) is not None}
    # _slim_review_runs annotates these, so the model type does not declare them.
    trigger = _derive_trigger(
        obj,
        has_inbox_review=obj.slim_has_inbox_review,  # type: ignore[attr-defined]
        has_manual_review=obj.slim_has_manual_review,  # type: ignore[attr-defined]
        stamped_trigger=obj.slim_review_trigger,  # type: ignore[attr-defined]
    )
    return _build_review_run_dto(obj, output=output, trigger=trigger)


def _review_run_list_row_to_dto(obj: ReviewRun) -> contracts.ReviewRunDTO:
    return _slim_review_run_to_dto(obj, contracts.REVIEW_RUN_OUTPUT_SUMMARY_KEYS)


def get_repo_config(team_id: int, repository: str) -> contracts.RepoConfigDTO | None:
    obj = StamphogRepoConfig.objects.for_team(team_id).filter(repository=repository).first()
    return _repo_config_to_dto(obj) if obj is not None else None


def get_repo_config_by_id(team_id: int, config_id: str) -> contracts.RepoConfigDTO | None:
    """Resolve one config by its primary key, or None when the team has no such row.

    An id that is not a UUID is a miss rather than an error, because the value comes straight off
    the URL and Django raises on a malformed one before the query runs.
    """
    try:
        parsed_id = UUID(config_id)
    except ValueError:
        return None
    obj = StamphogRepoConfig.objects.for_team(team_id).filter(id=parsed_id).first()
    return _repo_config_to_dto(obj) if obj is not None else None


def check_owners_file(config: contracts.RepoConfigDTO) -> OwnersFileStatus:
    """Whether the repo's default branch has the root owners.yaml that reviewer requests need.

    Makes one GitHub call with the repo's installation token, so callers ask only on demand.
    """
    return owners_file_status(config.id, config.repository, config.installation_id)


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
    """One run for the API. Its `output` carries only the summary keys and `reviewer_raw`."""
    qs = ReviewRun.objects.for_team(team_id).filter(id=review_run_id).select_related("pull_request__repo_config")
    obj = _slim_review_runs(qs, _RETRIEVE_OUTPUT_KEYS).first()
    return _slim_review_run_to_dto(obj, _RETRIEVE_OUTPUT_KEYS) if obj is not None else None


def _clean_reviewer_text(text: str) -> str:
    # The same redaction the posted GitHub review gets. An MCP client can render this as markdown,
    # which fetches images on render the way GitHub's camo proxy does.
    return neutralize_active_markdown(scrub_credentials(text))


def get_review_reasoning(run: contracts.ReviewRunDTO) -> contracts.ReviewReasoningDTO:
    """The reviewer's reasoning for a run, parsed from its stored output.

    This is the text stamphog posts as its GitHub review. The raw reviewer stdout it is parsed
    from never leaves the facade. All fields are None until the reviewer has run.
    """
    raw = (run.output or {}).get("reviewer_raw")
    if not isinstance(raw, str) or not raw:
        return contracts.ReviewReasoningDTO()
    try:
        parsed = parse_reviewer_output(raw)
    except (AttributeError, TypeError, ValueError):
        # A crashed or version-skewed engine can print a malformed verdict. Retrieve must still answer.
        logger.warning("stamphog_review_reasoning_unparseable", review_run_id=str(run.id))
        return contracts.ReviewReasoningDTO()
    return contracts.ReviewReasoningDTO(
        reasoning=_clean_reviewer_text(parsed.reasoning),
        showstoppers=[_clean_reviewer_text(item) for item in parsed.showstoppers],
        review_body=_clean_reviewer_text(parsed.review_body),
        change_summary=_clean_reviewer_text(parsed.change_summary),
    )


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
    routing_mode: str | None = None,
    routing_fork_labels: dict[str, str] | None = None,
    review_on_clean_external_review: bool | None = None,
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
    if routing_mode is not None:
        fields["routing_mode"] = routing_mode
    if routing_fork_labels is not None:
        fields["routing_fork_labels"] = routing_fork_labels
    if review_on_clean_external_review is not None:
        fields["review_on_clean_external_review"] = review_on_clean_external_review
    # unique_stamphog_installation_repo backs this at the DB level, so a race that slips past the
    # read still fails closed on the create below and surfaces as the same domain error.
    try:
        obj = StamphogRepoConfig.objects.for_team(team_id).create(team_id=team_id, **fields)
    except IntegrityError:
        raise contracts.RepoAlreadyClaimedError(repository)
    return _repo_config_to_dto(obj)


def list_available_repositories(team_id: int, *, search: str = "", limit: int) -> contracts.AvailableRepositoriesDTO:
    """Repositories in the team's installation snapshots that the team has not added yet.

    A repository another team holds under the same installation is left out too, because the
    cross-team unique constraint would refuse it. ``search`` is a case-insensitive substring.
    """
    # A record without a connecting user cannot mint review credentials, so add_repository refuses it.
    snapshots = list(
        StamphogInstallation.objects.for_team(team_id)
        .filter(provider="github", connected_by_user_id__isnull=False)
        .values_list("installation_id", "repositories")
    )
    if not snapshots:
        return contracts.AvailableRepositoriesDTO(repositories=[], total_count=0, has_installation=False)

    added = set(StamphogRepoConfig.objects.for_team(team_id).values_list("repository", flat=True))
    candidates = {
        (installation_id, repository)
        for installation_id, repositories in snapshots
        for repository in repositories
        if repository not in added
    }
    # The one cross-team read here: which of these repositories another team already owns. It
    # returns only names this team's own snapshots hold, so nothing about the other team leaks.
    claimed = set(
        StamphogRepoConfig.objects.unscoped()
        .filter(
            provider="github",
            installation_id__in={installation_id for installation_id, _ in candidates},
            repository__in={repository for _, repository in candidates},
        )
        .exclude(team_id=team_id)
        .values_list("installation_id", "repository")
    )
    addable = {repository for _, repository in candidates - claimed}
    needle = search.strip().lower()
    available = sorted((repository for repository in addable if needle in repository.lower()), key=str.lower)
    return contracts.AvailableRepositoriesDTO(
        repositories=available[:limit], total_count=len(available), has_installation=True
    )


def add_repository(team_id: int, repository: str) -> contracts.AddRepositoryResultDTO:
    """Turn reviews on for a repository from the team's installation snapshot.

    The installation and the connecting user come from the snapshot record, never from the caller:
    the record is what a member's GitHub token proved. A row the team already has for the
    repository is turned on and bound to that installation rather than refused, so a paused or
    removed repository can be added again.
    """
    write_db = router.db_for_write(StamphogRepoConfig)
    try:
        with transaction.atomic(using=write_db):
            # Writer pin: this read decides which installation the row binds to. The lock is the one a
            # removal or uninstall webhook takes first. Without it, a webhook can drop the repository
            # and tombstone the team's rows between this read and the create below, and the new row
            # then stays enabled for a repository that left the installation. A record without a
            # connecting user cannot mint review credentials, so a member has to sync it first.
            installation = (
                StamphogInstallation.objects.for_team(team_id)
                .using(write_db)
                .select_for_update()
                .filter(provider="github", repositories__contains=[repository], connected_by_user_id__isnull=False)
                .order_by("-updated_at")
                .first()
            )
            if installation is None:
                raise contracts.RepositoryNotInstalledError(repository)
            existing = (
                StamphogRepoConfig.objects.for_team(team_id)
                .using(write_db)
                .select_for_update()
                .filter(repository=repository)
                .first()
            )
            if existing is None:
                config = (
                    StamphogRepoConfig.objects.for_team(team_id)
                    .using(write_db)
                    .create(
                        # for_team() scopes a read but not row creation, so team_id is explicit here.
                        team_id=team_id,
                        provider="github",
                        repository=repository,
                        installation_id=installation.installation_id,
                        enabled=True,
                        connected_by_user_id=installation.connected_by_user_id,
                    )
                )
                return contracts.AddRepositoryResultDTO(config=_repo_config_to_dto(config), created=True)

            update_fields = ["enabled", "updated_at"]
            if existing.installation_id != installation.installation_id:
                # A reinstall row keeps its settings, because a verified binding configured them.
                if not existing.installation_id:
                    update_fields += reset_unverified_review_policy(existing)
                existing.installation_id = installation.installation_id
                update_fields.append("installation_id")
            existing.connected_by_user_id = installation.connected_by_user_id
            update_fields.append("connected_by_user_id")
            existing.enabled = True
            existing.save(update_fields=update_fields)
            return contracts.AddRepositoryResultDTO(config=_repo_config_to_dto(existing), created=False)
    except IntegrityError:
        # unique_stamphog_installation_repo: another team holds this repository under the installation.
        raise contracts.RepoAlreadyClaimedError(repository)


def update_repo_config(team_id: int, config_id: str, **fields: object) -> contracts.RepoConfigDTO:
    """Apply an update, superseding in-flight runs when the repo goes from enabled to disabled.

    provider and repository are the config's identity — they resolve inbound webhooks and anchor
    every PullRequest/ReviewRun FK — so they are never updatable here.
    """
    fields.pop("provider", None)
    fields.pop("repository", None)
    fields.pop("installation_id", None)
    write_db = router.db_for_write(StamphogRepoConfig)
    # One transaction for the read, the save and the supersede. The row is locked because a save
    # writes every field: two overlapping PATCHes that each read first would otherwise overwrite
    # each other from stale objects, and each would log only the change it thinks it made. The
    # supersede belongs here too, because a caller must never observe a disabled repo whose
    # in-flight runs are still live, and the activity-log receiver then waits for this commit
    # rather than running its cross-database write between the two statements.
    with transaction.atomic(using=write_db):
        obj = StamphogRepoConfig.objects.for_team(team_id).using(write_db).select_for_update().get(id=config_id)
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
    write_db = router.db_for_write(StamphogRepoConfig)
    # Same locked transaction as update_repo_config, for the same reasons.
    with transaction.atomic(using=write_db):
        obj = StamphogRepoConfig.objects.for_team(team_id).using(write_db).select_for_update().get(id=config_id)
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
    return LazyDTOList(_slim_review_runs(qs, contracts.REVIEW_RUN_OUTPUT_SUMMARY_KEYS), _review_run_list_row_to_dto)


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


# --- Reviewer routing runs ---


_ROUTING_RUN_COLUMNS = (
    "id",
    "team_id",
    "pull_request",
    "head_sha",
    "mode",
    "trigger",
    "scope",
    "fork",
    "llm_skipped",
    "model",
    "files_truncated",
    "additions_resolved",
    "owners_sha",
    "created_at",
)

_ROUTING_PULL_REQUEST_COLUMNS = (
    "pr_number",
    "title",
    "author_login",
    "pr_url",
    "merged_at",
    "additions",
    "deletions",
    "changed_files",
)


class _LargestFiles(Func):
    """An owner's 3 most changed files from its stored `files` list, computed in Postgres.

    The list reads only these, so a large pull request's full file lists never leave the database.
    Ties keep the stored order. The template is a constant and its one expression is a column.
    """

    template = (
        "(SELECT COALESCE(jsonb_agg(entry.file ORDER BY entry.lines DESC, entry.position), '[]'::jsonb) "
        "FROM (SELECT file, position, (file->>'additions')::int + (file->>'deletions')::int AS lines "
        "FROM jsonb_array_elements(%(expressions)s) WITH ORDINALITY AS stored(file, position) "
        "ORDER BY lines DESC, position LIMIT 3) AS entry)"
    )
    output_field = JSONField()


def _routing_file_to_dto(file: dict[str, Any]) -> contracts.RoutingFileDTO:
    return contracts.RoutingFileDTO(
        path=file["path"],
        previous_path=file["previous_path"],
        status=file["status"],
        additions=file["additions"],
        deletions=file["deletions"],
        # Runs recorded before the field have no entry.
        owners_source=file.get("owners_source"),
    )


def _routing_owner_to_dto(
    row: RoutingRunOwner, *, with_files: bool, reviewed: ReviewedSummary
) -> contracts.RoutingRunOwnerDTO:
    return contracts.RoutingRunOwnerDTO(
        owner=row.owner,
        kind=OwnerKind(row.kind),
        outcome=RoutingOwnerOutcome(row.outcome),
        reason=RoutingOwnerReason(row.reason),
        model_reason=row.model_reason,
        pins=[contracts.RoutingPinDTO(reason=PinReason(pin["reason"]), path=pin["path"]) for pin in row.pins],
        files=[_routing_file_to_dto(file) for file in row.files] if with_files else [],
        # Annotated by _routing_runs.
        top_files=[_routing_file_to_dto(file) for file in row.top_files],  # type: ignore[attr-defined]
        lines=row.lines,
        file_count=row.file_count,
        # Clauses are keyed by team slug, which is how owners.yaml spells a team owner.
        summary=reviewed.clauses.get(row.owner.casefold()),
    )


def _routing_run_to_dto(row: RoutingRun, *, with_files: bool = False) -> contracts.RoutingRunDTO:
    # The stored size is 0 until the merge, which would read as an empty pull request.
    merged = row.pull_request.merged_at is not None
    # Annotated by _routing_runs. Cleaned before the split, so the whole summary and every clause are.
    reviewed = split_clauses(_clean_reviewer_text(row.change_summary or ""))  # type: ignore[attr-defined]
    return contracts.RoutingRunDTO(
        id=row.id,
        team_id=row.team_id,
        repository=row.pull_request.repo_config.repository,
        pr_number=row.pull_request.pr_number,
        pull_request=contracts.RoutingPullRequestDTO(
            title=row.pull_request.title,
            author=row.pull_request.author_login,
            url=row.pull_request.pr_url,
            merged_at=row.pull_request.merged_at,
            additions=row.pull_request.additions if merged else None,
            deletions=row.pull_request.deletions if merged else None,
            changed_files=row.pull_request.changed_files if merged else None,
            summary=reviewed.whole_change or None,
            approved_by_stamphog=row.approved_by_stamphog,  # type: ignore[attr-defined]
        ),
        head_sha=row.head_sha,
        mode=RoutingMode(row.mode),
        trigger=row.trigger,
        scope=RoutingScope(row.scope),
        fork=row.fork,
        llm_skipped=LlmSkipReason(row.llm_skipped) if row.llm_skipped else None,
        model=row.model,
        files_truncated=row.files_truncated,
        additions_resolved=row.additions_resolved,
        owners_sha=row.owners_sha,
        owners=[_routing_owner_to_dto(owner, with_files=with_files, reviewed=reviewed) for owner in row.owners.all()],
        created_at=row.created_at,
    )


def _routing_runs(team_id: int, *, with_files: bool) -> QuerySet[RoutingRun]:
    owners = (
        RoutingRunOwner.objects.for_team(team_id, canonical=True)
        .annotate(top_files=_LargestFiles("files"))
        .order_by("owner")
    )
    if not with_files:
        # A large pull request gives every owner a long file list, which only the single-run read returns.
        owners = owners.defer("files")
    review_runs = ReviewRun.objects.for_team(team_id, canonical=True).filter(
        pull_request_id=OuterRef("pull_request_id")
    )
    # Head-independent on purpose: a summary from an earlier head still says what the change does,
    # and the merged head is not stored to match it against.
    change_summary = (
        review_runs.filter(status=ReviewRunStatus.COMPLETED)
        .exclude(change_summary="")
        .order_by("-created_at")
        .values("change_summary")[:1]
    )
    approval = review_runs.filter(approved_at_head(OuterRef("head_sha")) | retained_at_head(OuterRef("head_sha")))
    return (
        RoutingRun.objects.for_team(team_id, canonical=True)
        .select_related("pull_request__repo_config")
        # The pull request row carries the routing record and the description, which the reads never use.
        .only(
            *_ROUTING_RUN_COLUMNS,
            *(f"pull_request__{column}" for column in _ROUTING_PULL_REQUEST_COLUMNS),
            "pull_request__repo_config__repository",
        )
        .annotate(change_summary=Subquery(change_summary), approved_by_stamphog=Exists(approval))
        .prefetch_related(Prefetch("owners", queryset=owners))
    )


def _filter_by_merge(
    qs: QuerySet[RoutingRun], *, merged: bool | None, merged_after: datetime | None, merged_before: datetime | None
) -> QuerySet[RoutingRun]:
    if merged is not None:
        qs = qs.filter(pull_request__merged_at__isnull=not merged)
    if merged_after is not None:
        qs = qs.filter(pull_request__merged_at__gte=merged_after)
    if merged_before is not None:
        qs = qs.filter(pull_request__merged_at__lt=merged_before)
    return qs


def _runs_deciding_about(
    team_id: int, *, owner: str | None, outcomes: list[RoutingOwnerOutcome] | None, reason: RoutingOwnerReason | None
) -> QuerySet:
    # One subquery on the owners table, so a run that cut one owner and requested another never
    # matches `owner` plus `outcome` across two rows. The (team_id, owner) index answers `owner`.
    owners = RoutingRunOwner.objects.for_team(team_id, canonical=True)
    if owner:
        owners = owners.filter(owner=owner)
    if outcomes:
        owners = owners.filter(outcome__in=outcomes)
    if reason:
        owners = owners.filter(reason=reason)
    return owners.values("run_id")


def list_routing_runs(
    team_id: int,
    *,
    repository: str | None = None,
    pr_number: int | None = None,
    owner: str | None = None,
    outcome: list[RoutingOwnerOutcome] | None = None,
    reason: RoutingOwnerReason | None = None,
    head_sha: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    latest_per_pr: bool = False,
    merged: bool | None = None,
    merged_after: datetime | None = None,
    merged_before: datetime | None = None,
    ordering: RoutingRunOrdering = RoutingRunOrdering.NEWEST_RUN,
) -> LazyDTOList[contracts.RoutingRunDTO]:
    """The team's reviewer routing runs with their decision for every owner but no file lists.

    Newest run first by default, or newest merge first with `ordering`.

    `owner` keeps the runs that decided about that owner, as owners.yaml spells it (`team-devex`, `@alice`).
    `outcome` (any of several) and `reason` keep the runs where one owner row has them, the same row as `owner` when it is set.
    `latest_per_pr` keeps one run per pull request, its newest, and the other filters judge that run.
    `team_id` must be canonical, as every view passes it, so the reads skip the team lookup.
    """
    qs = _routing_runs(team_id, with_files=False)
    # Run ids are uuid7, so the id breaks a created_at tie in time order and a page boundary never splits a tie.
    if ordering == RoutingRunOrdering.NEWEST_MERGE:
        qs = qs.order_by(F("pull_request__merged_at").desc(nulls_last=True), "-created_at", "-id")
    else:
        qs = qs.order_by("-created_at", "-id")
    if latest_per_pr:
        # The subquery carries none of the other filters, so they judge the newest run instead of choosing it.
        newest_run = (
            RoutingRun.objects.for_team(team_id, canonical=True)
            .filter(pull_request_id=OuterRef("pull_request_id"))
            .order_by("-created_at", "-id")
            .values("id")[:1]
        )
        qs = qs.filter(id=Subquery(newest_run))
    if repository:
        qs = qs.filter(pull_request__repo_config__repository=repository)
    if pr_number is not None:
        qs = qs.filter(pull_request__pr_number=pr_number)
    if head_sha:
        qs = qs.filter(head_sha=head_sha)
    if created_after is not None:
        qs = qs.filter(created_at__gte=created_after)
    if created_before is not None:
        qs = qs.filter(created_at__lt=created_before)
    qs = _filter_by_merge(qs, merged=merged, merged_after=merged_after, merged_before=merged_before)
    if owner or outcome or reason:
        qs = qs.filter(id__in=_runs_deciding_about(team_id, owner=owner, outcomes=outcome, reason=reason))
    return LazyDTOList(qs, _routing_run_to_dto)


def get_routing_run(team_id: int, routing_run_id: str) -> contracts.RoutingRunDTO | None:
    """One routing run with the changed files each owner owns. `team_id` must be canonical."""
    row = _routing_runs(team_id, with_files=True).filter(id=routing_run_id).first()
    return _routing_run_to_dto(row, with_files=True) if row is not None else None


def list_routing_owners(team_id: int, *, created_after: datetime) -> list[contracts.RoutingOwnerCountDTO]:
    """Every owner a routing run decided about since `created_after`, most pull requests first.

    `pr_count` counts distinct pull requests, so a pull request routed several times counts once.
    `team_id` must be canonical.
    """
    rows = (
        RoutingRunOwner.objects.for_team(team_id, canonical=True)
        .filter(run__created_at__gte=created_after)
        .values("owner", "kind")
        .annotate(pr_count=Count("run__pull_request_id", distinct=True))
        .order_by("-pr_count", "owner")
    )
    return [
        contracts.RoutingOwnerCountDTO(owner=row["owner"], kind=OwnerKind(row["kind"]), pr_count=row["pr_count"])
        for row in rows
    ]


# --- Digest runs ---


def list_digest_runs(team_id: int, *, slack_channel_id: str | None = None) -> LazyDTOList[contracts.DigestRunDTO]:
    qs = DigestRun.objects.for_team(team_id).order_by("-created_at")
    if slack_channel_id is not None:
        qs = qs.filter(slack_channel_id=slack_channel_id)
    return LazyDTOList(qs, _digest_run_to_dto)
