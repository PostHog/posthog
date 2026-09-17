"""Facade re-export of the GitHub client surface the repo-config views need.

The install/sync endpoints talk to GitHub directly: they list a user's installations and
accessible repositories during setup, before any repo config exists to read from. That is
presentation-layer work against an external service, not product data, so it crosses as
functions rather than contracts.

Lives apart from ``api.py`` for the same reason ``tasks.py`` does — the client pulls the
GitHub App auth stack, which must stay off the module review_hog's settings serializer
imports on every request.
"""

from typing import Any

from django.db import IntegrityError, router, transaction
from django.utils import timezone

from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.scoping.manager import resolve_effective_team_id

from products.stamphog.backend.activity_logging import (
    log_repo_config_bulk_update,
    log_repo_configs_created,
    suppress_created_activity,
)
from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.api import _repo_config_to_dto
from products.stamphog.backend.facade.contracts import StamphogGitHubError
from products.stamphog.backend.logic.github_client import (
    exchange_oauth_code_for_user_token,
    list_user_accessible_repositories,
    list_user_installations,
    user_can_access_installation,
)
from products.stamphog.backend.models import StamphogRepoConfig

__all__ = [
    "StamphogGitHubError",
    "sync_installation_repositories",
    "exchange_oauth_code_for_user_token",
    "list_user_accessible_repositories",
    "list_user_installations",
    "user_can_access_installation",
]

# How many repo-config rows go into one INSERT. An installation can expose thousands of
# repositories, and every row in a statement adds its columns to that statement's bind-parameter
# list, so the batch is chunked to stay clear of Postgres' per-statement parameter ceiling.
_CREATE_BATCH_SIZE = 500


def _adopt_preexisting_config(team_id: int, repository: str, installation_id: str) -> StamphogRepoConfig | None:
    """Bind a manually-created (installation-less) config to a now-verified installation.

    Reached when the installation sync hits the unique (team, repository) constraint: a row for this
    repo already exists on the team, created through the plain API/MCP path with a blank installation_id
    — or bound to a PREVIOUS installation after an uninstall/reinstall cycle (each reinstall mints a new
    installation id, and the app can only be installed once per repo, so the old binding is dead).
    Stamp the verified installation onto it so it starts resolving webhooks again, rather than reporting
    it skipped and leaving it unbound forever. Safe to rebind: this helper is team-scoped and only
    reached from the sync flow, which already proved the caller owns the NEW installation.

    A never-bound placeholder binds DISABLED and with its review policy back at the defaults: every
    one of those fields was set by whoever created the row, who never proved GitHub access to the
    repo — otherwise a member could pre-arm ``enabled=True`` for a private repo and have reviews
    start (under the syncing teammate's identity) the moment someone else completes the install, or
    pre-select label mode with a label nobody uses so the row reviews nothing once a manager enables
    it. Reinstall rows keep their settings: they were configured while verifiably bound to a real
    installation.
    """
    # Writer pin: the writer-side unique constraint is what routed us here, so the row exists on the
    # writer — a lagged reader missing it would mark the repo skipped and leave it unbound forever.
    existing = (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(provider="github", repository=repository)
        .first()
    )
    if existing is None:
        return None
    if existing.installation_id != installation_id:
        update_fields = ["installation_id", "updated_at"]
        if not existing.installation_id:
            existing.enabled = False
            existing.digest_enabled = False
            # Read the defaults off the model so the reset cannot drift from what a fresh row gets.
            existing.review_mode = StamphogRepoConfig._meta.get_field("review_mode").get_default()
            existing.trigger_label = StamphogRepoConfig._meta.get_field("trigger_label").get_default()
            update_fields += ["enabled", "digest_enabled", "review_mode", "trigger_label"]
        existing.installation_id = installation_id
        try:
            existing.save(update_fields=update_fields)
        except IntegrityError:
            return None
    return existing


