"""Activity-log receiver and bulk-write helpers for stamphog repo configs.

The module stays import-light because `apps.py` imports it at `ready()`, and a repo config is
written from web requests, webhook Celery tasks, and management commands alike. Every call passes
`using=`, because the repo config lives on the stamphog database: the audit row must wait for that
connection's commit, and it must be dropped when that connection rolls back.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.db import router, transaction

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

# Set while a caller creates repo configs in bulk and logs them itself. Per task, not per process,
# so one request cannot silence another's audit rows.
_created_activity_suppressed: ContextVar[bool] = ContextVar("stamphog_created_activity_suppressed", default=False)


@contextmanager
def suppress_created_activity() -> Iterator[None]:
    """Stop the receiver writing one row per create inside this block.

    The installation sync creates a row per repository, and one installation can expose thousands of
    them. Each receiver call is a Team lookup, an insert and an internal event, in the request. The
    caller logs the batch itself instead. Updates still log per row: an adoption is rare and its diff
    is what a reader wants. A ContextVar, not `mute_selected_signals()`, because that flag is
    process-wide and would silence every other request the process serves at that moment.
    """
    token = _created_activity_suppressed.set(True)
    try:
        yield
    finally:
        _created_activity_suppressed.reset(token)


def _organization_id_for_team(team_id: int) -> UUID | None:
    # A repo config has no `team` accessor: team_id is a plain integer, and Team lives on the
    # main database. One lookup per logging call, never one per row.
    return Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()


def _log_after_product_commit(write_row: Callable[[], None], *, write_db: str, **log_context: Any) -> None:
    """Run an audit write once the stamphog database commits, and never fail the caller.

    A caller wraps its product write and the work that must follow it (superseding in-flight runs)
    in one transaction. Keep the Team lookup and the insert out of that transaction: they run on
    the main database, and a stall there would hold the product row's lock and widen the window in
    which a run that is being stopped can still post its verdict. Deferring also drops the audit
    row when the product write rolls back.

    The guard mirrors `_handle_activity_log_transaction`, so with the setting off (tests) the write
    stays inline and the row is there right after the request.
    """

    def _guarded() -> None:
        # The product row is committed by now, so a failed audit write must not escape.
        try:
            write_row()
        except Exception as e:
            logger.warning("stamphog_activity_log_failed", exception=e, **log_context)
            capture_exception(e)
            if settings.TEST:
                raise

    if not transaction.get_autocommit(using=write_db) and getattr(
        settings, "ACTIVITY_LOG_TRANSACTION_MANAGEMENT", True
    ):
        transaction.on_commit(_guarded, using=write_db)
    else:
        _guarded()


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

    if activity == "created" and _created_activity_suppressed.get():
        # The caller writes these rows in one batch. See suppress_created_activity.
        return

    # The receiver runs inside save(). An error here must not escape: the caller's post-save work
    # (superseding in-flight runs on a disable) would be skipped for a row that is already written.
    try:
        # Diff now, write later. `after_update` is the caller's live instance, so a later save in
        # the same transaction would otherwise rewrite this row's changes.
        changes = changes_between(scope, previous=before_update, current=after_update)
        if activity == "updated" and not changes:
            # log_activity drops an update that moved nothing, so the organization lookup is wasted.
            return

        detail = Detail(
            changes=changes,
            name=instance.repository,
            # A row created by the API carries no installation until a sync binds it, so the
            # describer must not call it connected.
            type="connected" if instance.installation_id else "placeholder",
        )
        team_id = instance.team_id
        item_id = instance.id
        write_db = router.db_for_write(StamphogRepoConfig)

        def _write_row() -> None:
            log_activity(
                organization_id=_organization_id_for_team(team_id),
                team_id=team_id,
                user=user,
                was_impersonated=was_impersonated,
                item_id=item_id,
                scope=scope,
                activity=activity,
                detail=detail,
                using=write_db,
            )

        _log_after_product_commit(_write_row, write_db=write_db, team_id=team_id, item_id=str(item_id))
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

        write_db = router.db_for_write(StamphogRepoConfig)

        def _write_rows() -> None:
            # One lookup for the batch, and only when there is a row to write.
            organization_id = _organization_id_for_team(team_id)
            for entry in entries:
                entry["organization_id"] = organization_id

            bulk_log_activity(entries, using=write_db)

        _log_after_product_commit(_write_rows, write_db=write_db, team_id=team_id)
    except Exception as e:
        logger.warning("stamphog_activity_log_failed", team_id=team_id, exception=e)
        capture_exception(e)
        if settings.TEST:
            raise


def installation_webhook_trigger(*, delivery_id: str, action: str, installation_id: str) -> Trigger:
    """Name the GitHub delivery behind a row a webhook wrote.

    A webhook carries no PostHog user, so its rows are system rows. The trigger is what lets a
    reader tie a batch of repos back to the one event that touched them.
    """
    return Trigger(
        job_type="github_installation_webhook",
        job_id=delivery_id,
        payload={"action": action, "installation_id": installation_id},
    )


def log_repo_configs_created(
    team_id: int,
    rows: list[dict[str, Any]],
    *,
    user: "User | None" = None,
    was_impersonated: bool = False,
    trigger: Trigger | None = None,
) -> None:
    """Log the repo configs one pass connected, in a single batch.

    Pairs with `suppress_created_activity`: the caller silences the per-row receiver and calls this
    once. `notify=False` drops the internal-event fan-out, because one event per connected repo
    would put thousands of messages on the topic for a single click. The rows themselves still
    reach the activity feed. A webhook caller passes `user=None` and a `trigger` naming the
    delivery, so the batch reads as a system row a reader can trace back to one GitHub event.
    """
    if not rows:
        return

    write_db = router.db_for_write(StamphogRepoConfig)

    def _write_rows() -> None:
        organization_id = _organization_id_for_team(team_id)
        bulk_log_activity(
            [
                LogActivityEntry(
                    organization_id=organization_id,
                    team_id=team_id,
                    user=user,
                    item_id=row["id"],
                    scope="StamphogRepoConfig",
                    activity="created",
                    # The sync binds the installation as it creates the row, so it is connected.
                    detail=Detail(name=row["repository"], type="connected", trigger=trigger),
                    was_impersonated=was_impersonated,
                )
                for row in rows
            ],
            using=write_db,
            notify=False,
        )

    _log_after_product_commit(_write_rows, write_db=write_db, team_id=team_id)


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
        trigger=installation_webhook_trigger(delivery_id=delivery_id, action=action, installation_id=installation_id),
    )
