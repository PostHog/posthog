"""Facade re-export of the GitHub client surface the repo-config views need.

The install/sync endpoints talk to GitHub directly: they list a user's installations and
accessible repositories during setup, before any repo config exists to read from. That is
presentation-layer work against an external service, not product data, so it crosses as
functions rather than contracts.

Lives apart from ``api.py`` for the same reason ``tasks.py`` does — the client pulls the
GitHub App auth stack, which must stay off the module review_hog's settings serializer
imports on every request.
"""

from django.db import IntegrityError, router, transaction
from django.utils import timezone

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

    A never-bound placeholder binds DISABLED: its enabled flags were set by whoever created the row,
    who never proved GitHub access to the repo — otherwise a member could pre-arm ``enabled=True``
    for a private repo and have reviews start (under the syncing teammate's identity) the moment
    someone else completes the install. Reinstall rows keep their settings: they were configured
    while verifiably bound to a real installation.
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
            update_fields += ["enabled", "digest_enabled"]
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
    skipped: list[str] = []
    # Bind the per-row savepoint to the model's routed DB (stamphog_db_writer when the product DB is
    # configured, else default) — a bare atomic() opens on the default connection, so the get_or_create
    # would run outside any transaction on the product DB.
    write_db = router.db_for_write(StamphogRepoConfig)
    for full_name in repositories:
        # Per-row savepoint: an IntegrityError only rolls back that row, leaving the rest of the
        # batch (and the outer autocommit context) intact.
        try:
            with transaction.atomic(using=write_db):
                config, _ = StamphogRepoConfig.objects.for_team(team_id).get_or_create(
                    provider="github",
                    installation_id=installation_id,
                    repository=full_name,
                    # for_team() scopes the read but not row creation, so team_id is explicit here.
                    # Bind disabled: an installation can surface hundreds of repos, so connect them
                    # but don't start reviewing until a human toggles each on. enabled only seeds new
                    # rows; an existing row's toggle is never flipped.
                    defaults={"team_id": team_id, "enabled": False},
                )
        except IntegrityError:
            # The unique (team, repository) constraint tripped: a same-team row for this repo already
            # exists under a different installation_id — the manually-created config (blank
            # installation) finally being bound. Adopt it instead of skipping; only a real conflict
            # (already bound to another installation) stays skipped.
            adopted = _adopt_preexisting_config(team_id, full_name, installation_id)
            if adopted is None:
                skipped.append(full_name)
            else:
                synced.append(adopted)
            continue
        synced.append(config)

    # .update() bypasses auto_now, so updated_at is set by hand.
    restamp_ids = [config.id for config in synced if config.connected_by_user_id != connected_by_user_id]
    if restamp_ids:
        StamphogRepoConfig.objects.for_team(team_id).filter(id__in=restamp_ids).update(
            connected_by_user_id=connected_by_user_id, updated_at=timezone.now()
        )

    return [_repo_config_to_dto(c) for c in synced], skipped
