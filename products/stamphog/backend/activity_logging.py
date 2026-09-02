"""Activity-log receiver and bulk-write helpers for stamphog repo configs.

The module stays import-light because `apps.py` imports it at `ready()`, and a repo config is
written from web requests, webhook Celery tasks, and management commands alike. Every call passes
`using=`, because the repo config lives on the stamphog database: the audit row must wait for that
connection's commit, and it must be dropped when that connection rolls back.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.db import router

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import (
    AuditableScope,
    Detail,
    LogActivityEntry,
    Trigger,
    bulk_log_activity,
    changes_between,
    dict_changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team import Team

from products.stamphog.backend.models import StamphogRepoConfig

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

# The fields a webhook disable changes on a repo config. A caller reads them from the writer
# before the update, so the logged change list carries the real previous values.
DISABLED_FIELDS = ("enabled", "digest_enabled")


def _organization_id_for_team(team_id: int) -> UUID | None:
    # A repo config has no `team` accessor: team_id is a plain integer, and Team lives on the
    # main database. One lookup per logging call, never one per row.
    return Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()


@mutable_receiver(model_activity_signal, sender=StamphogRepoConfig)
def handle_stamphog_repo_config_change(
    sender: type[StamphogRepoConfig],
    scope: AuditableScope,
    before_update: StamphogRepoConfig | None,
    after_update: StamphogRepoConfig | None,
    activity: str,
    user: "User | None",
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return

    # The receiver runs inside save(), after the row is committed on the product database. An error
    # here must not escape: the caller's post-save work (superseding in-flight runs on a disable)
    # would be skipped for a row that is already written.
    try:
        changes = changes_between(scope, previous=before_update, current=after_update)
        if activity == "updated" and not changes:
            # log_activity drops an update that moved nothing, so the organization lookup is wasted.
            return

        log_activity(
            organization_id=_organization_id_for_team(instance.team_id),
            team_id=instance.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=instance.id,
            scope=scope,
            activity=activity,
            # A row created by the API carries no installation until a sync binds it, so the describer
            # must not call it connected.
            detail=Detail(
                changes=changes,
                name=instance.repository,
                type="connected" if instance.installation_id else "placeholder",
            ),
            using=router.db_for_write(StamphogRepoConfig),
        )
    except Exception as e:
        logger.warning("stamphog_activity_log_failed", team_id=instance.team_id, item_id=str(instance.id), exception=e)
        capture_exception(e)
        if settings.TEST:
            raise


def log_repo_config_bulk_update(
    team_id: int,
    before_rows: list[dict[str, Any]],
    after_values: dict[str, Any],
    *,
    user: "User | None" = None,
    was_impersonated: bool = False,
    trigger: Trigger | None = None,
) -> None:
    """Log a queryset update of repo configs, which the model signal cannot see.

    `before_rows` holds the rows as the writer had them before the update, each with `id`,
    `repository`, and the updated fields. `after_values` holds what the update set on all of
    them. A row whose values did not move produces no log row.
    """
    # Same rule as the receiver: the rows are already written, so a failed audit write must not
    # escape into the caller.
    try:
        entries: list[LogActivityEntry] = []

        for row in before_rows:
            changes = dict_changes_between(
                "StamphogRepoConfig",
                previous={field: row.get(field) for field in after_values},
                new=after_values,
            )
            if not changes:
                continue
            entries.append(
                LogActivityEntry(
                    organization_id=None,
                    team_id=team_id,
                    user=user,
                    item_id=row["id"],
                    scope="StamphogRepoConfig",
                    activity="updated",
                    detail=Detail(changes=changes, name=row["repository"], trigger=trigger),
                    was_impersonated=was_impersonated,
                )
            )

        if not entries:
            return

        # One lookup for the batch, and only when there is a row to write.
        organization_id = _organization_id_for_team(team_id)
        for entry in entries:
            entry["organization_id"] = organization_id

        bulk_log_activity(entries, using=router.db_for_write(StamphogRepoConfig))
    except Exception as e:
        logger.warning("stamphog_activity_log_failed", team_id=team_id, exception=e)
        capture_exception(e)
        if settings.TEST:
            raise


def log_repo_configs_disabled_by_webhook(
    team_id: int,
    before_rows: list[dict[str, Any]],
    *,
    delivery_id: str,
    action: str,
    installation_id: str,
) -> None:
    """Log the disable that a GitHub installation webhook applies with one queryset update.

    The row is a system row: a webhook carries no PostHog user. The trigger names the delivery, so
    a reader can tie every disabled repo back to the one GitHub event that caused it.
    """
    log_repo_config_bulk_update(
        team_id,
        before_rows,
        dict.fromkeys(DISABLED_FIELDS, False),
        trigger=Trigger(
            job_type="github_installation_webhook",
            job_id=delivery_id,
            payload={"action": action, "installation_id": installation_id},
        ),
    )