def sync_installation_repositories(
    team_id: int,
    *,
    installation_id: str,
    user_token: str,
    connected_by_user_id: int,
) -> tuple[list[contracts.RepoConfigDTO], list[str]]:
    """Bind every user-accessible repo in one installation to the team. Returns (synced, skipped).

    Enumerate with the USER token, not the app installation token: bind only the repos this user can
    actually reach in the installation, so proving access to one repo can't attach repos they can't
    see. The app-token list would return every repo the installer selected regardless of this user.
    Raises :class:`StamphogGitHubError` on an enumeration failure so the caller fails closed.

    Every synced row records the caller as its connecting user — the identity the review sandbox's
    short-lived gateway token is minted under. Re-syncs re-stamp on purpose: the latest human to
    prove installation ownership is the right principal (the original installer may be long gone).
    """
    repositories = list_user_accessible_repositories(installation_id, user_token)
    # bulk_create below skips ProductTeamModel.save(), which is what normally rewrites team_id to the
    # canonical id, so resolve it here instead and pass canonical=True from then on. for_team()
    # resolves per call, so this also holds the whole sync to one Team lookup.
    team_id = resolve_effective_team_id(team_id)
    # Pin the reads and the writes to the model's routed DB (stamphog_db_writer when the product DB
    # is configured, else default). A lagged reader would miss a row this sync just wrote and try to
    # create it again.
    write_db = router.db_for_write(StamphogRepoConfig)

    # One read for the whole installation rather than one per repository. An organization that
    # installs the App on all of its repositories can expose thousands of them, and a per-repository
    # round trip made the request cost grow with that count until it ran past the gateway timeout.
    # A re-sync now finds every row here and does no write work at all.
    resolved: dict[str, StamphogRepoConfig] = {
        config.repository: config
        for config in StamphogRepoConfig.objects.for_team(team_id, canonical=True)
        .using(write_db)
        .filter(provider="github", installation_id=installation_id, repository__in=repositories)
    }

    created_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    # Create the rows without a per-row audit write and log the creates in one batch below; an
    # adoption still logs its own diff. The batch runs in a finally: a row that is already committed
    # when the work dies would otherwise never be logged, and a retry sees it as pre-existing, so its
    # creation is lost for good.
    try:
        with suppress_created_activity():
            candidates = [
                StamphogRepoConfig(
                    # for_team() scopes a read but not row creation, so team_id is explicit here.
                    team_id=team_id,
                    provider="github",
                    installation_id=installation_id,
                    repository=full_name,
                    # Bind disabled: an installation can surface hundreds of repos, so connect them
                    # but don't start reviewing until a human toggles each one on.
                    enabled=False,
                    # The connecting user is seeded here, so a new row does not need the restamp
                    # below and its activity log shows one "connected" entry instead of a create
                    # plus a connector change.
                    connected_by_user_id=connected_by_user_id,
                )
                for full_name in repositories
                if full_name not in resolved
            ]
            if candidates:
                # The rows and the record of which ones this call inserted have to commit together.
                # An unwrapped bulk_create commits on its own, so a failure of the read-back would
                # leave the rows in place with created_rows empty, and the retry would then see them
                # as pre-existing and never write their audit entries.
                with transaction.atomic(using=write_db):
                    # ON CONFLICT DO NOTHING, so both unique constraints still decide which rows land
                    # and a concurrent sync of the same installation cannot make this raise.
                    # bulk_create also sends no per-row save signal, which is the audit outcome the
                    # suppression above gives the rest of this block.
                    StamphogRepoConfig.objects.for_team(team_id, canonical=True).using(write_db).bulk_create(
                        candidates, ignore_conflicts=True, batch_size=_CREATE_BATCH_SIZE
                    )
                    # The primary keys are generated in Python, so reading them back says exactly
                    # which candidates this call inserted. ignore_conflicts reports nothing itself,
                    # and a row that lost to a conflict needs the per-row resolution below.
                    inserted_ids = set(
                        StamphogRepoConfig.objects.for_team(team_id, canonical=True)
                        .using(write_db)
                        .filter(id__in=[candidate.id for candidate in candidates])
                        .values_list("id", flat=True)
                    )
                # Recorded before the resolution below, so a failure in it still logs every row that
                # landed.
                created_rows.extend(
                    {"id": candidate.id, "repository": candidate.repository}
                    for candidate in candidates
                    if candidate.id in inserted_ids
                )
                for candidate in candidates:
                    if candidate.id in inserted_ids:
                        resolved[candidate.repository] = candidate
                        continue
                    # A unique constraint holds this repository. Either the same team already has it
                    # under a different installation_id, which is the manually-created config (blank
                    # installation) finally being bound, so adopt it; or another team owns the triple,
                    # which stays skipped.
                    adopted = _adopt_preexisting_config(team_id, candidate.repository, installation_id)
                    if adopted is None:
                        skipped.append(candidate.repository)
                    else:
                        resolved[candidate.repository] = adopted
    finally:
        log_repo_configs_created(
            team_id, created_rows, user=get_current_user(), was_impersonated=get_was_impersonated()
        )

    # Answer in the order GitHub listed the repositories, which is the order the connect screen renders.
    synced = [resolved[full_name] for full_name in repositories if full_name in resolved]
    # A row this call inserted already carries the caller as its connector, so only a pre-existing row
    # can need a restamp. Leaving the new ones out also keeps a first-time sync of a large installation
    # from locking every row it just created.
    created_ids = {row["id"] for row in created_rows}
    restamp_ids = [config.id for config in synced if config.id not in created_ids]

    if restamp_ids:
        with transaction.atomic(using=write_db):
            # Lock the rows and re-read the connector rather than trusting the objects above: two
            # syncs of the same installation running at once both hold the same stale value, so a
            # real A -> B handover would be logged twice, as C -> A and C -> B.
            locked = (
                StamphogRepoConfig.objects.for_team(team_id, canonical=True)
                .using(write_db)
                .select_for_update()
                .filter(id__in=restamp_ids)
                .values_list("id", "repository", "connected_by_user_id")
            )
            restamped: list[dict[str, Any]] = [
                {"id": row_id, "repository": repository, "connected_by_user_id": connector}
                for row_id, repository, connector in locked
                if connector != connected_by_user_id
            ]
            if restamped:
                # .update() bypasses auto_now, so updated_at is set by hand.
                StamphogRepoConfig.objects.for_team(team_id, canonical=True).filter(
                    id__in=[row["id"] for row in restamped]
                ).update(connected_by_user_id=connected_by_user_id, updated_at=timezone.now())
                # update() bypasses the model signal, so the change is logged here.
                log_repo_config_bulk_update(
                    team_id,
                    restamped,
                    {"connected_by_user_id": connected_by_user_id},
                    user=get_current_user(),
                    was_impersonated=get_was_impersonated(),
                )

    return [_repo_config_to_dto(c) for c in synced], skipped
