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

from products.stamphog.backend.activity_logging import log_repo_config_bulk_update
from products.stamphog.backend.facade import contracts
from products.stamphog.backend.facade.api import _repo_config_to_dto
from products.stamphog.backend.facade.contracts import StamphogGitHubError
from products.stamphog.backend.logic.github_client import (
    exchange_oauth_code_for_user_token,
    list_user_accessible_repositories,
    list_user_installations,
    user_can_access_installation,
)
from products.stamphog.backend.logic.installations import record_installation_sync, reset_unverified_review_policy
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

    Reached when the installation sync lists a repository the team already has a row for under
    another installation_id: a row created through the plain API/MCP path with a blank installation_id
    — or one bound to a PREVIOUS installation after an uninstall/reinstall cycle (each reinstall mints a new
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
            update_fields += ["enabled", "digest_enabled", *reset_unverified_review_policy(existing)]
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
    """Record the repos this user can reach in one installation. Returns (synced, skipped).

    Enumerate with the USER token, not the app installation token: record only the repos this user can
    actually reach in the installation, so proving access to one repo can't expose repos they can't
    see. The app-token list would return every repo the installer selected regardless of this user.
    Raises :class:`StamphogGitHubError` on an enumeration failure so the caller fails closed.

    The listed repos go into the team's installation snapshot, and no repo config is created: a member
    adds the ones to review from the snapshot. `synced` is the team's existing rows for listed repos,
    bound to this installation. `skipped` is the listed repos another team holds under it.

    Every synced row records the caller as its connecting user — the identity the review sandbox's
    short-lived gateway token is minted under. Re-syncs re-stamp on purpose: the latest human to
    prove installation ownership is the right principal (the original installer may be long gone).
    """
    repositories = list_user_accessible_repositories(installation_id, user_token)
    # for_team() resolves the canonical team per call, so resolve it once here and pass canonical=True
    # from then on.
    team_id = resolve_effective_team_id(team_id)
    # Pin the reads and the writes to the model's routed DB (stamphog_db_writer when the product DB
    # is configured, else default). A lagged reader would miss a row a concurrent sync just bound.
    write_db = router.db_for_write(StamphogRepoConfig)

    record_installation_sync(team_id, installation_id, repositories, connected_by_user_id=connected_by_user_id)

    # One read for the whole installation rather than one per repository. An organization that
    # installs the App on all of its repositories can expose thousands of them, and a per-repository
    # round trip made the request cost grow with that count until it ran past the gateway timeout.
    team_rows = (
        StamphogRepoConfig.objects.for_team(team_id, canonical=True)
        .using(write_db)
        .filter(provider="github", repository__in=repositories)
    )
    resolved: dict[str, StamphogRepoConfig] = {}
    skipped: set[str] = set(
        StamphogRepoConfig.objects.unscoped()
        .using(write_db)
        .filter(provider="github", installation_id=installation_id, repository__in=repositories)
        .exclude(team_id=team_id)
        .values_list("repository", flat=True)
    )
    for config in team_rows:
        if config.installation_id == installation_id:
            resolved[config.repository] = config
            continue
        # A manual placeholder or a row from a previous installation. Adopting it binds the row to the
        # verified installation, and a conflict means another team owns the triple, so it stays skipped.
        adopted = _adopt_preexisting_config(team_id, config.repository, installation_id)
        if adopted is None:
            skipped.add(config.repository)
        else:
            resolved[config.repository] = adopted

    # Answer in the order GitHub listed the repositories, which is the order the connect screen renders.
    synced = [resolved[full_name] for full_name in repositories if full_name in resolved]
    restamp_ids = [config.id for config in synced]

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

    return [_repo_config_to_dto(c) for c in synced], [full_name for full_name in repositories if full_name in skipped]
