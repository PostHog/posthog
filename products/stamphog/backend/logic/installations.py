"""Installation snapshots, the repositories a team can add to stamphog, and binding rows to them.

A snapshot holds only repositories a member proved access to with their own GitHub token. Every
write locks the installation row, because a sync and a webhook for the same installation can run at
once and each one rewrites the whole list.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import router, transaction

from ..models import StamphogInstallation, StamphogRepoConfig


def reset_unverified_review_policy(config: StamphogRepoConfig) -> list[str]:
    """Put a placeholder's review policy back at the model defaults. Returns the fields it changed.

    A placeholder (blank installation) was configured by someone who never proved GitHub access.
    A label mode with a label nobody uses would otherwise go live, reviewing nothing, the moment
    the row binds to a real installation and turns on.
    """
    # Read the defaults off the model so the reset cannot drift from what a fresh row gets.
    config.review_mode = StamphogRepoConfig._meta.get_field("review_mode").get_default()
    config.trigger_label = StamphogRepoConfig._meta.get_field("trigger_label").get_default()
    return ["review_mode", "trigger_label"]


def _write_db() -> str:
    return router.db_for_write(StamphogInstallation)


def record_installation_sync(
    team_id: int, installation_id: str, repositories: Iterable[str], *, connected_by_user_id: int
) -> None:
    """Merge a member's listed repositories into the team's snapshot, and make them its connector.

    The merge is a union, so a sync by a member who sees fewer repositories does not hide the ones
    a teammate listed. Repositories leave the snapshot only through the removal webhooks.
    """
    write_db = _write_db()
    with transaction.atomic(using=write_db):
        installation, _ = (
            StamphogInstallation.objects.for_team(team_id)
            .using(write_db)
            .select_for_update()
            # for_team() scopes a read but not row creation, so team_id is explicit here.
            .get_or_create(team_id=team_id, provider="github", installation_id=installation_id)
        )
        installation.repositories = sorted(set(installation.repositories) | set(repositories))
        installation.connected_by_user_id = connected_by_user_id
        installation.save(update_fields=["repositories", "connected_by_user_id", "updated_at"])


def remove_from_installation_snapshot(team_id: int, installation_id: str, repositories: Iterable[str]) -> None:
    removed = set(repositories)
    if not removed:
        return
    write_db = _write_db()
    with transaction.atomic(using=write_db):
        installation = (
            StamphogInstallation.objects.for_team(team_id)
            .using(write_db)
            .select_for_update()
            .filter(provider="github", installation_id=installation_id)
            .first()
        )
        if installation is None:
            return
        installation.repositories = sorted(set(installation.repositories) - removed)
        installation.save(update_fields=["repositories", "updated_at"])


def delete_installation(team_id: int, installation_id: str) -> None:
    StamphogInstallation.objects.for_team(team_id).using(_write_db()).filter(
        provider="github", installation_id=installation_id
    ).delete()
