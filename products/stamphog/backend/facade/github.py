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
    synced: list[StamphogRepoConfig] = []
    created_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    # Bind the per-row savepoint to the model's routed DB (stamphog_db_writer when the product DB is
    # configured, else default) — a bare atomic() opens on the default connection, so the get_or_create
    # would run outside any transaction on the product DB.
    write_db = router.db_for_write(StamphogRepoConfig)
    # One installation can expose thousands of repositories. Let the loop create the rows without a
    # per-row audit write and log the creates in one batch below; an adoption still logs its own diff.
    # The batch runs in a finally: a row that is already committed when the loop dies would otherwise
    # never be logged, and a retry sees it as pre-existing, so its creation is lost for good.
    try:
        with suppress_created_activity():
            for full_name in repositories:
                # Per-row savepoint: an IntegrityError only rolls back that row, leaving the rest of the
                # batch (and the outer autocommit context) intact.
                try:
                    with transaction.atomic(using=write_db):
                        config, was_created = StamphogRepoConfig.objects.for_team(team_id).get_or_create(
                            provider="github",
                            installation_id=installation_id,
                            repository=full_name,
                            # for_team() scopes the read but not row creation, so team_id is explicit
                            # here. Bind disabled: an installation can surface hundreds of repos, so
                            # connect them but don't start reviewing until a human toggles each on.
                            # enabled only seeds new rows; an existing row's toggle is never flipped.
                            # The connecting user is seeded here too, so a new row does not need the
                            # restamp below and its activity log shows one "connected" entry instead of
                            # a create plus a connector change.
                            defaults={
                                "team_id": team_id,
                                "enabled": False,
                                "connected_by_user_id": connected_by_user_id,
                            },
                        )
                except IntegrityError:
                    # The unique (team, repository) constraint tripped: a same-team row for this repo
                    # already exists under a different installation_id — the manually-created config
                    # (blank installation) finally being bound. Adopt it instead of skipping; only a
                    # real conflict (already bound to another installation) stays skipped.
                    adopted = _adopt_preexisting_config(team_id, full_name, installation_id)
                    if adopted is None:
                        skipped.append(full_name)
                    else:
                        synced.append(adopted)
                    continue
                synced.append(config)
                if was_created:
                    created_rows.append({"id": config.id, "repository": config.repository})
    finally:
        log_repo_configs_created(
            team_id, created_rows, user=get_current_user(), was_impersonated=get_was_impersonated()
        )

    if synced:
        with transaction.atomic(using=write_db):
            # Lock the rows and re-read the connector rather than trusting the objects above: two
            # syncs of the same installation running at once both hold the same stale value, so a
            # real A -> B handover would be logged twice, as C -> A and C -> B.
            locked = (
                StamphogRepoConfig.objects.for_team(team_id)
                .using(write_db)
                .select_for_update()
                .filter(id__in=[c.id for c in synced])
                .values_list("id", "repository", "connected_by_user_id")
            )
            restamped: list[dict[str, Any]] = [
                {"id": row_id, "repository": repository, "connected_by_user_id": connector}
                for row_id, repository, connector in locked
                if connector != connected_by_user_id
            ]
            if restamped:
                # .update() bypasses auto_now, so updated_at is set by hand.
                StamphogRepoConfig.objects.for_team(team_id).filter(id__in=[row["id"] for row in restamped]).update(
                    connected_by_user_id=connected_by_user_id, updated_at=timezone.now()
                )
                # update() bypasses the model signal, so the change is logged here.
                log_repo_config_bulk_update(
                    team_id,
                    restamped,
                    {"connected_by_user_id": connected_by_user_id},
                    user=get_current_user(),
                    was_impersonated=get_was_impersonated(),
                )

    return [_repo_config_to_dto(c) for c in synced], skipped
