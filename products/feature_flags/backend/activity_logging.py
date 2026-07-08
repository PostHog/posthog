from posthog.models.activity_logging.activity_log import Detail, Trigger, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Lives here, not in api/feature_flag.py, so it can wire at AppConfig.ready() without dragging that
# viewset (which pulls scipy via the dashboard -> error-tracking query runners cross-import) onto the
# django.setup() path. Flags are mutated outside web requests (cohort recalculation, scheduled
# changes), so the audit log must connect in every process.


@mutable_receiver(model_activity_signal, sender=FeatureFlag)
def handle_feature_flag_change(
    sender,
    scope,
    before_update,
    after_update,
    activity,
    was_impersonated=False,
    **kwargs,
):
    # Extract scheduled change context if present
    scheduled_change_context = getattr(after_update, "_scheduled_change_context", {})
    scheduled_change_id = scheduled_change_context.get("scheduled_change_id")
    is_scheduled_change = scheduled_change_id is not None

    # Create trigger info for scheduled changes
    trigger = None
    if is_scheduled_change:
        trigger = Trigger(
            job_type="scheduled_change",
            job_id=str(scheduled_change_id),
            payload={"scheduled_change_id": scheduled_change_id},
        )

    changes = changes_between(scope, previous=before_update, current=after_update)
    resolved_activity = activity
    deleted_change = next((change for change in changes if change.field == "deleted"), None)
    if deleted_change:
        if bool(deleted_change.after):
            resolved_activity = "deleted"
        elif bool(deleted_change.before):
            resolved_activity = "restored"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.last_modified_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=resolved_activity,
        detail=Detail(
            changes=changes,
            name=after_update.key,
            trigger=trigger,
        ),
    )
