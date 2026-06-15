# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().
import dataclasses

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.managed_migrations.backend.models.batch_import_utils import (
    extract_batch_import_info,
    get_batch_import_created_by_info,
    get_batch_import_detail_name,
)
from products.managed_migrations.backend.models.batch_imports import BatchImport


@dataclasses.dataclass(frozen=True)
class BatchImportContext(ActivityContextBase):
    source_type: str
    content_type: str
    start_date: str | None
    end_date: str | None
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@mutable_receiver(model_activity_signal, sender=BatchImport)
def handle_batch_import_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    batch_import = after_update or before_update

    if not batch_import:
        return

    source_type, content_type, start_date, end_date = extract_batch_import_info(batch_import)
    created_by_user_id, created_by_user_email, created_by_user_name = get_batch_import_created_by_info(batch_import)
    detail_name = get_batch_import_detail_name(source_type, content_type)

    context = BatchImportContext(
        source_type=source_type,
        content_type=content_type,
        start_date=start_date,
        end_date=end_date,
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=batch_import.team.organization_id,
        team_id=batch_import.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=batch_import.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )


@receiver(pre_delete, sender=BatchImport)
def handle_batch_import_delete(sender, instance, **kwargs):
    user = get_current_user()
    was_impersonated = get_was_impersonated()

    source_type, content_type, start_date, end_date = extract_batch_import_info(instance)
    created_by_user_id, created_by_user_email, created_by_user_name = get_batch_import_created_by_info(instance)
    detail_name = get_batch_import_detail_name(source_type, content_type)

    context = BatchImportContext(
        source_type=source_type,
        content_type=content_type,
        start_date=start_date,
        end_date=end_date,
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope="BatchImport",
        activity="deleted",
        detail=Detail(name=detail_name, context=context),
    )
